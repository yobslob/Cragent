"""
CLI frontend for Human-in-the-Loop interactions.

Implements streaming progress output and the blocking CLI pattern for
LangGraph interrupt()/Command(resume=...).
"""

from langgraph.types import Command


def _print_node_update(node_name: str, update: dict) -> None:
    """Print a human-readable progress line for a completed node."""
    if node_name == "planner":
        tasks = update.get("tasks_to_execute", [])
        print(f"  [Planner]       Generated {len(tasks)} test case(s)")

    elif node_name == "executor":
        results = update.get("past_results", [])
        for r in results:
            status = r.get("status", "?")
            test_id = r.get("test_id", "?")
            obs = r.get("observations", "")[:80]
            print(f"  [Executor]      {test_id} — {status}  {obs}")

    elif node_name == "serial_executor":
        results = update.get("past_results", [])
        for r in results:
            status = r.get("status", "?")
            test_id = r.get("test_id", "?")
            obs = r.get("observations", "")[:80]
            print(f"  [SerialExec]    {test_id} — {status}  {obs}")

    elif node_name == "evaluator":
        decision = update.get("evaluator_decision", {})
        d = decision.get("decision", "?")
        depth = update.get("current_depth", "?")
        reasoning = decision.get("reasoning", "")[:80]
        print(f"  [Evaluator]     {d}  (depth→{depth})  {reasoning}")

    elif node_name == "auth_bootstrap":
        path = update.get("shared_auth_state")
        if path:
            print(f"  [AuthBootstrap] Logged in — state saved to {path}")
        else:
            print(f"  [AuthBootstrap] No credentials / login skipped")

    elif node_name == "synthesizer":
        print(f"  [Synthesizer]   Report generated")

    else:
        print(f"  [{node_name}]")


async def run_with_cli_hitl(graph, inputs: dict, config: dict) -> dict:
    """
    Run the graph with streaming progress output and CLI-based HITL support.

    Streams node-level updates so the user sees progress in real time.
    When the graph emits an interrupt(), blocks on input() and resumes.

    Returns the final state dict after graph completion.
    """
    while True:
        interrupt_value = None

        async for chunk in graph.astream(inputs, config=config, stream_mode="updates"):
            for node_name, update in chunk.items():
                if node_name == "__interrupt__":
                    # update is a tuple of Interrupt objects
                    interrupts = update
                    if interrupts:
                        iv = interrupts[0]
                        interrupt_value = iv.value if hasattr(iv, "value") else str(iv)
                else:
                    _print_node_update(node_name, update)

        if interrupt_value is not None:
            print(f"\n{'='*60}")
            print(f"  Agent needs input: {interrupt_value}")
            print(f"{'='*60}")
            user_response = input("Your response: ").strip()
            inputs = Command(resume=user_response)
        else:
            # Stream finished — retrieve and return the final state values
            snapshot = await graph.aget_state(config)
            return snapshot.values if snapshot else {}


def print_startup_banner(target_url: str, config) -> None:
    """Print the startup banner."""
    print(f"""
{'='*57}
  Autonomous Testing Agent — Starting Run
  Target: {target_url}
  Max Depth: {config.max_depth} | Concurrency: {config.max_concurrency} | Model: {config.primary_model}
{'='*57}
""")


def print_completion_summary(state: dict) -> None:
    """Print the final completion summary."""
    past_results = state.get("past_results", [])
    total = len(past_results)
    passed = sum(1 for r in past_results if r.get("status") == "PASS")
    failed = sum(1 for r in past_results if r.get("status") == "FAIL")
    blocked = sum(1 for r in past_results if r.get("status") == "BLOCKED_CAPTCHA")
    health = round(passed / total * 100, 1) if total > 0 else 0

    print(f"""
{'='*57}
  Total: {total} tests | {passed} PASS | {failed} FAIL | {blocked} BLOCKED
  Health Score: {health}%
  Report saved to: {state.get('report_output_path', './test-report')}
{'='*57}
""")
