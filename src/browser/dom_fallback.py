"""
Shadow DOM fallback traversal for pages where page.accessibility.snapshot()
returns empty or minimal trees (common with heavy Web Components).
"""

from typing import Optional

from playwright.async_api import Page

from src.browser.a11y_tree import get_pruned_a11y_tree


# JavaScript that pierces shadow roots and extracts interactive elements
_SHADOW_DOM_TRAVERSAL_JS = """
() => {
    function traverse(root, results = []) {
        const elements = root.querySelectorAll(
            'button, a, input, select, textarea, [role="button"], [role="link"], ' +
            '[role="textbox"], [role="checkbox"], [role="radio"], [role="combobox"], ' +
            '[role="searchbox"], [role="tab"], [role="menuitem"], [role="switch"]'
        );
        elements.forEach(el => {
            results.push({
                role: el.getAttribute('role') || el.tagName.toLowerCase(),
                name: el.getAttribute('aria-label') || el.textContent?.trim()?.slice(0, 50) || '',
                tag: el.tagName,
                type: el.getAttribute('type') || '',
                placeholder: el.getAttribute('placeholder') || '',
                href: el.getAttribute('href') || '',
            });
        });
        // Pierce shadow roots
        root.querySelectorAll('*').forEach(el => {
            if (el.shadowRoot) traverse(el.shadowRoot, results);
        });
        return results;
    }
    return traverse(document);
}
"""

# Minimum node count to consider the A11y tree as "valid"
_MIN_TREE_NODE_COUNT = 3


async def shadow_dom_fallback(page: Page) -> list[dict]:
    """
    Traverse shadow DOMs and extract interactive elements.

    Used when page.accessibility.snapshot() returns an empty or minimal tree.
    """
    try:
        elements = await page.evaluate(_SHADOW_DOM_TRAVERSAL_JS)
        return elements or []
    except Exception:
        return []


def _count_tree_nodes(tree: Optional[dict]) -> int:
    """Count nodes in an A11y tree."""
    if not tree:
        return 0
    count = 1
    for child in tree.get("children", []):
        count += _count_tree_nodes(child)
    return count


def _shadow_results_to_tree(elements: list[dict]) -> dict:
    """Convert flat shadow DOM results into a tree-like structure."""
    children = []
    for el in elements:
        role = el.get("role", "unknown")
        # Normalize tag names to roles
        tag_role_map = {
            "a": "link",
            "button": "button",
            "input": "textbox",
            "select": "combobox",
            "textarea": "textbox",
        }
        if role in tag_role_map.values():
            pass  # Already a proper role
        elif role.lower() in tag_role_map:
            role = tag_role_map[role.lower()]

        name = el.get("name", "") or el.get("placeholder", "")
        node = {"role": role, "name": name}
        if el.get("href"):
            node["value"] = el["href"]
        children.append(node)

    return {
        "role": "WebArea",
        "name": "Shadow DOM Fallback",
        "children": children,
    }


async def get_a11y_tree_with_fallback(
    page: Page,
    focus_section: Optional[str] = None,
    max_nodes: int = 150,
) -> Optional[dict]:
    """
    Try primary A11y tree extraction; fall back to Shadow DOM traversal if needed.
    """
    tree = await get_pruned_a11y_tree(page, focus_section, max_nodes)

    if tree and _count_tree_nodes(tree) >= _MIN_TREE_NODE_COUNT:
        return tree

    # Fallback: Shadow DOM traversal
    elements = await shadow_dom_fallback(page)
    if elements:
        return _shadow_results_to_tree(elements)

    # Last resort: return whatever we got from the primary extraction
    return tree
