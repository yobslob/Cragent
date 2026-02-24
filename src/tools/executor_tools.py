"""
Executor tools — 9 tools (6 core + 3 edge-case) for browser-based test execution.

All tools operate on a shared ExecutorContext object that maintains the page,
node-ID map, credential vault, and result state.
"""

import random
from typing import Optional
from urllib.parse import urlparse

from langchain_core.tools import tool
from playwright.async_api import Page

from src.config import Config
from src.security.vault import CredentialVault
from src.browser.a11y_tree import (
    assign_node_ids,
    tree_to_compact_string,
)
from src.browser.dom_fallback import get_a11y_tree_with_fallback
from src.tools.cookie_consent import dismiss_cookie_consent
from src.tools.js_sandbox import evaluate_javascript_safe
from src.state import TestResultModel


class ExecutorContext:
    """
    Shared mutable context for all Executor tools within a single test execution.

    Maintains browser page, node-ID mapping, credential vault, and result state.
    """

    def __init__(
        self,
        page: Page,
        vault: CredentialVault,
        config: Config,
    ):
        self.page = page
        self.vault = vault
        self.config = config
        self.node_id_map: dict = {}
        self.test_result: Optional[TestResultModel] = None
        self.is_done: bool = False
        self._visited_domains: set[str] = set()

    def _get_domain(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.hostname or ""


def create_executor_tools(context: ExecutorContext) -> list:
    """
    Factory that creates all 9 Executor tools with the shared context bound via closure.
    """
    config = context.config

    # --- Core Tool 1: navigate_to ---
    @tool
    async def navigate_to(url: str) -> str:
        """Navigate to a URL. Waits for network idle and DOM stability.
        Auto-dismisses cookie consent banners on first visit to a new domain.
        """
        try:
            page = context.page

            # Random delay to avoid rate limiting
            delay_range = config.inter_request_delay_ms
            await page.wait_for_timeout(
                random.randint(delay_range[0], delay_range[1])
            )

            await page.goto(
                url,
                wait_until="networkidle",
                timeout=config.navigation_timeout_seconds * 1000,
            )

            # DOM stability check: compare aria snapshots with 500ms gap
            snap1 = await page.locator("body").aria_snapshot()
            await page.wait_for_timeout(500)
            snap2 = await page.locator("body").aria_snapshot()
            if snap1 != snap2:
                # Page still hydrating, wait a bit more
                await page.wait_for_timeout(1000)

            # Cookie consent dismissal on first visit to domain
            domain = context._get_domain(url)
            if domain and domain not in context._visited_domains:
                context._visited_domains.add(domain)
                if config.dismiss_cookie_consent:
                    await dismiss_cookie_consent(
                        page, timeout=config.cookie_consent_timeout_ms
                    )

            return f"Navigated to {page.url}"

        except Exception as e:
            return f"Navigation error: {str(e)}"

    # --- Core Tool 2: get_page_state ---
    @tool
    async def get_page_state(focus_element_id: Optional[str] = None) -> str:
        """Get the current page state as an accessibility tree with [node-XX] IDs.

        Each interactive element gets a unique ID for use with interact_with_element.
        IDs are regenerated on each call — do NOT reuse old IDs.

        Optional: pass focus_element_id (a CSS selector) to scope to a subtree.
        """
        try:
            tree = await get_a11y_tree_with_fallback(
                context.page,
                focus_section=focus_element_id,
                max_nodes=config.a11y_tree_max_nodes,
            )

            if not tree:
                # Last resort
                text = await context.page.evaluate(
                    "document.body.innerText.slice(0, 3000)"
                )
                context.node_id_map.clear()
                return f"[No interactive elements found. Page text:]\n{text}"

            annotated_tree, id_map = assign_node_ids(tree)

            # Update the shared node-ID map (clear old, populate new)
            context.node_id_map.clear()
            context.node_id_map.update(id_map)

            return tree_to_compact_string(annotated_tree)

        except Exception as e:
            return f"Error getting page state: {str(e)}"

    # --- Core Tool 3: interact_with_element ---
    @tool
    async def interact_with_element(
        element_id: str,
        action_type: str,
        input_value: Optional[str] = None,
    ) -> str:
        """Interact with a page element by its [node-XX] ID.

        Args:
            element_id: The [node-XX] ID from get_page_state output.
            action_type: One of: click, type, select, hover
            input_value: Required for type and select actions.
                         For credentials, use {{vault:password}} or {{vault:username}}.
        """
        if element_id not in context.node_id_map:
            return (
                f"Element {element_id} not found in current page state. "
                "Call get_page_state() first to get fresh element IDs."
            )

        element_info = context.node_id_map[element_id]
        role = element_info.get("role", "")
        name = element_info.get("name", "")

        # Resolve vault tokens
        resolved_value = input_value
        if input_value and context.vault.is_vault_token(input_value):
            try:
                resolved_value = context.vault.resolve_token(
                    input_value, context.page.url
                )
            except Exception as e:
                return f"Vault error: {str(e)}"

        try:
            # Build a Playwright locator from role + name
            locator = context.page.get_by_role(role, name=name, exact=False)

            # If multiple matches, try to narrow down
            count = await locator.count()
            if count == 0:
                return (
                    f"No element found matching role='{role}' name='{name}'. "
                    "The page may have changed. Call get_page_state() for fresh IDs."
                )
            if count > 1:
                locator = locator.first

            if action_type == "click":
                await locator.click(timeout=5000)
                return f"Clicked {element_id} ({role} '{name}')"

            elif action_type == "type":
                if resolved_value is None:
                    return "Error: input_value is required for 'type' action."
                await locator.fill(resolved_value, timeout=5000)
                # Report with vault token, not actual value
                display_value = input_value if input_value != resolved_value else resolved_value
                return f"Typed into {element_id} ({role} '{name}'): {display_value}"

            elif action_type == "select":
                if resolved_value is None:
                    return "Error: input_value is required for 'select' action."
                await locator.select_option(resolved_value, timeout=5000)
                return f"Selected '{resolved_value}' in {element_id} ({role} '{name}')"

            elif action_type == "hover":
                await locator.hover(timeout=5000)
                return f"Hovered over {element_id} ({role} '{name}')"

            else:
                return (
                    f"Unknown action_type '{action_type}'. "
                    "Use one of: click, type, select, hover"
                )

        except Exception as e:
            return f"Interaction error on {element_id}: {str(e)}"

    # --- Core Tool 4: navigate_back ---
    @tool
    async def navigate_back() -> str:
        """Go back to the previous page (browser back button)."""
        try:
            await context.page.go_back(wait_until="networkidle")
            return f"Navigated back to {context.page.url}"
        except Exception as e:
            return f"Navigation back error: {str(e)}"

    # --- Core Tool 5: report_test_result ---
    @tool
    async def report_test_result(status: str, observations: str) -> str:
        """Report the final test result. ALWAYS call this before done_tool().

        Args:
            status: "PASS" or "FAIL"
            observations: Factual description of what was observed.
                         NEVER include credential values.
        """
        if status not in ("PASS", "FAIL", "BLOCKED_CAPTCHA"):
            status = "FAIL"

        context.test_result = TestResultModel(
            test_id="",  # Filled by the executor node
            status=status,
            observations=observations,
        )
        return f"Test result recorded: {status}"

    # --- Core Tool 6: done_tool ---
    @tool
    async def done_tool() -> str:
        """Signal that this test execution is complete.
        ALWAYS call this after report_test_result.
        """
        context.is_done = True
        return "Execution complete."

    # --- Edge-Case Tool 7: upload_file ---
    @tool
    async def upload_file(element_id: str, file_path: str) -> str:
        """Upload a file to a file input element.

        Args:
            element_id: The [node-XX] ID of the file input element.
            file_path: Path to the file to upload.
        """
        if element_id not in context.node_id_map:
            return (
                f"Element {element_id} not found. "
                "Call get_page_state() for fresh IDs."
            )

        element_info = context.node_id_map[element_id]
        role = element_info.get("role", "")
        name = element_info.get("name", "")

        try:
            locator = context.page.get_by_role(role, name=name, exact=False)
            await locator.set_input_files(file_path)
            return f"File '{file_path}' uploaded to {element_id}"
        except Exception as e:
            return f"File upload error: {str(e)}"

    # --- Edge-Case Tool 8: evaluate_javascript ---
    @tool
    async def evaluate_javascript(script: str) -> str:
        """Execute a READ-ONLY JavaScript snippet in the browser.

        Allowed: localStorage, sessionStorage, cookies, document.title,
                 element text/values, window.location, computed styles.
        Blocked: fetch, write operations, eval, setTimeout, DOM mutations.
        """
        return await evaluate_javascript_safe(context.page, script)

    # --- Edge-Case Tool 9: wait_for_condition ---
    @tool
    async def wait_for_condition(
        condition_type: str,
        value: Optional[str] = None,
    ) -> str:
        """Wait for a specific condition before proceeding.

        Args:
            condition_type: One of:
                "network_idle" — wait for all network requests to settle
                "element_visible" — wait for a CSS selector to be visible
                "dom_stable" — wait for SPA hydration (A11y tree stabilizes)
                "timeout" — wait for N milliseconds
            value: Required for element_visible (CSS selector) and timeout (ms).
        """
        try:
            if condition_type == "network_idle":
                await context.page.wait_for_load_state("networkidle")
                return "Network is idle."

            elif condition_type == "element_visible":
                if not value:
                    return "Error: 'value' (CSS selector) required for element_visible."
                await context.page.wait_for_selector(value, state="visible", timeout=10000)
                return f"Element '{value}' is now visible."

            elif condition_type == "dom_stable":
                # Poll aria snapshots twice with 500ms gap
                snap1 = await context.page.locator("body").aria_snapshot()
                await context.page.wait_for_timeout(500)
                snap2 = await context.page.locator("body").aria_snapshot()
                if snap1 == snap2:
                    return "DOM is stable."
                # Retry once more
                await context.page.wait_for_timeout(1000)
                snap3 = await context.page.locator("body").aria_snapshot()
                if snap2 == snap3:
                    return "DOM is stable (after second check)."
                return "DOM may still be changing. Proceeding anyway."

            elif condition_type == "timeout":
                if not value:
                    return "Error: 'value' (milliseconds) required for timeout."
                ms = int(value)
                await context.page.wait_for_timeout(ms)
                return f"Waited {ms}ms."

            else:
                return (
                    f"Unknown condition_type '{condition_type}'. "
                    "Use: network_idle, element_visible, dom_stable, timeout"
                )

        except Exception as e:
            return f"Wait error: {str(e)}"

    return [
        # Core tools
        navigate_to,
        get_page_state,
        interact_with_element,
        navigate_back,
        report_test_result,
        done_tool,
        # Edge-case tools
        upload_file,
        evaluate_javascript,
        wait_for_condition,
    ]
