import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright

VIDEO_DIR = Path("/Users/dhaanish/Desktop/VIVA/recordings")
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

async def main():
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
            record_video_dir=str(VIDEO_DIR),
            record_video_size={"width": 1280, "height": 720},
            viewport={"width": 1280, "height": 720},
            permissions=["microphone"],
        )
        page = await context.new_page()

        audio_responses = []

        page.on("console", lambda msg: print(f"[Browser Console {msg.type}]: {msg.text}"))
        page.on("pageerror", lambda err: print(f"[Browser Page Error]: {err}"))
        page.on("request", lambda req: print(f"[Browser Request]: {req.method} {req.url}") if "/api/" in req.url else None)
        page.on("response", lambda res: print(f"[Browser Response]: {res.status} {res.url}") if "/api/" in res.url else None)

        print("1. Navigating to practice problem...")
        await page.goto("http://127.0.0.1:5180/practice/ex1_shortest_subarray?spec=v1_positive_only", wait_until="networkidle")
        await page.wait_for_timeout(2000)

        # Take screenshot of initial state
        await page.screenshot(path=str(VIDEO_DIR / "step1_landing.png"))
        print("Captured step1_landing.png")

        # Click Start Practice Session
        print("2. Clicking 'Start Practice Session'...")
        start_btn = page.locator("button.big-start-session-btn")
        if await start_btn.is_visible():
            await start_btn.click()
            print("Clicked Start Practice Session!")
            await page.wait_for_timeout(4000)
            await page.screenshot(path=str(VIDEO_DIR / "step2_session_started.png"))
            print("Captured step2_session_started.png")

        # Verify introduction audio was requested
        intro_audio = [r for r in audio_responses if "introduction" in r["url"]]
        print(f"Introduction audio responses: {intro_audio}")

        # Explain approach in the textarea
        print("3. Typing explanation...")
        textarea = page.locator("textarea[aria-label='Editable Learner Transcript']")
        if await textarea.is_visible():
            await textarea.fill("I will maintain a sliding window with left and right pointers. When the sum is at least target, I record the length and contract left.")
            await page.wait_for_timeout(1000)
            await page.screenshot(path=str(VIDEO_DIR / "step3_explanation_typed.png"))

            # Click send action
            send_btn = page.locator("button.mentor-send-action")
            if await send_btn.is_visible():
                await send_btn.click()
                print("Proposed transcript interpretation!")
                await page.wait_for_timeout(3000)
                await page.screenshot(path=str(VIDEO_DIR / "step4_interpretation_proposed.png"))

        # Confirm Explanation
        confirm_btn = page.locator("button[data-testid='confirm-claim-btn']")
        if await confirm_btn.is_visible():
            print("4. Confirming explanation...")
            await confirm_btn.click()
            await page.wait_for_timeout(3000)
            await page.screenshot(path=str(VIDEO_DIR / "step5_explanation_confirmed.png"))

        # Test Voice Button or Unmute
        volume_btn = page.locator("button.mentor-volume-btn")
        if await volume_btn.is_visible():
            print("5. Clicking mentor volume button to trigger voice test...")
            await volume_btn.click()
            await page.wait_for_timeout(3000)
            await page.screenshot(path=str(VIDEO_DIR / "step6_volume_tested.png"))

        await page.wait_for_timeout(2000)
        video_path = await page.video.path()
        await context.close()
        await browser.close()

        print(f"Video recorded at: {video_path}")
        print(f"All speech responses captured: {json.dumps(audio_responses, indent=2)}")

if __name__ == "__main__":
    asyncio.run(main())
