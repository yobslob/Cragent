"""
BrowserContext factory with stealth, auth, proxy, and UA randomization.
"""

import random
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
)
from playwright_stealth import Stealth

from src.config import Config

# Pool of realistic user-agent strings for randomization
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def get_proxy(config: Config, executor_index: int = 0) -> Optional[dict]:
    """Get a proxy from the configured list using round-robin or random selection."""
    if not config.proxy_list:
        return None

    if config.proxy_rotation == "random":
        proxy_url = random.choice(config.proxy_list)
    else:
        proxy_url = config.proxy_list[executor_index % len(config.proxy_list)]

    return {"server": proxy_url}


async def create_browser_context(
    playwright: Playwright,
    config: Config,
    storage_state: Optional[str] = None,
    proxy: Optional[dict] = None,
) -> tuple[Browser, BrowserContext, Page]:
    """
    Create a fully configured browser context with stealth, auth, and proxy.

    Returns (browser, context, page) tuple. Caller is responsible for cleanup.
    """
    launch_kwargs = {"headless": config.headless}
    if proxy:
        launch_kwargs["proxy"] = proxy

    browser = await playwright.chromium.launch(**launch_kwargs)

    context_kwargs = {
        "viewport": {"width": config.viewport_width, "height": config.viewport_height},
        "user_agent": random.choice(_USER_AGENTS),
    }
    if storage_state:
        context_kwargs["storage_state"] = storage_state

    context = await browser.new_context(**context_kwargs)

    if config.stealth_enabled:
        stealth = Stealth()
        await stealth.apply_stealth_async(context)

    page = await context.new_page()

    return browser, context, page


async def close_context(browser: Optional[Browser], context: Optional[BrowserContext]):
    """Safely close a browser context and browser instance."""
    try:
        if context:
            await context.close()
    except Exception:
        pass
    try:
        if browser:
            await browser.close()
    except Exception:
        pass
