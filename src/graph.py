"""
LangGraph state machine construction and wiring.

Defines the complete graph topology:
  __start__ -> auth_bootstrap (if credentials) -> planner
  planner -> [Send() fan-out] -> executor / serial_executor
  executor -> evaluator
  evaluator -> planner (CONTINUE) / synthesizer (DONE) / auth_bootstrap (RE_AUTH)
  synthesizer -> END
"""

from langgraph.graph import StateGraph, END
from langgraph.types import Send
from langgraph.checkpoint.memory import MemorySaver

from src.config import Config
from src.state import AgentState
from src.nodes.planner import planner_node
from src.nodes.executor import executor_node
from src.nodes.serial_executor import serial_executor_node
from src.nodes.evaluator import evaluator_node
from src.nodes.synthesizer import synthesizer_node
from src.nodes.auth_bootstrap import auth_bootstrap_node


def _route_entry(state: AgentState, config: Config) -> str:
    """Route from __start__: auth_bootstrap if credentials, else planner."""
    if state.get("credentials") and config.auth_bootstrap_enabled:
        return "auth_bootstrap"
    return "planner"

def _planner_to_executors(state: AgentState) -> list[Send]:
    """
    Fan-out: dispatch test cases to executor nodes.

    Independent tests (no conflict_group) get individual Send() to "executor".
    Tests sharing a conflict_group get a single Send() to "serial_executor".
    """
    tasks = state.get("tasks_to_execute", [])

    independent = [t for t in tasks if not t.get("conflict_group")]
    grouped: dict[str, list] = {}
    for t in tasks:
        cg = t.get("conflict_group")
        if cg:
            grouped.setdefault(cg, []).append(t)

    base_payload = {
        "credentials": state.get("credentials", {}),
        "shared_auth_state": state.get("shared_auth_state"),
        "max_retries": state.get("max_retries", 3),
        "current_depth": state.get("current_depth", 1),
    }

    sends = []

    # Independent tests: one Send each (executed in parallel)
    for test_case in independent:
        sends.append(
            Send("executor", {"test_case": test_case, **base_payload})
        )

    # Conflict groups: one Send per group to serial executor
    for group_name, group_tests in grouped.items():
        sends.append(
            Send("serial_executor", {"test_cases": group_tests, **base_payload})
        )

    # Guard: if no sends, create a fallback
    if not sends:
        sends.append(
            Send("executor", {
                "test_case": {
                    "test_id": "TC-NOOP",
                    "description": "No test cases generated",
                    "category": "navigation",
                    "priority": 1,
                    "target_url": state.get("current_url", ""),
                    "steps": ["Navigate to target URL", "Verify page loads"],
                    "expected_outcome": "Page loads",
                    "failure_criteria": "Page fails to load",
                    "is_destructive": False,
                    "requires_auth": False,
                    "setup_steps": [],
                    "conflict_group": None,
                },
                **base_payload,
            })
        )

    return sends


def _route_after_eval(state: AgentState) -> str:
    """Route based on Evaluator's decision."""
    decision = state.get("evaluator_decision", {})
    d = decision.get("decision", "TESTING_COMPLETE")

    if d == "TESTING_COMPLETE":
        return "synthesizer"
    if d == "RE_AUTHENTICATE":
        return "auth_bootstrap"
    return "planner"  # CONTINUE_TESTING


def build_graph(config: Config):
    """
    Build and compile the LangGraph state machine.

    Returns a compiled graph ready for invocation.
    """
    # Wrap each node in a plain async closure so LangGraph only sees (state),
    # avoiding the RunnableConfig type-mismatch warning from partial().
    async def _auth_bootstrap(state): return await auth_bootstrap_node(state, config)
    async def _planner(state):        return await planner_node(state, config)
    async def _executor(state):       return await executor_node(state, config)
    async def _serial_executor(state): return await serial_executor_node(state, config)
    async def _evaluator(state):      return await evaluator_node(state, config)
    async def _synthesizer(state):    return await synthesizer_node(state, config)

    def _entry_route(state): return _route_entry(state, config)

    graph = StateGraph(AgentState)

    graph.add_node("auth_bootstrap", _auth_bootstrap)
    graph.add_node("planner",        _planner)
    graph.add_node("executor",       _executor)
    graph.add_node("serial_executor", _serial_executor)
    graph.add_node("evaluator",      _evaluator)
    graph.add_node("synthesizer",    _synthesizer)

    # Entry point routing
    graph.add_conditional_edges(
        "__start__",
        _entry_route,
        {
            "auth_bootstrap": "auth_bootstrap",
            "planner": "planner",
        },
    )

    # Auth bootstrap -> planner
    graph.add_edge("auth_bootstrap", "planner")

    # Planner -> fan-out to executors
    graph.add_conditional_edges("planner", _planner_to_executors)

    # Executors -> evaluator
    graph.add_edge("executor", "evaluator")
    graph.add_edge("serial_executor", "evaluator")

    # Evaluator -> routing
    graph.add_conditional_edges(
        "evaluator",
        _route_after_eval,
        {
            "planner": "planner",
            "synthesizer": "synthesizer",
            "auth_bootstrap": "auth_bootstrap",
        },
    )

    # Synthesizer -> END
    graph.add_edge("synthesizer", END)

    # Compile with checkpointer
    checkpointer = MemorySaver()
    compiled = graph.compile(checkpointer=checkpointer)

    return compiled
