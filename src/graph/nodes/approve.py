"""Approve node — human-in-the-loop gating for sub-page planners."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import Command, interrupt

from src.config import AppConfig

logger = logging.getLogger(__name__)


def approve_node(state: dict[str, Any], app_config: AppConfig) -> dict[str, Any] | Command:
    """Gate sub-page planner requests through human approval (or auto-approve/decline).

    - Root planners (depth == 0) are always auto-approved.
    - Behavior for sub-page planners depends on app_config.approval.mode.

    Args:
        state: Current LangGraph state.
        app_config: Application configuration.

    Returns:
        Unchanged state (approved) or Command(goto="dequeue") to skip.
    """
    current_request = state.get("current_request")
    if current_request is None:
        # Shouldn't happen, but defensive
        return {}

    depth = current_request.get("depth", 0)
    url = current_request.get("url", "")

    # Root planner is always auto-approved
    if depth == 0:
        logger.info(f"Auto-approved root planner: {url}")
        return {}

    mode = app_config.approval.mode

    if mode == "auto_approve":
        logger.info(f"Auto-approved sub-page planner (mode=auto_approve): {url}")
        return {}

    if mode == "auto_decline":
        logger.info(f"Auto-declined sub-page planner (mode=auto_decline): {url}")
        return Command(goto="dequeue_node")

    # mode == "interrupt" — ask the human
    logger.info(f"Requesting human approval for sub-page planner: {url} (depth {depth})")
    approval = interrupt(
        {
            "url": url,
            "depth": depth,
            "reason": f"Sub-page planner at depth {depth} wants to test: {url}",
        }
    )

    if approval:
        logger.info(f"Human approved sub-page planner: {url}")
        return {}
    else:
        logger.info(f"Human declined sub-page planner: {url}")
        return Command(goto="dequeue_node")
