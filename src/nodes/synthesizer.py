"""
Synthesizer node — generates the final comprehensive test report.

Two-phase approach:
  Phase 1: Deterministic template rendering (Python, no LLM)
  Phase 2: LLM-generated narrative summary
"""

import os
from datetime import datetime, timezone

from langchain_core.messages import SystemMessage, HumanMessage

from src.config import Config
from src.state import AgentState, TestResult
from src.prompts import SYNTHESIZER_LLM_PROMPT
from src.llm.factory import create_llm
from src.llm.retry import call_llm_with_retry


def generate_report_data(state: AgentState) -> dict:
    """
    Phase 1: Deterministic report data generation.

    Pure Python computation — no LLM calls. Produces structured data
    for the report template.
    """
    results = state.get("past_results", [])
    total = len(results)
    passed = sum(1 for r in results if r.get("status") == "PASS")
    failed = sum(1 for r in results if r.get("status") == "FAIL")
    blocked = sum(1 for r in results if r.get("status") == "BLOCKED_CAPTCHA")

    # Per-round breakdown
    rounds: dict[int, dict] = {}
    for r in results:
        rn = r.get("round_number", 0)
        if rn not in rounds:
            rounds[rn] = {"passed": 0, "failed": 0, "blocked": 0, "surfaces": set(), "total": 0}
        rounds[rn]["total"] += 1
        status = r.get("status", "FAIL")
        if status == "PASS":
            rounds[rn]["passed"] += 1
        elif status == "BLOCKED_CAPTCHA":
            rounds[rn]["blocked"] += 1
        else:
            rounds[rn]["failed"] += 1
        rounds[rn]["surfaces"].add(r.get("tested_surface", "unknown"))

    # Critical issues (FAIL results with observations)
    critical_issues = [
        {
            "test_id": r.get("test_id", "?"),
            "surface": r.get("tested_surface", "unknown"),
            "observations": r.get("observations", ""),
        }
        for r in results
        if r.get("status") == "FAIL"
    ]

    # Surfaces tested
    surfaces_tested = list({r.get("tested_surface", "unknown") for r in results})

    # Self-healing log (tests with retries > 0)
    retry_log = [
        {
            "test_id": r.get("test_id", "?"),
            "retries": r.get("retry_count", 0),
            "status": r.get("status", "?"),
        }
        for r in results
        if r.get("retry_count", 0) > 0
    ]

    return {
        "health_score": round(passed / total * 100, 1) if total > 0 else 0,
        "total": total,
        "passed": passed,
        "failed": failed,
        "blocked": blocked,
        "rounds": rounds,
        "critical_issues": critical_issues,
        "surfaces_tested": surfaces_tested,
        "retry_log": retry_log,
    }


def _render_markdown_report(
    target_url: str,
    current_depth: int,
    max_depth: int,
    report_data: dict,
    llm_narrative: str,
) -> str:
    """Render the final Markdown report from structured data and LLM narrative."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    health = report_data["health_score"]

    lines = [
        f"# Test Report: {target_url}",
        f"**Date:** {timestamp} | **Rounds:** {current_depth}/{max_depth} | **Health:** {health}%",
        "",
        "## Summary",
        llm_narrative,
        "",
        "## Results Overview",
        "| Round | Tests | Passed | Failed | Blocked | Surfaces |",
        "|-------|-------|--------|--------|---------|----------|",
    ]

    for rn in sorted(report_data["rounds"].keys()):
        rd = report_data["rounds"][rn]
        surfaces_str = ", ".join(list(rd["surfaces"])[:3])
        if len(rd["surfaces"]) > 3:
            surfaces_str += f" (+{len(rd['surfaces']) - 3} more)"
        lines.append(
            f"| {rn} | {rd['total']} | {rd['passed']} | {rd['failed']} | "
            f"{rd['blocked']} | {surfaces_str} |"
        )

    lines.extend(["", "## Critical Issues"])
    if report_data["critical_issues"]:
        for issue in report_data["critical_issues"]:
            lines.append(
                f"- **{issue['test_id']}** on `{issue['surface']}`: "
                f"{issue['observations'][:300]}"
            )
    else:
        lines.append("No critical issues found.")

    lines.extend(["", "## Coverage Map"])
    for surface in report_data["surfaces_tested"]:
        lines.append(f"- {surface}")

    lines.extend(["", "## Self-Healing Log"])
    if report_data["retry_log"]:
        for entry in report_data["retry_log"]:
            lines.append(
                f"- {entry['test_id']}: {entry['retries']} retries -> {entry['status']}"
            )
    else:
        lines.append("No self-healing retries needed.")

    return "\n".join(lines)


async def synthesizer_node(state: AgentState, config: Config) -> dict:
    """
    Synthesizer node: generates the final test report.

    Phase 1: Deterministic data aggregation
    Phase 2: LLM narrative summary
    Phase 3: Markdown report rendering and file output
    """
    target_url = state.get("target_url", "")
    current_depth = state.get("current_depth", 0)
    max_depth = state.get("max_depth", 5)

    # Phase 1: Deterministic report data
    report_data = generate_report_data(state)

    # Phase 2: LLM narrative summary
    critical_formatted = "\n".join(
        f"- {i['test_id']} on {i['surface']}: {i['observations'][:200]}"
        for i in report_data["critical_issues"]
    ) or "None"

    surfaces_formatted = "\n".join(
        f"- {s}" for s in report_data["surfaces_tested"]
    ) or "None"

    prompt = SYNTHESIZER_LLM_PROMPT.format(
        target_url=target_url,
        health_score=report_data["health_score"],
        current_depth=current_depth,
        max_depth=max_depth,
        passed=report_data["passed"],
        failed=report_data["failed"],
        blocked=report_data["blocked"],
        critical_issues_formatted=critical_formatted,
        surfaces_tested_formatted=surfaces_formatted,
    )

    try:
        llm = create_llm(config.synthesizer_model, 0.3)
        result = await call_llm_with_retry(
            llm,
            [HumanMessage(content=prompt)],
            max_retries=config.llm_max_retries,
            base_delay=config.llm_base_delay_seconds,
        )
        llm_narrative = result.content
    except Exception as e:
        llm_narrative = (
            f"(Report summary generation failed: {str(e)[:100]}. "
            "See structured data below for results.)"
        )

    # Phase 3: Render and save
    report = _render_markdown_report(
        target_url, current_depth, max_depth, report_data, llm_narrative
    )

    # Save report to file
    output_dir = config.report_output_path
    os.makedirs(output_dir, exist_ok=True)

    if config.report_format == "markdown":
        filename = os.path.join(output_dir, "report.md")
        with open(filename, "w", encoding="utf-8") as f:
            f.write(report)
    elif config.report_format == "json":
        import json
        filename = os.path.join(output_dir, "report.json")
        with open(filename, "w", encoding="utf-8") as f:
            json.dump({
                "target_url": target_url,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "health_score": report_data["health_score"],
                "total": report_data["total"],
                "passed": report_data["passed"],
                "failed": report_data["failed"],
                "blocked": report_data["blocked"],
                "critical_issues": report_data["critical_issues"],
                "surfaces_tested": report_data["surfaces_tested"],
                "narrative": llm_narrative,
            }, f, indent=2)

    return {"status": "done"}
