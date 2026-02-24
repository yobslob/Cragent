"""
Planner tools — the single tool available to the Planner LLM.

fetch_accessibility_tree: Spins up a short-lived headless Playwright context,
navigates to a URL, extracts the pruned A11y tree, and tears down the context.
Returns a compact string WITHOUT [node-XX] IDs.
"""

from langchain_core.tools import tool
from playwright.async_api import async_playwright

from src.config import Config
from src.browser.context_manager import create_browser_context, close_context
from src.browser.dom_fallback import get_a11y_tree_with_fallback
from src.browser.a11y_tree import tree_to_compact_string


def create_planner_tools(config: Config) -> list:
    """
    Factory that creates the Planner's tool list with config bound via closure.

    Returns a list containing the single fetch_accessibility_tree tool.
    """

    @tool
    async def fetch_accessibility_tree(url: str) -> str:
        """Fetch the accessibility tree for a URL.

        Returns a pruned hierarchical representation of interactive elements
        (buttons, links, inputs, headings, dropdowns) with roles and names.
        Use this to understand a page's structure before generating tests.

        Does NOT return [node-XX] IDs — those are assigned at runtime by the
        Executor's get_page_state tool.
        """
        browser = None
        context = None
        try:
            p = await async_playwright().start()
            browser, context, page = await create_browser_context(
                p, config, storage_state=None, proxy=None,
            )

            await page.goto(
                url,
                wait_until="networkidle",
                timeout=config.navigation_timeout_seconds * 1000,
            )

            tree = await get_a11y_tree_with_fallback(
                page,
                focus_section=None,
                max_nodes=config.a11y_tree_max_nodes,
            )

            if tree:
                return tree_to_compact_string(tree)
            else:
                # Last resort: extract visible text
                text = await page.evaluate(
                    "document.body.innerText.slice(0, 3000)"
                )
                return f"[No A11y tree available. Page text excerpt:]\n{text}"

        except Exception as e:
            return f"Error fetching accessibility tree for {url}: {str(e)}"
        finally:
            await close_context(browser, context)
            try:
                await p.stop()
            except Exception:
                pass

    return [fetch_accessibility_tree]
