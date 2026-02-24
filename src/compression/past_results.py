"""
Adaptive past-results compression with strict token budget enforcement.

Implements the 4-priority compression pipeline from Section 9.2:
  Priority 1: Recent round (verbatim)
  Priority 2: All FAIL results from older rounds (always preserved)
  Priority 3: Mid-term round summaries (deterministic one-liners)
  Priority 4: Historical global summary
"""

import tiktoken

from src.state import TestResult


def _token_count(text: str, model: str = "gpt-4o") -> int:
    """Count tokens in a text string."""
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def format_results_verbatim(results: list[TestResult]) -> str:
    """Format test results with full detail."""
    if not results:
        return "No results."
    lines = []
    for r in results:
        lines.append(
            f"- {r['test_id']} [{r['status']}] on {r.get('tested_surface', 'unknown')}: "
            f"{r.get('observations', 'No observations')}"
        )
        if r.get("discovered_elements"):
            lines.append(f"  Discovered: {', '.join(r['discovered_elements'][:5])}")
        if r.get("retry_count", 0) > 0:
            lines.append(f"  Retries: {r['retry_count']}")
    return "\n".join(lines)


def format_failures_compact(failures: list[TestResult]) -> str:
    """Compact format preserving test_id, surface, and key observations."""
    if not failures:
        return "None"
    return "\n".join(
        f"- {r['test_id']} on {r.get('tested_surface', 'unknown')}: "
        f"{r.get('observations', '')[:150]}"
        for r in failures
    )


def _summarize_single_round(round_number: int, results: list[TestResult]) -> str:
    """Generate a one-line summary for a single round."""
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    blocked = sum(1 for r in results if r["status"] == "BLOCKED_CAPTCHA")
    surfaces = set(r.get("tested_surface", "unknown") for r in results)

    parts = [f"Round {round_number}: {total} tests"]
    status_parts = []
    if passed:
        status_parts.append(f"{passed} PASS")
    if failed:
        status_parts.append(f"{failed} FAIL")
    if blocked:
        status_parts.append(f"{blocked} BLOCKED")
    parts.append(f"({', '.join(status_parts)})")

    if surfaces:
        parts.append(f"Surfaces: {', '.join(list(surfaces)[:3])}")

    return " | ".join(parts)


def summarize_rounds(results: list[TestResult]) -> list[str]:
    """Generate per-round one-line summaries."""
    rounds: dict[int, list[TestResult]] = {}
    for r in results:
        rn = r.get("round_number", 0)
        rounds.setdefault(rn, []).append(r)

    summaries = []
    for round_num in sorted(rounds.keys()):
        summaries.append(_summarize_single_round(round_num, rounds[round_num]))
    return summaries


def summarize_global(results: list[TestResult]) -> str:
    """Generate a single paragraph summary of old results."""
    if not results:
        return "No historical results."
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    blocked = sum(1 for r in results if r["status"] == "BLOCKED_CAPTCHA")
    surfaces = set(r.get("tested_surface", "unknown") for r in results)
    rounds_covered = set(r.get("round_number", 0) for r in results)

    return (
        f"Across {len(rounds_covered)} earlier round(s), {total} tests were executed: "
        f"{passed} passed, {failed} failed, {blocked} blocked. "
        f"Surfaces covered: {', '.join(list(surfaces)[:5])}."
    )


def compress_past_results(
    past_results: list[TestResult],
    current_depth: int,
    token_budget: int = 2000,
    model: str = "gpt-4o",
) -> str:
    """
    Adaptive compression with strict token budget enforcement.

    Priority (highest to lowest):
    1. Recent round (current_depth - 1): full verbatim results
    2. Failed tests from ANY round: always preserved (key signal for replanning)
    3. Mid-term rounds: one-line-per-round deterministic summaries
    4. Old rounds: single global summary paragraph

    If budget is exceeded, evict from lowest priority first.
    """
    if not past_results:
        return "No previous test results."

    # Priority 1: Recent round — full detail
    recent = [r for r in past_results if r.get("round_number") == current_depth - 1]
    recent_text = "## Recent Round (Full Detail)\n" + format_results_verbatim(recent)

    # Priority 2: All FAIL results from older rounds — always kept
    old_failures = [
        r for r in past_results
        if r.get("round_number", 0) < current_depth - 1
        and r["status"] == "FAIL"
    ]
    failures_text = "## Previous Failures\n" + format_failures_compact(old_failures)

    # Priority 3: Mid-term summaries (rounds N-4 through N-2)
    mid_rounds = [
        r for r in past_results
        if current_depth - 4 <= r.get("round_number", 0) < current_depth - 1
    ]
    mid_text = "## Mid-Term Summaries\n" + "\n".join(summarize_rounds(mid_rounds))

    # Priority 4: Global summary (everything older than N-4)
    old_rounds = [
        r for r in past_results
        if r.get("round_number", 0) < current_depth - 4
    ]
    global_text = "## Historical Summary\n" + summarize_global(old_rounds)

    # Assemble with budget enforcement — evict from lowest priority
    components = [
        (1, recent_text),
        (2, failures_text),
        (3, mid_text),
        (4, global_text),
    ]

    assembled = "\n\n".join(text for _, text in components)
    while _token_count(assembled, model) > token_budget and len(components) > 1:
        components.pop()
        assembled = "\n\n".join(text for _, text in components)

    # If even recent round alone exceeds budget, compress PASS results to one-liners
    if _token_count(assembled, model) > token_budget and recent:
        compressed_recent_lines = []
        for r in recent:
            if r["status"] == "PASS":
                compressed_recent_lines.append(
                    f"- {r['test_id']} [PASS] on {r.get('tested_surface', 'unknown')}"
                )
            else:
                compressed_recent_lines.append(
                    f"- {r['test_id']} [{r['status']}] on {r.get('tested_surface', 'unknown')}: "
                    f"{r.get('observations', '')[:150]}"
                )
        assembled = "## Recent Round\n" + "\n".join(compressed_recent_lines)

    return assembled
