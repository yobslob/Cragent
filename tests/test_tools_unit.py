"""Tests for executor tools with mocked Playwright Page."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.config import Config
from src.security.vault import CredentialVault
from src.tools.executor_tools import ExecutorContext, create_executor_tools


@pytest.fixture
def mock_page():
    """Create a mock Playwright Page."""
    page = AsyncMock()
    page.url = "https://example.com/login"
    page.goto = AsyncMock(return_value=None)
    page.go_back = AsyncMock(return_value=None)
    page.wait_for_timeout = AsyncMock(return_value=None)
    page.wait_for_load_state = AsyncMock(return_value=None)
    page.wait_for_selector = AsyncMock(return_value=None)
    page.evaluate = AsyncMock(return_value="some value")

    # get_by_role and locator return the same mock locator
    mock_locator = AsyncMock()
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.click = AsyncMock(return_value=None)
    mock_locator.fill = AsyncMock(return_value=None)
    mock_locator.select_option = AsyncMock(return_value=None)
    mock_locator.hover = AsyncMock(return_value=None)
    mock_locator.set_input_files = AsyncMock(return_value=None)
    mock_locator.aria_snapshot = AsyncMock(return_value="- button \"Submit\"\n- textbox \"Username\"")
    page.get_by_role = MagicMock(return_value=mock_locator)
    page.locator = MagicMock(return_value=mock_locator)

    return page


@pytest.fixture
def test_config():
    return Config(
        target_url="https://example.com",
        max_depth=2,
        max_concurrency=1,
        headless=True,
        primary_model="gpt-4o-mini",
        navigation_timeout_seconds=10,
        a11y_tree_max_nodes=50,
        dismiss_cookie_consent=False,
        inter_request_delay_ms=[50, 100],
    )


@pytest.fixture
def vault():
    return CredentialVault({
        "example.com": {"username": "admin", "password": "s3cret"},
    })


@pytest.fixture
def context(mock_page, vault, test_config):
    return ExecutorContext(page=mock_page, vault=vault, config=test_config)


@pytest.fixture
def tools(context):
    return create_executor_tools(context)


def _get_tool(tools, name):
    """Helper to find a tool by name."""
    for t in tools:
        if t.name == name:
            return t
    raise ValueError(f"Tool '{name}' not found. Available: {[t.name for t in tools]}")


class TestExecutorContext:
    def test_initial_state(self, context):
        assert context.node_id_map == {}
        assert context.test_result is None
        assert context.is_done is False
        assert len(context._visited_domains) == 0

    def test_get_domain(self, context):
        assert context._get_domain("https://example.com/page") == "example.com"
        assert context._get_domain("https://www.test.com") == "www.test.com"


class TestToolCreation:
    def test_creates_nine_tools(self, tools):
        assert len(tools) == 9

    def test_tool_names(self, tools):
        names = {t.name for t in tools}
        expected = {
            "navigate_to", "get_page_state", "interact_with_element",
            "navigate_back", "report_test_result", "done_tool",
            "upload_file", "evaluate_javascript", "wait_for_condition",
        }
        assert names == expected


class TestReportTestResult:
    @pytest.mark.asyncio
    async def test_records_pass(self, tools, context):
        tool = _get_tool(tools, "report_test_result")
        result = await tool.ainvoke({"status": "PASS", "observations": "Page loaded"})
        assert "PASS" in result
        assert context.test_result is not None
        assert context.test_result.status == "PASS"
        assert context.test_result.observations == "Page loaded"

    @pytest.mark.asyncio
    async def test_records_fail(self, tools, context):
        tool = _get_tool(tools, "report_test_result")
        result = await tool.ainvoke({"status": "FAIL", "observations": "Error found"})
        assert "FAIL" in result
        assert context.test_result.status == "FAIL"

    @pytest.mark.asyncio
    async def test_invalid_status_defaults_to_fail(self, tools, context):
        tool = _get_tool(tools, "report_test_result")
        await tool.ainvoke({"status": "INVALID", "observations": "test"})
        assert context.test_result.status == "FAIL"


class TestDoneTool:
    @pytest.mark.asyncio
    async def test_sets_is_done(self, tools, context):
        tool = _get_tool(tools, "done_tool")
        result = await tool.ainvoke({})
        assert context.is_done is True
        assert "complete" in result.lower()


class TestNavigateTo:
    @pytest.mark.asyncio
    async def test_navigates_successfully(self, tools, mock_page):
        tool = _get_tool(tools, "navigate_to")
        result = await tool.ainvoke({"url": "https://example.com"})
        mock_page.goto.assert_called_once()
        assert "Navigated" in result or "example.com" in result

    @pytest.mark.asyncio
    async def test_navigation_error_handled(self, tools, mock_page):
        mock_page.goto.side_effect = Exception("Timeout")
        tool = _get_tool(tools, "navigate_to")
        result = await tool.ainvoke({"url": "https://example.com"})
        assert "error" in result.lower()


class TestInteractWithElement:
    @pytest.mark.asyncio
    async def test_element_not_found(self, tools, context):
        tool = _get_tool(tools, "interact_with_element")
        result = await tool.ainvoke({
            "element_id": "[node-99]",
            "action_type": "click",
        })
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_click_action(self, tools, context, mock_page):
        context.node_id_map["[node-01]"] = {"role": "button", "name": "Submit"}
        tool = _get_tool(tools, "interact_with_element")
        result = await tool.ainvoke({
            "element_id": "[node-01]",
            "action_type": "click",
        })
        assert "Clicked" in result

    @pytest.mark.asyncio
    async def test_type_action(self, tools, context, mock_page):
        context.node_id_map["[node-02]"] = {"role": "textbox", "name": "Username"}
        tool = _get_tool(tools, "interact_with_element")
        result = await tool.ainvoke({
            "element_id": "[node-02]",
            "action_type": "type",
            "input_value": "testuser",
        })
        assert "Typed" in result

    @pytest.mark.asyncio
    async def test_vault_substitution(self, tools, context, mock_page):
        context.node_id_map["[node-02]"] = {"role": "textbox", "name": "Password"}
        tool = _get_tool(tools, "interact_with_element")
        result = await tool.ainvoke({
            "element_id": "[node-02]",
            "action_type": "type",
            "input_value": "{{vault:password}}",
        })
        # Should succeed and show vault token (not actual password) in result
        assert "Typed" in result
        assert "{{vault:password}}" in result
        # The actual value "s3cret" should have been passed to fill()
        locator = mock_page.get_by_role.return_value
        locator.fill.assert_called_once_with("s3cret", timeout=5000)

    @pytest.mark.asyncio
    async def test_unknown_action_type(self, tools, context):
        context.node_id_map["[node-01]"] = {"role": "button", "name": "Submit"}
        tool = _get_tool(tools, "interact_with_element")
        result = await tool.ainvoke({
            "element_id": "[node-01]",
            "action_type": "drag",
        })
        assert "Unknown action_type" in result


class TestGetPageState:
    @pytest.mark.asyncio
    async def test_returns_tree_string(self, tools, context):
        tool = _get_tool(tools, "get_page_state")
        with patch("src.tools.executor_tools.get_a11y_tree_with_fallback", new_callable=AsyncMock) as mock_tree:
            mock_tree.return_value = {
                "role": "WebArea",
                "name": "Page",
                "children": [
                    {"role": "button", "name": "Click"},
                ],
            }
            result = await tool.ainvoke({})
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_updates_node_id_map(self, tools, context):
        tool = _get_tool(tools, "get_page_state")
        with patch("src.tools.executor_tools.get_a11y_tree_with_fallback", new_callable=AsyncMock) as mock_tree:
            mock_tree.return_value = {
                "role": "WebArea",
                "name": "Page",
                "children": [
                    {"role": "button", "name": "Submit"},
                    {"role": "textbox", "name": "Search"},
                ],
            }
            await tool.ainvoke({})
            assert len(context.node_id_map) > 0

    @pytest.mark.asyncio
    async def test_clears_old_ids(self, tools, context):
        context.node_id_map["[node-old]"] = {"role": "button", "name": "Old"}
        tool = _get_tool(tools, "get_page_state")
        with patch("src.tools.executor_tools.get_a11y_tree_with_fallback", new_callable=AsyncMock) as mock_tree:
            mock_tree.return_value = {
                "role": "WebArea",
                "name": "Page",
                "children": [
                    {"role": "button", "name": "New"},
                ],
            }
            await tool.ainvoke({})
            assert "[node-old]" not in context.node_id_map


class TestNavigateBack:
    @pytest.mark.asyncio
    async def test_goes_back(self, tools, mock_page):
        tool = _get_tool(tools, "navigate_back")
        result = await tool.ainvoke({})
        mock_page.go_back.assert_called_once()
        assert "Navigated back" in result


class TestEvaluateJavascript:
    @pytest.mark.asyncio
    async def test_blocks_dangerous_js(self, tools):
        tool = _get_tool(tools, "evaluate_javascript")
        result = await tool.ainvoke({"script": "fetch('https://evil.com')"})
        assert "BLOCKED" in result

    @pytest.mark.asyncio
    async def test_allows_safe_js(self, tools, mock_page):
        tool = _get_tool(tools, "evaluate_javascript")
        with patch("src.tools.executor_tools.evaluate_javascript_safe", new_callable=AsyncMock) as mock_eval:
            mock_eval.return_value = "Example Title"
            result = await tool.ainvoke({"script": "document.title"})
            assert result == "Example Title"


class TestWaitForCondition:
    @pytest.mark.asyncio
    async def test_network_idle(self, tools, mock_page):
        tool = _get_tool(tools, "wait_for_condition")
        result = await tool.ainvoke({"condition_type": "network_idle"})
        mock_page.wait_for_load_state.assert_called_once_with("networkidle")
        assert "idle" in result.lower()

    @pytest.mark.asyncio
    async def test_timeout(self, tools, mock_page):
        tool = _get_tool(tools, "wait_for_condition")
        result = await tool.ainvoke({"condition_type": "timeout", "value": "500"})
        mock_page.wait_for_timeout.assert_called()
        assert "500" in result

    @pytest.mark.asyncio
    async def test_element_visible(self, tools, mock_page):
        tool = _get_tool(tools, "wait_for_condition")
        result = await tool.ainvoke({
            "condition_type": "element_visible",
            "value": "#submit-btn",
        })
        mock_page.wait_for_selector.assert_called_once()
        assert "visible" in result.lower()

    @pytest.mark.asyncio
    async def test_unknown_condition(self, tools):
        tool = _get_tool(tools, "wait_for_condition")
        result = await tool.ainvoke({"condition_type": "something_invalid"})
        assert "Unknown" in result
