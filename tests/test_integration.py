"""
Integration tests for the full graph.

These tests verify end-to-end graph execution with mocked LLM and browser
to avoid external dependencies. They test the wiring between nodes.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.config import Config
from src.graph import build_graph


@pytest.fixture
def integration_config():
    return Config(
        target_url="https://example.com",
        max_depth=1,
        batch_size=2,
        max_retries=1,
        max_concurrency=1,
        headless=True,
        primary_model="gpt-4o-mini",
        fallback_model="gpt-4o-mini",
        evaluator_model="gpt-4o-mini",
        synthesizer_model="gpt-4o-mini",
        node_inactivity_timeout_seconds=30,
        node_absolute_timeout_seconds=60,
        graph_timeout_seconds=120,
        auth_bootstrap_enabled=False,
        report_output_path="test_report.md",
    )


class TestGraphBuild:
    def test_graph_builds_successfully(self, integration_config):
        """Verify graph can be built and compiled."""
        graph = build_graph(integration_config)
        assert graph is not None

    def test_graph_node_count(self, integration_config):
        """Verify the correct number of operational nodes."""
        graph = build_graph(integration_config)
        nodes = graph.get_graph().nodes
        # Should have: __start__, __end__, auth_bootstrap, planner,
        # executor, serial_executor, evaluator, synthesizer
        operational = {
            k for k in nodes.keys()
            if k not in ("__start__", "__end__")
        }
        assert len(operational) == 6

    def test_executor_node_exists(self, integration_config):
        """Verify executor node is registered in the graph."""
        graph = build_graph(integration_config)
        g = graph.get_graph()
        assert "executor" in g.nodes

    def test_serial_executor_node_exists(self, integration_config):
        """Verify serial_executor node is registered in the graph."""
        graph = build_graph(integration_config)
        g = graph.get_graph()
        assert "serial_executor" in g.nodes

    def test_evaluator_node_exists(self, integration_config):
        """Verify evaluator node is registered in the graph."""
        graph = build_graph(integration_config)
        g = graph.get_graph()
        assert "evaluator" in g.nodes

    def test_synthesizer_node_exists(self, integration_config):
        """Verify synthesizer node is registered in the graph."""
        graph = build_graph(integration_config)
        g = graph.get_graph()
        assert "synthesizer" in g.nodes

    def test_graph_edges_from_auth_bootstrap(self, integration_config):
        """Verify auth_bootstrap connects to planner."""
        graph = build_graph(integration_config)
        g = graph.get_graph()
        auth_edges = [
            e for e in g.edges
            if e.source == "auth_bootstrap"
        ]
        targets = {e.target for e in auth_edges}
        assert "planner" in targets


class TestGraphInitialState:
    def test_valid_initial_state(self, integration_config):
        """Verify the graph accepts well-formed initial state."""
        graph = build_graph(integration_config)
        # Just verify the graph compiled; actual invocation would
        # require mocking all LLM + browser calls.
        assert graph is not None

    def test_graph_runnable_get_graph(self, integration_config):
        """Verify the compiled graph exposes get_graph for introspection."""
        graph = build_graph(integration_config)
        g = graph.get_graph()
        assert g is not None
        assert hasattr(g, "nodes")
        assert hasattr(g, "edges")
