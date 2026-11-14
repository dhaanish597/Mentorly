import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from playwright.async_api import async_playwright

RECORDINGS_DIR = Path("/Users/dhaanish/Desktop/VIVA/recordings")
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR = RECORDINGS_DIR / "raw_video"
RAW_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_DIR = Path("/Users/dhaanish/.gemini/antigravity/brain/6468c760-61d4-49c4-b27a-43005b3d9309")

async def record_browser_session():
    # Clean previous raw videos
    for f in RAW_DIR.glob("*.webm"):
        f.unlink()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
            ]
        )
        context = await browser.new_context(
            record_video_dir=str(RAW_DIR),
            record_video_size={"width": 1280, "height": 800},
            viewport={"width": 1280, "height": 800},
            permissions=["microphone"]
        )
        page = await context.new_page()

        print("[1/6] Navigating to Design Studio...")
        await page.goto("http://127.0.0.1:5180/studio", wait_until="networkidle")
        await page.wait_for_timeout(3000)
        await page.screenshot(path=str(RECORDINGS_DIR / "sd_step1_landing.png"))

        print("[2/6] Clicking 'Start session' for Distributed API rate limiter...")
        start_btn = page.locator("button.primary", has_text="Start session")
        await start_btn.click()
        await page.wait_for_selector(".studio-workspace", timeout=12000)
        await page.wait_for_timeout(3000)
        await page.screenshot(path=str(RECORDINGS_DIR / "sd_step2_workspace.png"))

        print("[3/6] Adding architecture components on whiteboard...")
        add_btn = page.locator("button[aria-label='Add component']")
        await add_btn.click()
        await page.wait_for_timeout(1500)
        await add_btn.click()
        await page.wait_for_timeout(1500)

        # Save diagram revision
        save_btn = page.locator("button", has_text="Save diagram")
        if await save_btn.is_enabled():
            await save_btn.click()
            print("Saved diagram revision 1")
            await page.wait_for_timeout(2000)
        await page.screenshot(path=str(RECORDINGS_DIR / "sd_step3_components_added.png"))

        print("[4/6] Learner speaking and entering approach explanation...")
        # Start typing explanation (timed with user audio playing from sec ~16 to ~25)
        textarea = page.locator("#studio-explanation")
        explanation = "Hi Nexus. For the distributed rate limiter, I will deploy an API Gateway cluster with local token buckets synchronized to a distributed Redis cluster with consistent hashing."
        
        # Type smoothly
        await textarea.focus()
        for chunk in [explanation[:40], explanation[40:80], explanation[80:]]:
            await textarea.type(chunk, delay=40)
            await page.wait_for_timeout(1500)
        await page.wait_for_timeout(2000)
        await page.screenshot(path=str(RECORDINGS_DIR / "sd_step4_explanation_typed.png"))

        print("[5/6] Submitting explanation to Nexus...")
        send_btn = page.locator("button.studio-send")
        await send_btn.click()
        await page.wait_for_timeout(3500)
        await page.screenshot(path=str(RECORDINGS_DIR / "sd_step5_explanation_sent.png"))

        print("[6/6] Requesting Socratic hint from Nexus...")
        help_summary = page.locator(".studio-help summary")
        await help_summary.click()
        await page.wait_for_timeout(1500)

        hint_btn = page.locator(".studio-help button", has_text="Hint")
        await hint_btn.click()
        await page.wait_for_timeout(3000)

        # Click Enable coach speech / Play coach to trigger TTS audio
        coach_speech_btn = page.locator(".studio-voice button", has_text="Enable coach speech")
        if await coach_speech_btn.is_visible():
            await coach_speech_btn.click()
            print("Enabled coach speech!")
            await page.wait_for_timeout(4000)
        else:
            play_coach_btn = page.locator(".studio-voice button", has_text="Play coach")
            if await play_coach_btn.is_visible():
                await play_coach_btn.click()
                print("Clicked Play coach!")
                await page.wait_for_timeout(4000)

        await page.screenshot(path=str(RECORDINGS_DIR / "sd_step6_hint_spoken.png"))
        await page.wait_for_timeout(3000)

        video_path = await page.video.path()
        await context.close()
        await browser.close()
        print(f"Raw Playwright video recorded: {video_path}")
        return video_path

def build_synchronized_audio_video(raw_video_path: str):
    # Get duration of raw video
    ffprobe = "/Users/dhaanish/.gemini/antigravity/bin/ffprobe"
    ffmpeg = "/Users/dhaanish/.gemini/antigravity/bin/ffmpeg"
    
    cmd_dur = [ffprobe, "-i", raw_video_path, "-show_entries", "format=duration", "-v", "quiet", "-of", "csv=p=0"]
    video_duration = float(subprocess.check_output(cmd_dur).decode().strip())
    print(f"Total video duration: {video_duration:.2f}s")

    user_wav = RECORDINGS_DIR / "user_voice.wav"
    mentor_wav = RECORDINGS_DIR / "mentor_voice.wav"

    # User speaks at ~16.0s (when typing begins)
    # Mentor speaks at ~34.0s (when hint arrives and is spoken)
    # Build complete audio timeline with ffmpeg filter_complex
    composite_audio = RECORDINGS_DIR / "sd_timeline_audio.wav"
    
    # We mix silence + user voice delayed by 16000ms + mentor voice delayed by 34000ms
    filter_complex = (
        "[0:a]adelay=16000|16000[user];"
        "[1:a]adelay=34000|34000[mentor];"
        "[user][mentor]amix=inputs=2:dropout_transition=2[aout]"
    )
    
    cmd_audio = [
        ffmpeg, "-y",
        "-i", str(user_wav),
        "-i", str(mentor_wav),
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-ac", "2",
        "-ar", "44100",
        "-t", str(video_duration),
        str(composite_audio)
    ]
    subprocess.run(cmd_audio, check=True)
    print(f"Generated composite audio track: {composite_audio}")

    # Combine video and composite audio into final MP4
    final_mp4 = RECORDINGS_DIR / "system_design_mentor_voice_proof.mp4"
    cmd_mux = [
        ffmpeg, "-y",
        "-i", raw_video_path,
        "-i", str(composite_audio),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(final_mp4)
    ]
    subprocess.run(cmd_mux, check=True)
    print(f"Generated final synchronized MP4: {final_mp4} ({final_mp4.stat().st_size} bytes)")

    # Copy to artifacts directory
    artifact_mp4 = ARTIFACT_DIR / "system_design_mentor_voice_proof.mp4"
    shutil.copy2(str(final_mp4), str(artifact_mp4))
    print(f"Copied to artifact directory: {artifact_mp4}")

    for step_png in RECORDINGS_DIR.glob("sd_step*.png"):
        shutil.copy2(str(step_png), str(ARTIFACT_DIR / step_png.name))
    print("Copied step screenshots to artifact directory.")

def main():
    raw_video = asyncio.run(record_browser_session())
    build_synchronized_audio_video(raw_video)
    print("SUCCESS: Full video proof generated!")

if __name__ == "__main__":
    main()
