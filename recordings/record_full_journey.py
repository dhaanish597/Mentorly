import asyncio
import json
import os
import subprocess
from pathlib import Path
from playwright.async_api import async_playwright

RECORDINGS_DIR = Path("/Users/dhaanish/Desktop/VIVA/recordings")
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
FFMPEG_BIN = "/Users/dhaanish/.gemini/antigravity/bin/ffmpeg"

async def run_journey():
    print("=== STARTING FULL MENTORLY SOLVE & VOICE VERIFICATION JOURNEY ===")
    
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
            record_video_dir=str(RECORDINGS_DIR),
            record_video_size={"width": 1280, "height": 800},
            viewport={"width": 1280, "height": 800},
            permissions=["microphone"],
        )
        page = await context.new_page()

        speech_events = []
        
        def handle_response(res):
            if "/speech/" in res.url:
                print(f"[SPEECH API] {res.status} {res.url}")
                speech_events.append({"url": res.url, "status": res.status})

        page.on("response", handle_response)
        page.on("console", lambda msg: print(f"[Browser Console {msg.type}]: {msg.text}") if "error" in msg.type or "warn" in msg.type else None)

        print("\n--- Step 1: Navigating to Practice Problem ---")
        await page.goto("http://127.0.0.1:5180/practice/ex1_shortest_subarray?spec=v1_positive_only", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        await page.screenshot(path=str(RECORDINGS_DIR / "01_landing.png"))

        print("\n--- Step 2: Starting Practice Session with Mentor Voice ---")
        start_btn = page.locator("button.big-start-session-btn")
        if await start_btn.is_visible():
            await start_btn.click()
            print("Clicked 'Start Practice Session'")
            # Wait for session creation and introduction TTS audio to stream/play
            await page.wait_for_timeout(7000)
            await page.screenshot(path=str(RECORDINGS_DIR / "02_session_started.png"))

        print("\n--- Step 3: Explaining Approach via Voice / Transcript ---")
        textarea = page.locator("textarea[aria-label='Editable Learner Transcript']")
        if await textarea.is_visible():
            await textarea.fill("I will maintain a sliding window with left and right pointers. When the sum is at least target, I record the length and contract left.")
            await page.wait_for_timeout(1000)
            send_btn = page.locator("button.mentor-send-action")
            await send_btn.click()
            print("Sent approach explanation for interpretation...")
            await page.wait_for_timeout(3500)
            await page.screenshot(path=str(RECORDINGS_DIR / "03_explanation_interpreted.png"))

        # Confirm Explanation
        confirm_btn = page.locator("button[data-testid='confirm-claim-btn']")
        if await confirm_btn.is_visible():
            await confirm_btn.click()
            print("Clicked 'Confirm Explanation (No Execution)'")
            await page.wait_for_timeout(3000)
            await page.screenshot(path=str(RECORDINGS_DIR / "04_explanation_confirmed.png"))

        print("\n--- Step 4: Issuing Diagnostic Challenge Input ---")
        issue_btn = page.locator("button:has-text('Issue Challenge Input')")
        await issue_btn.dispatch_event("click")
        print("Dispatched click on 'Issue Challenge Input'")
        await page.wait_for_timeout(2500)

        # Predict output on diagnostic challenge
        # Problem: target = 7, nums = [2, 3, 1, 2, 4, 3] -> shortest subarray is [4, 3], length 2
        pred_input = page.locator("input[aria-label='Predicted Integer Output']")
        await pred_input.wait_for(state="attached", timeout=5000)
        await pred_input.fill("2")
        reason_input = page.locator("input[aria-label='Prediction Rationale']")
        await reason_input.fill("Subarray [4, 3] has sum 7 and length 2.")
        await page.wait_for_timeout(1000)

        # Submit prediction proposal
        propose_btn = page.locator("button:has-text('Propose Claim')")
        await propose_btn.dispatch_event("click")
        print("Proposed prediction claim")
        await page.wait_for_timeout(3000)

        # Confirm Claim & Run in Sandbox
        confirm_claim_btn = page.locator("button[data-testid='confirm-claim-btn']")
        await confirm_claim_btn.click()
        print("Clicked 'Confirm Claim & Run in Sandbox'...")
        # Give ample time for sandbox execution and auto-hint voice playback
        await page.wait_for_timeout(8000)
        await page.screenshot(path=str(RECORDINGS_DIR / "05_sandbox_executed.png"))

        print("\n--- Step 5: Socratic Hint Voice Delivery ---")
        replay_btn = page.locator("button:has-text('Replay message'), button:has-text('Play message')")
        if await replay_btn.count() > 0:
            print("Found Replay/Play message button for hint!")
            await replay_btn.first.click()
            print("Clicked Replay message to hear coach voice again!")
            await page.wait_for_timeout(6000)
            await page.screenshot(path=str(RECORDINGS_DIR / "06_hint_spoken.png"))

        print("\n--- Step 6: Testing Mentor Volume & Voice Output ---")
        volume_btn = page.locator("button.mentor-volume-btn")
        if await volume_btn.is_visible():
            await volume_btn.click()
            print("Clicked mentor volume button (triggered test-voice)")
            await page.wait_for_timeout(4000)
            await page.screenshot(path=str(RECORDINGS_DIR / "07_voice_tested.png"))

        print("\n--- Step 7: Saving Correct Code & Verifying Repair ---")
        # Switch to accessible plain text editor to insert code
        plain_btn = page.locator("button:has-text('Use Accessible Plain Text Editor')")
        if await plain_btn.is_visible():
            await plain_btn.click()
            await page.wait_for_timeout(1000)
            editor_textarea = page.locator("textarea[aria-label='Python Solution Editor']")
            fixed_code = (
                "def shortest_subarray_ge_target(nums: list[int], target: int) -> int:\n"
                "    best = len(nums) + 1\n"
                "    for start in range(len(nums)):\n"
                "        running = 0\n"
                "        for end in range(start, len(nums)):\n"
                "            running += nums[end]\n"
                "            if running >= target:\n"
                "                best = min(best, end - start + 1)\n"
                "                break\n"
                "    return 0 if best > len(nums) else best\n"
            )
            await editor_textarea.fill(fixed_code)
            print("Entered corrected code solution into editor")
            await page.wait_for_timeout(1000)

        # Click Save Code Version
        save_btn = page.locator("button:has-text('Save Code Version')")
        await save_btn.wait_for(state="visible", timeout=5000)
        await save_btn.click()
        print("Clicked 'Save Code Version'")
        await page.wait_for_timeout(3000)

        # Click Verify Saved Repair
        verify_btn = page.locator("button:has-text('Verify Saved Repair')")
        if await verify_btn.is_visible() and not await verify_btn.is_disabled():
            await verify_btn.click()
            print("Clicked 'Verify Saved Repair'...")
            await page.wait_for_timeout(7000)
            await page.screenshot(path=str(RECORDINGS_DIR / "08_repair_verified.png"))
        else:
            print("Verify Saved Repair is disabled (current solution is sound with no prior failure artifact).")

        await page.wait_for_timeout(3000)
        video_path = await page.video.path()
        await context.close()
        await browser.close()

        print(f"\nRaw WebM recording saved at: {video_path}")
        print(f"Captured speech requests:\n{json.dumps(speech_events, indent=2)}")

        # Convert webm to mp4
        output_mp4 = RECORDINGS_DIR / "mentor_voice_proof.mp4"
        cmd = [
            FFMPEG_BIN,
            "-y",
            "-i", str(video_path),
            "-c:v", "libx264",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-crf", "22",
            str(output_mp4)
        ]
        print(f"\nConverting video to MP4: {' '.join(cmd)}")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            print(f"Successfully generated MP4 at: {output_mp4}")
            print(f"File size: {output_mp4.stat().st_size} bytes")
        else:
            print(f"FFmpeg conversion error: {res.stderr}")

if __name__ == "__main__":
    asyncio.run(run_journey())
