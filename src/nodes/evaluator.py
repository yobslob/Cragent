"""
Evaluator node — the strategic decision-maker after each testing round.

Reviews aggregated results and decides: CONTINUE_TESTING, TESTING_COMPLETE,
or RE_AUTHENTICATE.
"""

import json

from src.config import Config
from src.state import AgentState, EvaluatorDecisionModel
from src.prompts import EVALUATOR_SYSTEM_PROMPT
from src.compression.past_results import compress_past_results
from src.llm.factory import create_llm
from src.llm.retry import call_llm_with_retry


def _build_evaluator_message(state: AgentState) -> str:
    """Construct the user message for the Evaluator LLM."""
    past_results = state.get("past_results", [])
    current_depth = state.get("current_depth", 1)
    max_depth = state.get("max_depth", 5)
    target_url = state.get("target_url", "")
    instructions = state.get("testing_instructions", "")

    # Summary stats
    total = len(past_results)
    passed = sum(1 for r in past_results if r.get("status") == "PASS")
    failed = sum(1 for r in past_results if r.get("status") == "FAIL")
    blocked = sum(1 for r in past_results if r.get("status") == "BLOCKED_CAPTCHA")

    # Recent round results
    recent = [r for r in past_results if r.get("round_number") == current_depth]
    recent_summary = []
    for r in recent:
        recent_summary.append(
            f"  - {r.get('test_id', '?')} [{r.get('status', '?')}]: "
            f"{r.get('observations', '')[:200]}"
        )

    parts = [
        f"Target URL: {target_url}",
        f"Current Depth: {current_depth} / {max_depth}",
        f"Overall Stats: {total} tests — {passed} PASS, {failed} FAIL, {blocked} BLOCKED",
        f"\nUser Instructions: {instructions}" if instructions else "",
        f"\nThis Round's Results:",
        "\n".join(recent_summary) if recent_summary else "  No results for this round.",
    ]

    # Check for session expiry patterns
    login_patterns = ["/login", "/signin", "/auth", "/sso", "session expired", "redirected to login"]
    session_issues = [
        r for r in recent
        if any(p in r.get("observations", "").lower() for p in login_patterns)
    ]
    if session_issues:
        parts.append(
            f"\nWARNING: {len(session_issues)} test(s) reported possible session expiry."
        )

    return "\n".join(p for p in parts if p)


def _parse_evaluator_decision(llm_output: str) -> EvaluatorDecisionModel:
    """Parse the Evaluator's structured decision output."""
    text = llm_output.strip()

    # Try JSON parsing
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            data = json.loads(text[start:end + 1])
            return EvaluatorDecisionModel(**data)
        except (json.JSONDecodeError, Exception):
            pass

    # Fail-safe: default to TESTING_COMPLETE
    return EvaluatorDecisionModel(
        decision="TESTING_COMPLETE",
        next_url=None,
        focus_areas=[],
        reasoning="Could not parse evaluator output. Defaulting to TESTING_COMPLETE.",
    )


async def evaluator_node(state: AgentState, config: Config) -> dict:
    """
    Evaluator node: reviews test results and decides next action.

    Returns updated state with evaluator_decision, incremented depth,
    and potentially updated current_url.
    """
    current_depth = state.get("current_depth", 1)
    max_depth = state.get("max_depth", 5)
    past_results = state.get("past_results", [])

    # Force completion if depth limit reached
    if current_depth >= max_depth:
        decision = EvaluatorDecisionModel(
            decision="TESTING_COMPLETE",
            next_url=None,
            focus_areas=[],
            reasoning=f"Depth limit reached ({current_depth}/{max_depth}).",
        )
        return {
            "evaluator_decision": decision.to_dict(),
            "current_depth": current_depth + 1,
            "status": "evaluating",
        }

    # Build LLM prompt
    llm = create_llm(config.evaluator_model, config.temperature)
    user_message = _build_evaluator_message(state)

    try:
        from langchain_core.messages import SystemMessage, HumanMessage

        result = await call_llm_with_retry(
            llm,
            [
                SystemMessage(content=EVALUATOR_SYSTEM_PROMPT),
                HumanMessage(content=user_message),
            ],
            max_retries=config.llm_max_retries,
            base_delay=config.llm_base_delay_seconds,
        )

        decision = _parse_evaluator_decision(result.content)

    except Exception as e:
        # Fail-safe on LLM error
        decision = EvaluatorDecisionModel(
            decision="TESTING_COMPLETE",
            next_url=None,
            focus_areas=[],
            reasoning=f"Evaluator LLM error: {str(e)[:100]}. Defaulting to TESTING_COMPLETE.",
        )

    # Auto-throttle: if >50% of recent batch was BLOCKED_CAPTCHA
    recent = [r for r in past_results if r.get("round_number") == current_depth]
    if recent:
        blocked_count = sum(1 for r in recent if r.get("status") == "BLOCKED_CAPTCHA")
        if blocked_count > len(recent) / 2:
            current_concurrency = state.get("max_concurrency", 3)
            new_concurrency = max(1, current_concurrency - 1)
            return {
                "evaluator_decision": decision.to_dict(),
                "current_depth": current_depth + 1,
                "current_url": decision.next_url or state.get("current_url", ""),
                "max_concurrency": new_concurrency,
                "status": "evaluating",
            }

    return {
        "evaluator_decision": decision.to_dict(),
        "current_depth": current_depth + 1,
        "current_url": decision.next_url or state.get("current_url", ""),
        "status": "evaluating",
    }
