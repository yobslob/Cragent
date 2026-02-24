"""Smoke tests for graph compilation and topology."""

import pytest

from src.config import Config
from src.graph import build_graph, _route_entry, _planner_to_executors, _route_after_eval


@pytest.fixture
def config():
    return Config(
        target_url="https://example.com",
        max_depth=2,
        max_concurrency=1,
        headless=True,
        primary_model="gpt-4o-mini",
        fallback_model="gpt-4o-mini",
        evaluator_model="gpt-4o-mini",
        synthesizer_model="gpt-4o-mini",
    )


class TestGraphCompilation:
    def test_graph_compiles(self, config):
        """Graph should compile without error."""
        graph = build_graph(config)
        assert graph is not None

    def test_graph_has_expected_nodes(self, config):
        """Graph should contain all defined nodes."""
        graph = build_graph(config)
        node_names = set(graph.get_graph().nodes.keys())
        expected = {
            "__start__", "__end__",
            "auth_bootstrap", "planner", "executor",
            "serial_executor", "evaluator", "synthesizer",
        }
        assert expected.issubset(node_names), (
            f"Missing nodes: {expected - node_names}"
        )


class TestRouteEntry:
    def test_routes_to_planner_without_credentials(self, config):
        state = {"credentials": {}}
        assert _route_entry(state, config) == "planner"

    def test_routes_to_planner_when_no_credentials_key(self, config):
        state = {}
        assert _route_entry(state, config) == "planner"

    def test_routes_to_auth_bootstrap_with_credentials(self, config):
        state = {"credentials": {"example.com": {"username": "admin", "password": "pass"}}}
        # auth_bootstrap_enabled defaults to True
        assert _route_entry(state, config) == "auth_bootstrap"


class TestPlannerToExecutors:
    def test_independent_tests_to_executor(self):
        state = {
            "tasks_to_execute": [
                {"test_id": "TC-001", "conflict_group": None, "description": "Test 1"},
                {"test_id": "TC-002", "conflict_group": None, "description": "Test 2"},
            ],
            "credentials": {},
            "shared_auth_state": None,
            "max_retries": 3,
            "current_depth": 1,
        }
        sends = _planner_to_executors(state)
        assert len(sends) == 2
        for send in sends:
            assert send.node == "executor"

    def test_conflict_groups_to_serial_executor(self):
        state = {
            "tasks_to_execute": [
                {"test_id": "TC-001", "conflict_group": "cart", "description": "Add to cart"},
                {"test_id": "TC-002", "conflict_group": "cart", "description": "Checkout"},
            ],
            "credentials": {},
            "shared_auth_state": None,
            "max_retries": 3,
            "current_depth": 1,
        }
        sends = _planner_to_executors(state)
        assert len(sends) == 1
        assert sends[0].node == "serial_executor"

    def test_mixed_independent_and_grouped(self):
        state = {
            "tasks_to_execute": [
                {"test_id": "TC-001", "conflict_group": None, "description": "Independent"},
                {"test_id": "TC-002", "conflict_group": "cart", "description": "Add"},
                {"test_id": "TC-003", "conflict_group": "cart", "description": "Checkout"},
            ],
            "credentials": {},
            "shared_auth_state": None,
            "max_retries": 3,
            "current_depth": 1,
        }
        sends = _planner_to_executors(state)
        assert len(sends) == 2  # 1 independent + 1 group
        nodes = {s.node for s in sends}
        assert "executor" in nodes
        assert "serial_executor" in nodes

    def test_empty_tasks_creates_fallback(self):
        state = {
            "tasks_to_execute": [],
            "current_url": "https://example.com",
            "credentials": {},
            "shared_auth_state": None,
            "max_retries": 3,
            "current_depth": 1,
        }
        sends = _planner_to_executors(state)
        assert len(sends) == 1
        assert sends[0].node == "executor"
        assert sends[0].arg["test_case"]["test_id"] == "TC-NOOP"


class TestRouteAfterEval:
    def test_testing_complete_routes_to_synthesizer(self):
        state = {
            "evaluator_decision": {
                "decision": "TESTING_COMPLETE",
                "next_url": None,
                "focus_areas": [],
                "reasoning": "Done",
            }
        }
        assert _route_after_eval(state) == "synthesizer"

    def test_continue_testing_routes_to_planner(self):
        state = {
            "evaluator_decision": {
                "decision": "CONTINUE_TESTING",
                "next_url": "https://example.com/cart",
                "focus_areas": ["checkout"],
                "reasoning": "More to test",
            }
        }
        assert _route_after_eval(state) == "planner"

    def test_re_authenticate_routes_to_auth_bootstrap(self):
        state = {
            "evaluator_decision": {
                "decision": "RE_AUTHENTICATE",
                "next_url": None,
                "focus_areas": [],
                "reasoning": "Session expired",
            }
        }
        assert _route_after_eval(state) == "auth_bootstrap"

    def test_missing_decision_defaults_to_synthesizer(self):
        state = {"evaluator_decision": {}}
        assert _route_after_eval(state) == "synthesizer"

    def test_missing_evaluator_decision_defaults_to_synthesizer(self):
        state = {}
        assert _route_after_eval(state) == "synthesizer"
