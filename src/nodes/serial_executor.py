"""
Serial Executor node — runs conflict-group tests sequentially.

When multiple tests share a conflict_group (e.g., both modify the same
server-side resource), they are dispatched to this node instead of
parallel individual executors to prevent race conditions.
"""

from src.config import Config
from src.state import TestResult
from src.nodes.executor import run_single_test


async def serial_executor_node(state: dict, config: Config) -> dict:
    """
    Serial executor: receives a list of test cases (same conflict group)
    and executes them sequentially.

    Returns {"past_results": [all_results]} for the dedup reducer.
    """
    test_cases = state.get("test_cases", [])
    credentials = state.get("credentials", {})
    shared_auth_state = state.get("shared_auth_state")
    max_retries = state.get("max_retries", 3)
    current_depth = state.get("current_depth", 1)

    all_results = []

    for i, test_case in enumerate(test_cases):
        result = await run_single_test(
            test_case=test_case,
            credentials=credentials,
            shared_auth_state=shared_auth_state,
            max_retries=max_retries,
            current_depth=current_depth,
            config=config,
            executor_index=i,
        )
        all_results.append(dict(result))

    return {"past_results": all_results}
