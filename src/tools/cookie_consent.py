"""
Cookie consent banner dismissal.

Attempts to dismiss common cookie consent banners after first navigation
to a new domain. Silent no-op if no banner found.
"""

from playwright.async_api import Page


# Common cookie consent selectors (ordered by prevalence)
COOKIE_CONSENT_SELECTORS = [
    '#onetrust-accept-btn-handler',
    'button[aria-label*="Accept"]',
    'button[aria-label*="accept"]',
    '[data-testid="cookie-accept"]',
    '.cookie-banner-accept',
    '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
    '.cc-btn.cc-allow',
]


async def dismiss_cookie_consent(page: Page, timeout: int = 3000) -> bool:
    """
    Attempt to dismiss a cookie consent banner.

    Tries each known selector until one is found and clicked.
    Returns True if a banner was dismissed, False otherwise.
    Silent no-op if no banner exists.
    """
    for selector in COOKIE_CONSENT_SELECTORS:
        try:
            btn = await page.wait_for_selector(selector, timeout=timeout)
            if btn:
                await btn.click()
                await page.wait_for_timeout(500)  # Wait for banner animation
                return True
        except Exception:
            continue

    return False
