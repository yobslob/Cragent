"""Tests for A11y tree processing."""

from src.browser.a11y_tree import (
    filter_by_roles,
    prioritize_and_truncate,
    assign_node_ids,
    tree_to_compact_string,
    INTERACTIVE_ROLES,
    PRIORITY_ORDER,
    _count_nodes,
)


SAMPLE_TREE = {
    "role": "WebArea",
    "name": "Example Page",
    "children": [
        {
            "role": "heading",
            "name": "Welcome",
            "level": 1,
        },
        {
            "role": "navigation",
            "name": "Main Nav",
            "children": [
                {"role": "link", "name": "Home"},
                {"role": "link", "name": "About"},
                {"role": "link", "name": "Contact"},
            ],
        },
        {
            "role": "searchbox",
            "name": "Search",
        },
        {
            "role": "button",
            "name": "Submit",
        },
        {
            "role": "img",  # Not interactive
            "name": "Logo",
        },
    ],
}


class TestFilterByRoles:
    def test_keeps_interactive_elements(self):
        result = filter_by_roles(SAMPLE_TREE, INTERACTIVE_ROLES)
        assert result is not None
        # Should keep heading, links, searchbox, button — not img
        flat = []
        _flatten(result, flat)
        roles = {n.get("role") for n in flat}
        assert "button" in roles
        assert "link" in roles
        assert "heading" in roles
        assert "searchbox" in roles
        assert "img" not in roles

    def test_empty_tree(self):
        assert filter_by_roles({}, INTERACTIVE_ROLES) is None
        assert filter_by_roles(None, INTERACTIVE_ROLES) is None

    def test_no_matching_roles(self):
        tree = {"role": "img", "name": "photo"}
        result = filter_by_roles(tree, INTERACTIVE_ROLES)
        assert result is None


class TestPrioritizeAndTruncate:
    def test_no_truncation_when_under_limit(self):
        result = prioritize_and_truncate(SAMPLE_TREE, PRIORITY_ORDER, 100)
        assert _count_nodes(result) == _count_nodes(SAMPLE_TREE)

    def test_truncation_keeps_priority_roles(self):
        result = prioritize_and_truncate(SAMPLE_TREE, PRIORITY_ORDER, 4)
        assert _count_nodes(result) <= 4


class TestAssignNodeIds:
    def test_assigns_sequential_ids(self):
        tree = {
            "role": "WebArea",
            "name": "Page",
            "children": [
                {"role": "button", "name": "Click Me"},
                {"role": "textbox", "name": "Input"},
                {"role": "link", "name": "Go"},
            ],
        }
        annotated, id_map = assign_node_ids(tree)
        assert "[node-01]" in id_map
        assert "[node-02]" in id_map
        assert "[node-03]" in id_map
        assert id_map["[node-01]"]["role"] == "button"
        assert id_map["[node-02]"]["role"] == "textbox"
        assert id_map["[node-03]"]["role"] == "link"

    def test_non_interactive_roles_get_no_id(self):
        tree = {
            "role": "WebArea",
            "name": "Page",
            "children": [
                {"role": "img", "name": "Logo"},
                {"role": "button", "name": "Click"},
            ],
        }
        annotated, id_map = assign_node_ids(tree)
        assert len(id_map) == 1  # Only button gets an ID


class TestTreeToCompactString:
    def test_basic_formatting(self):
        tree = {
            "role": "button",
            "name": "Click Me",
            "node_id": "[node-01]",
        }
        result = tree_to_compact_string(tree)
        assert "[node-01]" in result
        assert "button" in result
        assert '"Click Me"' in result

    def test_nested_tree(self):
        tree = {
            "role": "WebArea",
            "name": "Page",
            "children": [
                {
                    "role": "button",
                    "name": "Submit",
                    "node_id": "[node-01]",
                },
            ],
        }
        result = tree_to_compact_string(tree)
        assert "[node-01]" in result
        lines = result.strip().split("\n")
        assert len(lines) >= 2


def _flatten(tree, result):
    """Helper to flatten tree for testing."""
    if not tree:
        return
    result.append(tree)
    for child in tree.get("children", []):
        _flatten(child, result)
