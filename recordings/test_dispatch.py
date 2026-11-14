import asyncio
from playwright.async_api import async_playwright

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
        context = await browser.new_context(permissions=["microphone"])
        page = await context.new_page()

        page.on("response", lambda res: print(f"[HTTP {res.status}] {res.url}") if "/api/v1/" in res.url else None)

        print("1. Goto practice...")
        await page.goto("http://127.0.0.1:5180/practice/ex1_shortest_subarray?spec=v1_positive_only", wait_until="networkidle")
        await page.wait_for_timeout(2000)

        print("2. Click Start Session...")
        await page.locator("button.big-start-session-btn").click()
        await page.wait_for_timeout(4000)

        print("3. Send explanation...")
        await page.locator("textarea[aria-label='Editable Learner Transcript']").fill("I will maintain a sliding window with left and right pointers.")
        await page.locator("button.mentor-send-action").click()
        await page.wait_for_timeout(3000)

        print("4. Confirm explanation...")
        await page.locator("button[data-testid='confirm-claim-btn']").click()
        await page.wait_for_timeout(3000)

        print("5. Dispatch click to Issue Challenge Input...")
        issue_btn = page.locator("button:has-text('Issue Challenge Input')")
        print(f"issue_btn count: {await issue_btn.count()}")
        await issue_btn.dispatch_event("click")
        await page.wait_for_timeout(3000)

        print("6. Check for prediction input...")
        pred_input = page.locator("input[aria-label='Predicted Integer Output']")
        print(f"pred_input count: {await pred_input.count()}")
        if await pred_input.count() > 0:
            await pred_input.fill("2")
            await page.locator("input[aria-label='Prediction Rationale']").fill("Subarray [4, 3] sum 7 length 2")
            print("Filled prediction! Proposing claim...")
            await page.locator("button:has-text('Propose Claim')").dispatch_event("click")
            await page.wait_for_timeout(3000)
            print("Confirming claim and running in sandbox...")
            await page.locator("button[data-testid='confirm-claim-btn']").click()
            await page.wait_for_timeout(5000)

            print("7. Checking Level 1 Hint...")
            hint_btn = page.locator("button:has-text('Level 1 Hint')")
            print(f"hint_btn visible: {await hint_btn.is_visible()}, disabled: {await hint_btn.is_disabled()}")
            if await hint_btn.is_visible() and not await hint_btn.is_disabled():
                print("Clicking Level 1 Hint...")
                await hint_btn.click()
                await page.wait_for_timeout(6000)

        await context.close()
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
