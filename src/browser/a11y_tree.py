"""
Accessibility Tree extraction, pruning pipeline, and [node-XX] ID assignment.

Implements the 4-layer pruning strategy from Section 9.1:
  Layer 1: JavaScript-based interactive-element extraction (replaces
           page.accessibility.snapshot which was removed in Playwright 1.47+)
  Layer 2: Section-scoped extraction via root element
  Layer 3: Role-based filtering (keep only interactive elements)
  Layer 4: Hard cap on node count with priority sorting
"""

from typing import Optional

from playwright.async_api import Page, ElementHandle


# Interactive roles to keep during pruning
INTERACTIVE_ROLES = {
    "button", "link", "textbox", "checkbox", "radio",
    "combobox", "listbox", "menuitem", "tab", "searchbox",
    "slider", "spinbutton", "switch", "option", "heading",
}

# Priority order for truncation — higher priority = kept first
PRIORITY_ORDER = ["textbox", "button", "link", "combobox", "heading"]

# JavaScript that builds an accessibility-like tree from the DOM.
# Works in Playwright 1.47+ where page.accessibility was removed.
# Returns a dict matching {role, name, level?, checked?, value?, children?}.
_AXJS = """(rootElement) => {
    const INTERACTIVE = new Set(['button','link','textbox','checkbox','radio',
        'combobox','listbox','menuitem','tab','searchbox','slider','spinbutton',
        'switch','option','heading']);

    function getRole(el) {
        const r = el.getAttribute && el.getAttribute('role');
        if (r) return r.toLowerCase();
        const t = el.tagName ? el.tagName.toLowerCase() : '';
        const tp = (el.getAttribute && el.getAttribute('type') || '').toLowerCase();
        if (t === 'a' && el.href) return 'link';
        if (t === 'button') return 'button';
        if (t === 'input') {
            if (['button','submit','reset'].includes(tp)) return 'button';
            if (tp === 'checkbox') return 'checkbox';
            if (tp === 'radio') return 'radio';
            if (tp === 'hidden') return null;
            return 'textbox';
        }
        if (t === 'select') return 'combobox';
        if (t === 'textarea') return 'textbox';
        if (/^h[1-6]$/.test(t)) return 'heading';
        return t;
    }

    function getName(el) {
        const labId = el.getAttribute && el.getAttribute('aria-labelledby');
        const labEl = labId && document.getElementById(labId);
        return (
            (el.getAttribute && el.getAttribute('aria-label')) ||
            (labEl && labEl.textContent && labEl.textContent.trim()) ||
            (el.getAttribute && el.getAttribute('alt')) ||
            (el.getAttribute && el.getAttribute('placeholder')) ||
            (el.getAttribute && el.getAttribute('title')) ||
            (el.textContent && el.textContent.trim().slice(0, 80)) || ''
        );
    }

    function buildTree(el, depth) {
        if (!el || depth > 8) return null;
        const r = getRole(el);
        if (!r) return null;
        const n = getName(el);
        const hm = el.tagName && el.tagName.match(/^H([1-6])$/i);
        const kids = [];
        for (const c of (el.children || [])) {
            const k = buildTree(c, depth + 1);
            if (k) kids.push(k);
        }
        if (!INTERACTIVE.has(r) && !kids.length) return null;
        const node = { role: r, name: n };
        if (hm) node.level = parseInt(hm[1]);
        if (el.checked !== undefined && el.checked !== null) node.checked = el.checked;
        if (kids.length) node.children = kids;
        return node;
    }

    return buildTree(rootElement || document.body, 0);
}"""


def _count_nodes(tree: dict) -> int:
    """Count total nodes in an A11y tree recursively."""
    if not tree:
        return 0
    count = 1
    for child in tree.get("children", []):
        count += _count_nodes(child)
    return count


def filter_by_roles(snapshot: dict, roles: set) -> Optional[dict]:
    """
    Recursively filter an A11y tree to keep only nodes with matching roles.

    Preserves hierarchy: if a parent doesn't match but has matching descendants,
    the parent is kept as a structural container.
    """
    if not snapshot:
        return None

    role = snapshot.get("role", "").lower()
    children = snapshot.get("children", [])

    filtered_children = []
    for child in children:
        filtered_child = filter_by_roles(child, roles)
        if filtered_child is not None:
            filtered_children.append(filtered_child)

    if role in roles or filtered_children:
        result = {k: v for k, v in snapshot.items() if k != "children"}
        if filtered_children:
            result["children"] = filtered_children
        return result

    return None


def _collect_nodes_flat(tree: dict, result: list):
    """Flatten tree into a list of (node_dict, depth) for priority sorting."""
    if not tree:
        return
    result.append(tree)
    for child in tree.get("children", []):
        _collect_nodes_flat(child, result)


def prioritize_and_truncate(tree: dict, priority_order: list, max_nodes: int) -> dict:
    """
    Truncate tree to max_nodes by keeping higher-priority roles first.

    Collects all nodes, sorts by role priority, keeps the top max_nodes,
    and rebuilds the tree with only the kept nodes.
    """
    all_nodes = []
    _collect_nodes_flat(tree, all_nodes)

    if len(all_nodes) <= max_nodes:
        return tree

    def role_priority(node):
        role = node.get("role", "").lower()
        try:
            return priority_order.index(role)
        except ValueError:
            return len(priority_order)

    all_nodes.sort(key=role_priority)
    keep_set = set(id(n) for n in all_nodes[:max_nodes])

    def _rebuild(node):
        if id(node) not in keep_set:
            return None
        children = node.get("children", [])
        new_children = []
        for child in children:
            rebuilt = _rebuild(child)
            if rebuilt is not None:
                new_children.append(rebuilt)
        result = {k: v for k, v in node.items() if k != "children"}
        if new_children:
            result["children"] = new_children
        return result

    # Always keep the root
    keep_set.add(id(tree))
    return _rebuild(tree) or tree


def assign_node_ids(tree: dict) -> tuple[dict, dict]:
    """
    Walk the pruned tree and assign [node-XX] IDs to each interactive element.

    Returns:
        (annotated_tree, id_to_element_info) where id_to_element_info maps
        "[node-XX]" to {"role": ..., "name": ..., "selector_hint": ...}
        for use in building Playwright locators.

    Note: This is used ONLY by the Executor's get_page_state, NOT by the
    Planner's fetch_accessibility_tree.
    """
    counter = [0]
    id_map = {}

    def _walk(node):
        if not node:
            return node

        role = node.get("role", "").lower()
        annotated = dict(node)

        if role in INTERACTIVE_ROLES:
            counter[0] += 1
            node_id = f"[node-{counter[0]:02d}]"
            annotated["node_id"] = node_id
            id_map[node_id] = {
                "role": role,
                "name": node.get("name", ""),
                "value": node.get("value", ""),
                "description": node.get("description", ""),
            }

        children = node.get("children", [])
        if children:
            annotated["children"] = [_walk(c) for c in children]

        return annotated

    annotated_tree = _walk(tree)
    return annotated_tree, id_map


def tree_to_compact_string(tree: dict, indent: int = 0) -> str:
    """
    Serialize an A11y tree to a compact text format suitable for LLM consumption.

    Example output:
      [node-01] button "Add to Cart"
        [node-02] link "Product Details"
      heading "Featured Products" (level 2)
    """
    if not tree:
        return ""

    lines = []
    role = tree.get("role", "unknown")
    name = tree.get("name", "")
    value = tree.get("value", "")
    node_id = tree.get("node_id", "")

    prefix = "  " * indent
    parts = []

    if node_id:
        parts.append(node_id)

    parts.append(role)

    if name:
        parts.append(f'"{name}"')

    if value:
        parts.append(f'(value: "{value}")')

    # Add level for headings
    level = tree.get("level")
    if level:
        parts.append(f"(level {level})")

    # Add checked state for checkboxes/radios
    checked = tree.get("checked")
    if checked is not None:
        parts.append(f"(checked: {checked})")

    lines.append(prefix + " ".join(parts))

    for child in tree.get("children", []):
        child_str = tree_to_compact_string(child, indent + 1)
        if child_str:
            lines.append(child_str)

    return "\n".join(lines)


async def get_pruned_a11y_tree(
    page: Page,
    focus_section: Optional[str] = None,
    max_nodes: int = 150,
) -> Optional[dict]:
    """
    Multi-layer pruning pipeline for Accessibility Trees.

    Layer 1: JavaScript DOM traversal (page.accessibility was removed in Playwright 1.47+)
    Layer 2: Section-scoped extraction via CSS selector
    Layer 3: Role-based filtering (keep only interactive elements)
    Layer 4: Hard cap on node count with priority sorting
    """
    # Layer 1 & 2: Extract with optional CSS-scoped root
    root_handle = None
    if focus_section:
        root_handle = await page.query_selector(focus_section)

    if root_handle:
        snapshot = await page.evaluate(_AXJS, root_handle)
    else:
        snapshot = await page.evaluate(_AXJS)

    if not snapshot:
        return None

    # Layer 3: Filter to interactive roles
    filtered = filter_by_roles(snapshot, INTERACTIVE_ROLES)
    if not filtered:
        return None

    # Layer 4: Hard cap with priority sorting
    if _count_nodes(filtered) > max_nodes:
        filtered = prioritize_and_truncate(filtered, PRIORITY_ORDER, max_nodes)

    return filtered
