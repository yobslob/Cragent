"""
Executor node — executes a single test case using browser automation tools.

Each Executor instance gets an isolated browser context, an activity-based
timeout watchdog, and the 9-tool browser automation toolkit.
"""

import asyncio
import json
import re
import random
import time
from typing import Optional

from langgraph.prebuilt import create_react_agent
from playwright.async_api import async_playwright

from src.config import Config
from src.state import TestResult
from src.prompts import EXECUTOR_SYSTEM_PROMPT
from src.security.vault import CredentialVault
from src.browser.context_manager import create_browser_context, close_context, get_proxy
from src.tools.executor_tools import ExecutorContext, create_executor_tools
from src.llm.factory import create_llm


def _sanitize_observation(text: str) -> str:
    """
    Remove model artifacts from fallback observations.

    Catches two common failure modes with smaller local models:
      1. Model writes raw JSON function-call syntax instead of calling the tool
      2. Model echoes back parts of the system prompt
    """
    # Raw JSON function call (model described the action instead of doing it)
    if '"name":' in text and '"parameters":' in text:
        return "Executor described tool call in text without invoking the tool."
    # System-prompt leakage (═══ decoration or known section headers)
    if '═══' in text or 'EXECUTION PROTOCOL' in text or 'MANDATORY FINAL STEPS' in text:
        # Keep only plain content lines
        lines = [
            ln.strip() for ln in text.split('\n')
            if ln.strip()
            and '═══' not in ln
            and ln.strip() not in {
                'EXECUTION PROTOCOL', 'MANDATORY FINAL STEPS',
                'NAVIGATE', 'ORIENT', 'EXECUTE STEPS', 'SECURITY RULES',
            }
        ]
        cleaned = ' '.join(lines[:6])
        return (cleaned[:300] if cleaned
                else "Executor output contained system-prompt text rather than a verdict.")
    return text[:300]


def _extract_text_tool_call(messages: list) -> tuple[str | None, str | None]:
    """
    Parse text-based JSON tool calls written by models that don't use the tool
    calling API reliably (common with smaller local models like llama3.1:8b).

    Scans AI messages for patterns like:
      {"name": "report_test_result", "parameters": {"status": "PASS", "observations": "..."}}

    Returns (status, observations) if found, otherwise (None, None).
    """
    # Patterns to match report_test_result JSON in text
    _REPORT_RE = re.compile(
        r'"name"\s*:\s*"report_test_result".*?"parameters"\s*:\s*(\{[^{}]+\})',
        re.DOTALL,
    )
    _ALT_RE = re.compile(
        r'"function"\s*:\s*\{[^{}]*"name"\s*:\s*"report_test_result"[^{}]*"arguments"\s*:\s*(\{[^{}]+\})',
        re.DOTALL,
    )

    for msg in reversed(messages):
        content = msg.content if hasattr(msg, "content") else ""
        if not content or isinstance(content, list):
            continue
        msg_type = getattr(msg, "type", type(msg).__name__.lower())
        if "ai" not in msg_type and "assistant" not in msg_type:
            continue

        for pattern in (_REPORT_RE, _ALT_RE):
            m = pattern.search(content)
            if m:
                try:
                    params = json.loads(m.group(1))
                    status = params.get("status", "").upper().strip()
                    observations = str(params.get("observations", ""))[:500]
                    if status in ("PASS", "FAIL", "BLOCKED_CAPTCHA"):
                        return status, observations
                except (json.JSONDecodeError, AttributeError):
                    continue

        # Also try: the entire message is (or contains) a JSON object with
        # status/observations keys (some models skip the "name" wrapper)
        try:
            # Find any JSON objects in the content
            for json_match in re.finditer(r'\{[^<>]{10,}\}', content, re.DOTALL):
                try:
                    obj = json.loads(json_match.group())
                    status = obj.get("status", "").upper().strip()
                    observations = str(obj.get("observations", ""))[:500]
                    if status in ("PASS", "FAIL", "BLOCKED_CAPTCHA") and observations:
                        return status, observations
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass

    return None, None


def _infer_result_from_messages(
    agent_result: dict | None,
    test_id: str,
    target_url: str,
    current_depth: int,
) -> TestResult:
    """
    Fallback: extract a TestResult from the agent's text when
    report_test_result was not called (common with smaller local models).

    Priority order:
    1. Parse structured JSON tool call written as text (llama3.1:8b pattern)
    2. Keyword scan for PASS/FAIL in recent AI messages
    3. Generic FAIL
    """
    observations = "Executor completed without calling report_test_result."
    status = "FAIL"

    if not agent_result:
        return TestResult(
            test_id=test_id, status=status, tested_surface=target_url,
            target_url=target_url, observations=observations,
            discovered_elements=[], retry_count=0, round_number=current_depth,
        )

    messages = agent_result.get("messages", [])

    # 1. Try to extract status/observations from text-based JSON tool call
    extracted_status, extracted_obs = _extract_text_tool_call(messages)
    if extracted_status:
        return TestResult(
            test_id=test_id, status=extracted_status, tested_surface=target_url,
            target_url=target_url, observations=extracted_obs or observations,
            discovered_elements=[], retry_count=0, round_number=current_depth,
        )

    # 2. Keyword scan over recent AI message text
    ai_texts = []
    for msg in messages:
        content = msg.content if hasattr(msg, "content") else ""
        if not content:
            continue
        msg_type = getattr(msg, "type", type(msg).__name__.lower())
        if "ai" in msg_type or "assistant" in msg_type:
            ai_texts.append(content if isinstance(content, str) else str(content))

    if ai_texts:
        recent = " ".join(ai_texts[-2:])
        tail = recent[-600:].upper()

        pass_hit = "PASS" in tail
        fail_hit = any(k in tail for k in ("FAIL", "FAILED", "NOT PASS", "DIDN'T PASS", "DID NOT PASS"))

        if pass_hit and not fail_hit:
            status = "PASS"

        observations = _sanitize_observation(ai_texts[-1])

    return TestResult(
        test_id=test_id,
        status=status,
        tested_surface=target_url,
        target_url=target_url,
        observations=observations,
        discovered_elements=[],
        retry_count=0,
        round_number=current_depth,
    )


def _build_executor_message(test_case: dict) -> str:
    """Construct the user message for the Executor LLM with test case details."""
    parts = [
        f"Execute the following test case:\n",
        f"Test ID: {test_case.get('test_id', 'unknown')}",
        f"Description: {test_case.get('description', '')}",
        f"Category: {test_case.get('category', '')}",
        f"Target URL: {test_case.get('target_url', '')}",
        f"Is Destructive: {test_case.get('is_destructive', False)}",
    ]

    setup_steps = test_case.get("setup_steps", [])
    if setup_steps:
        parts.append(f"\nSetup Steps (execute first):")
        for i, step in enumerate(setup_steps, 1):
            parts.append(f"  {i}. {step}")

    steps = test_case.get("steps", [])
    parts.append(f"\nTest Steps:")
    for i, step in enumerate(steps, 1):
        parts.append(f"  {i}. {step}")

    parts.append(f"\nExpected Outcome: {test_case.get('expected_outcome', '')}")
    parts.append(f"Failure Criteria: {test_case.get('failure_criteria', '')}")

    return "\n".join(parts)


async def run_single_test(
    test_case: dict,
    credentials: dict,
    shared_auth_state: Optional[str],
    max_retries: int,
    current_depth: int,
    config: Config,
    executor_index: int = 0,
) -> TestResult:
    """
    Execute a single test case in an isolated browser context.

    This is the core logic shared by executor_node and serial_executor_node.

    Returns a TestResult dict.
    """
    test_id = test_case.get("test_id", "unknown")
    target_url = test_case.get("target_url", "")
    browser = None
    context_obj = None
    playwright_instance = None

    try:
        # Stagger start
        delay = random.uniform(
            config.stagger_start_delay_ms[0] / 1000,
            config.stagger_start_delay_ms[1] / 1000,
        )
        await asyncio.sleep(delay)

        # Browser setup
        playwright_instance = await async_playwright().start()
        proxy = get_proxy(config, executor_index)
        browser, browser_ctx, page = await create_browser_context(
            playwright_instance,
            config,
            storage_state=shared_auth_state,
            proxy=proxy,
        )

        # Create executor context and tools
        vault = CredentialVault(credentials)
        exec_ctx = ExecutorContext(page, vault, config)
        tools = create_executor_tools(exec_ctx)

        # Create LLM agent
        llm = create_llm(
            config.primary_model,
            config.temperature,
            ollama_base_url=config.ollama_base_url,
            ollama_num_ctx=config.ollama_num_ctx,
        )
        agent = create_react_agent(
            llm,
            tools=tools,
            prompt=EXECUTOR_SYSTEM_PROMPT,
        )

        # Build input message
        user_message = _build_executor_message(test_case)

        # Activity-based timeout watchdog
        last_activity = time.monotonic()
        original_tools = tools

        # Wrap tools to track activity
        for tool_obj in original_tools:
            if hasattr(tool_obj, "coroutine") and tool_obj.coroutine:
                original_func = tool_obj.coroutine
            elif hasattr(tool_obj, "func"):
                original_func = tool_obj.func
            else:
                continue

            async def tracked_func(*args, _orig=original_func, **kwargs):
                nonlocal last_activity
                last_activity = time.monotonic()
                return await _orig(*args, **kwargs)

            if hasattr(tool_obj, "coroutine"):
                tool_obj.coroutine = tracked_func

        # Run executor with timeout watchdog
        result_container = {"result": None}

        async def run_executor():
            result_container["result"] = await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_message}]}
            )

        async def watchdog():
            while True:
                await asyncio.sleep(10)
                elapsed = time.monotonic() - last_activity
                if elapsed > config.node_inactivity_timeout_seconds:
                    raise TimeoutError(
                        f"Executor inactive for {elapsed:.0f}s (no tool calls)"
                    )

        try:
            executor_task = asyncio.create_task(run_executor())
            watchdog_task = asyncio.create_task(watchdog())

            done, pending = await asyncio.wait(
                {executor_task, watchdog_task},
                timeout=config.node_absolute_timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

            if executor_task in done:
                # Check if executor raised an exception
                if executor_task.exception():
                    raise executor_task.exception()
            else:
                # Timeout
                return TestResult(
                    test_id=test_id,
                    status="FAIL",
                    tested_surface=target_url,
                    target_url=target_url,
                    observations=(
                        f"Executor timed out — no tool activity for "
                        f"{config.node_inactivity_timeout_seconds}s or "
                        f"absolute timeout of {config.node_absolute_timeout_seconds}s reached."
                    ),
                    discovered_elements=[],
                    retry_count=0,
                    round_number=current_depth,
                )

        except TimeoutError as e:
            return TestResult(
                test_id=test_id,
                status="FAIL",
                tested_surface=target_url,
                target_url=target_url,
                observations=str(e),
                discovered_elements=[],
                retry_count=0,
                round_number=current_depth,
            )

        # Extract result from executor context
        if exec_ctx.test_result:
            return TestResult(
                test_id=test_id,
                status=exec_ctx.test_result.status,
                tested_surface=target_url,
                target_url=target_url,
                observations=exec_ctx.test_result.observations,
                discovered_elements=exec_ctx.test_result.discovered_elements,
                retry_count=exec_ctx.test_result.retry_count,
                round_number=current_depth,
            )
        else:
            # report_test_result was not called — infer result from agent text
            # (common with smaller local models that describe results in text
            #  without calling the final tools)
            return _infer_result_from_messages(
                result_container.get("result"),
                test_id,
                target_url,
                current_depth,
            )

    except Exception as e:
        return TestResult(
            test_id=test_id,
            status="FAIL",
            tested_surface=target_url,
            target_url=target_url,
            observations=f"Executor crashed: {str(e)[:200]}",
            discovered_elements=[],
            retry_count=0,
            round_number=current_depth,
        )
    finally:
        await close_context(browser, browser_ctx if 'browser_ctx' in dir() else None)
        if playwright_instance:
            try:
                await playwright_instance.stop()
            except Exception:
                pass


async def executor_node(state: dict, config: Config) -> dict:
    """
    Executor graph node — receives a single test case from Send() and executes it.

    Returns {"past_results": [result_dict]} for the dedup reducer.
    """
    test_case = state.get("test_case", {})
    credentials = state.get("credentials", {})
    shared_auth_state = state.get("shared_auth_state")
    max_retries = state.get("max_retries", 3)
    current_depth = state.get("current_depth", 1)

    result = await run_single_test(
        test_case=test_case,
        credentials=credentials,
        shared_auth_state=shared_auth_state,
        max_retries=max_retries,
        current_depth=current_depth,
        config=config,
    )

    return {"past_results": [dict(result)]}
