"""
Auth Bootstrap node — performs initial login and exports authenticated storage_state.

Runs once before the main loop (if credentials are available) to create a
shared authenticated session that all Executors can inherit.
"""

import hashlib
import os
import tempfile

from playwright.async_api import async_playwright

from src.config import Config
from src.state import AgentState
from src.browser.context_manager import create_browser_context, close_context


# Common selectors for login form elements
_USERNAME_SELECTORS = [
    'input[type="email"]',
    'input[name="username"]',
    'input[name="email"]',
    'input[name="login"]',
    'input[id="username"]',
    'input[id="email"]',
    '#ap_email',  # Amazon
]

_PASSWORD_SELECTORS = [
    'input[type="password"]',
    'input[name="password"]',
    '#ap_password',  # Amazon
]

_SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    '#signInSubmit',  # Amazon
    'button:has-text("Sign in")',
    'button:has-text("Log in")',
    'button:has-text("Login")',
    'button:has-text("Submit")',
]


async def _find_and_fill(page, selectors: list[str], value: str) -> bool:
    """Try multiple selectors to find and fill a form field."""
    for selector in selectors:
        try:
            element = await page.query_selector(selector)
            if element:
                await element.fill(value)
                return True
        except Exception:
            continue
    return False


async def _find_and_click(page, selectors: list[str]) -> bool:
    """Try multiple selectors to find and click a submit button."""
    for selector in selectors:
        try:
            element = await page.query_selector(selector)
            if element:
                await element.click()
                return True
        except Exception:
            continue
    return False


def _extract_domain(url: str) -> str:
    """Extract domain from URL for credential lookup."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.hostname or ""
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


async def auth_bootstrap_node(state: AgentState, config: Config) -> dict:
    """
    Auth Bootstrap node: performs initial login and exports storage_state.

    1. If no credentials exist, returns {shared_auth_state: None}
    2. Launches a single stealth browser context
    3. Navigates to login page
    4. Fills username/password, submits
    5. Exports storage_state.json
    6. Returns path in {shared_auth_state: path}
    """
    credentials = state.get("credentials", {})
    if not credentials:
        return {"shared_auth_state": None}

    current_url = state.get("current_url", state.get("target_url", ""))
    domain = _extract_domain(current_url)

    # Find credentials for this domain
    creds = credentials.get(domain)
    if not creds:
        # Try partial match
        for key in credentials:
            if key in domain or domain in key:
                creds = credentials[key]
                break

    if not creds:
        return {"shared_auth_state": None}

    username = creds.get("username", "")
    password = creds.get("password", "")
    if not username or not password:
        return {"shared_auth_state": None}

    browser = None
    context = None
    playwright_instance = None

    try:
        playwright_instance = await async_playwright().start()
        browser, context, page = await create_browser_context(
            playwright_instance, config
        )

        # Try common login URL patterns
        login_url = None
        for pattern in config.login_url_patterns:
            test_url = current_url.rstrip("/") + pattern
            try:
                response = await page.goto(test_url, wait_until="networkidle", timeout=10000)
                if response and response.ok:
                    login_url = test_url
                    break
            except Exception:
                continue

        if not login_url:
            # Try navigating to the base URL (might redirect to login)
            await page.goto(current_url, wait_until="networkidle", timeout=15000)

        # Fill username
        filled_user = await _find_and_fill(page, _USERNAME_SELECTORS, username)
        if not filled_user:
            return {"shared_auth_state": None}

        # Some login forms have separate steps for username and password
        # Try submitting username first
        has_password = await page.query_selector('input[type="password"]')
        if not has_password:
            await _find_and_click(page, _SUBMIT_SELECTORS)
            await page.wait_for_load_state("networkidle")

        # Fill password
        filled_pass = await _find_and_fill(page, _PASSWORD_SELECTORS, password)
        if not filled_pass:
            return {"shared_auth_state": None}

        # Submit
        await _find_and_click(page, _SUBMIT_SELECTORS)
        await page.wait_for_load_state("networkidle")

        # Export storage state
        domain_hash = hashlib.md5(domain.encode()).hexdigest()[:8]
        state_path = os.path.join(tempfile.gettempdir(), f"auth_state_{domain_hash}.json")
        await context.storage_state(path=state_path)

        return {"shared_auth_state": state_path}

    except Exception:
        return {"shared_auth_state": None}

    finally:
        await close_context(browser, context)
        if playwright_instance:
            try:
                await playwright_instance.stop()
            except Exception:
                pass
