"""
Standalone CAPTCHA solver utility.

Launches a HEADED browser with matching stealth parameters, loads the
exported storage_state from a blocked Executor, and lets the user
solve the CAPTCHA manually.

Usage:
    python solve_captcha.py --state /tmp/captcha_state_xxx.json --url https://example.com/blocked
"""

import argparse
import asyncio

from playwright.async_api import async_playwright
from playwright_stealth import Stealth


async def solve_captcha(state_path: str, url: str):
    """
    Launch a headed browser, load exported state, navigate to blocked URL.

    The user solves the CAPTCHA manually, then presses Enter.
    The solved storage_state is exported to a new file.
    """
    p = await async_playwright().start()

    # Launch HEADED browser (user needs to see and interact with it)
    browser = await p.chromium.launch(headless=False)
    context = await browser.new_context(
        storage_state=state_path,
        viewport={"width": 1280, "height": 720},
    )
    stealth = Stealth()
    await stealth.apply_stealth(context)

    page = await context.new_page()

    print(f"Navigating to: {url}")
    await page.goto(url, wait_until="networkidle")

    print("\n" + "=" * 50)
    print("  Solve the CAPTCHA in the browser window.")
    print("  Press Enter here when done...")
    print("=" * 50)

    input()

    # Export solved state
    solved_path = state_path.replace(".json", "_solved.json")
    await context.storage_state(path=solved_path)

    await browser.close()
    await p.stop()

    print(f"\nSolved state saved to: {solved_path}")
    print("The agent will resume with this state automatically.")


def main():
    parser = argparse.ArgumentParser(
        description="CAPTCHA solver — opens a headed browser for manual CAPTCHA solving"
    )
    parser.add_argument(
        "--state", required=True,
        help="Path to the exported storage_state.json from the blocked Executor"
    )
    parser.add_argument(
        "--url", required=True,
        help="URL where the CAPTCHA was encountered"
    )

    args = parser.parse_args()
    asyncio.run(solve_captcha(args.state, args.url))


if __name__ == "__main__":
    main()
