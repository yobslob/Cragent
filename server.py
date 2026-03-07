"""Thin FastAPI backend that wraps the existing CLI agent pipeline.

Streams all agent output (logs, LLM calls, browser actions, errors) to the
frontend via Server-Sent Events (SSE).

Does NOT modify any existing agent/LangGraph/browser-use code.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command
from sse_starlette.sse import EventSourceResponse

from src.config import load_config
from src.graph.builder import build_graph
from src.models.state import PlannerRequest

# ---------------------------------------------------------------------------
# Load environment variables (same as CLI does)
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Cragent Web UI", version="0.1.0")

# Serve static files (index.html lives in static/)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the frontend."""
    try:
        return FileResponse("static/index.html", media_type="text/html")
    except Exception:
        traceback.print_exc()
        return HTMLResponse("<h1>Error loading frontend</h1>", status_code=500)


# ---------------------------------------------------------------------------
# SSE streaming helpers
# ---------------------------------------------------------------------------

def _timestamp() -> str:
    """Return an ISO-8601 UTC timestamp string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sse_msg(msg_type: str, content: str, **extra: Any) -> str:
    """Build a JSON payload for an SSE event."""
    payload: dict[str, Any] = {
        "type": msg_type,
        "timestamp": _timestamp(),
        "content": content,
    }
    payload.update(extra)
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Custom logging handler that pushes log records into an asyncio.Queue
# ---------------------------------------------------------------------------

class QueueLogHandler(logging.Handler):
    """Logging handler that puts formatted records into an asyncio Queue."""

    def __init__(self, queue: asyncio.Queue[str]) -> None:
        super().__init__()
        self._queue = queue
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def emit(self, record: logging.Record) -> None:
        try:
            msg = self.format(record)
            payload = _sse_msg("log", msg)
            if self._loop is not None and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._queue.put_nowait, payload)
            else:
                try:
                    self._queue.put_nowait(payload)
                except Exception:
                    pass
        except Exception:
            self.handleError(record)


# ---------------------------------------------------------------------------
# Stdout/Stderr captor that also writes to a queue
# ---------------------------------------------------------------------------

class StreamCaptor(io.TextIOBase):
    """Wraps an original stream; copies writes to an asyncio.Queue as SSE messages."""

    def __init__(
        self,
        original: Any,
        queue: asyncio.Queue[str],
        stream_name: str,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._original = original
        self._queue = queue
        self._stream_name = stream_name
        self._loop = loop

    def write(self, s: str) -> int:
        if s and s.strip():
            payload = _sse_msg("stdout" if self._stream_name == "stdout" else "stderr", s.rstrip())
            if self._loop is not None and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._queue.put_nowait, payload)
            else:
                try:
                    self._queue.put_nowait(payload)
                except Exception:
                    pass
        # Also write to the original stream so server console still works
        if self._original is not None:
            try:
                return self._original.write(s)
            except Exception:
                return len(s) if s else 0
        return len(s) if s else 0

    def flush(self) -> None:
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass

    def fileno(self) -> int:
        if self._original is not None:
            return self._original.fileno()
        raise io.UnsupportedOperation("fileno")

    @property
    def encoding(self) -> str:
        if hasattr(self._original, "encoding"):
            return self._original.encoding
        return "utf-8"


# ---------------------------------------------------------------------------
# Core agent runner — mirrors src/main.py:run_agent() logic without modification
# ---------------------------------------------------------------------------

async def _run_agent_pipeline(
    url: str,
    instructions: str,
    config_path: str,
    queue: asyncio.Queue[str],
) -> None:
    """Run the full agent pipeline, streaming progress to the SSE queue.

    This function mirrors the logic in src/main.py:run_agent() but replaces
    interactive prompts with auto-approve and sends all output via the queue.
    """
    loop = asyncio.get_event_loop()

    # Install logging handler
    root_logger = logging.getLogger()
    queue_handler = QueueLogHandler(queue)
    queue_handler.set_loop(loop)
    queue_handler.setFormatter(logging.Formatter("%(levelname)s | %(name)s | %(message)s"))
    queue_handler.setLevel(logging.WARNING)
    root_logger.addHandler(queue_handler)
    original_level = root_logger.level

    # Install stdout/stderr captors
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    stdout_captor = StreamCaptor(original_stdout, queue, "stdout", loop)
    stderr_captor = StreamCaptor(original_stderr, queue, "stderr", loop)
    sys.stdout = stdout_captor  # type: ignore[assignment]
    sys.stderr = stderr_captor  # type: ignore[assignment]

    try:
        # ── Step 1: Load config ──
        await queue.put(_sse_msg("status", "Loading configuration..."))
        try:
            config = load_config(config_path)
        except Exception:
            tb = traceback.format_exc()
            await queue.put(_sse_msg("error", f"Failed to load config:\n{tb}"))
            return

        # ── Step 2: Apply overrides ──
        if url:
            config.target_url = url
        # Force auto-approve for web UI (no interactive prompts)
        config.approval.mode = "auto_approve"

        target_url = config.target_url
        user_instructions = instructions.strip() if instructions else ""

        await queue.put(_sse_msg("status", f"Target URL: {target_url}"))
        if user_instructions:
            await queue.put(_sse_msg("status", f"Instructions: {user_instructions}"))
        else:
            await queue.put(_sse_msg("status", "No instructions — planner will auto-detect tests."))

        # ── Step 3: Build the LangGraph graph ──
        await queue.put(_sse_msg("status", "Building agent graph..."))
        try:
            graph = build_graph(config)
        except Exception:
            tb = traceback.format_exc()
            await queue.put(_sse_msg("error", f"Failed to build graph:\n{tb}"))
            return

        # ── Step 4: Seed initial state — same logic as run_agent() ──
        seed_urls = [target_url]
        raw_extras = list(config.extra_urls or [])
        for u in raw_extras:
            if u.startswith("/"):
                base = target_url.rstrip("/")
                seed_urls.append(f"{base}{u}")
            elif u.startswith(("http://", "https://")):
                seed_urls.append(u)
            else:
                base = target_url.rstrip("/")
                seed_urls.append(f"{base}/{u}")

        # Deduplicate while preserving order
        seen: set[str] = set()
        seed_queue: list[dict] = []
        for u in seed_urls:
            normalized = u.rstrip("/").lower()
            if normalized not in seen:
                seen.add(normalized)
                req = PlannerRequest(
                    url=u,
                    depth=0,
                    user_instructions=user_instructions,
                )
                seed_queue.append(req.to_dict())

        await queue.put(_sse_msg("status", f"Seeded {len(seed_queue)} URL(s) into planner queue"))

        initial_state: dict[str, Any] = {
            "queue": seed_queue,
            "visited_urls": [],
            "reports": [],
            "current_request": None,
            "current_test_plan": None,
            "current_results": [],
            "final_report": None,
            "total_cost": 0.0,
            "planner_context": "",
            "planner_clarification_count": 0,
        }

        thread_id = hashlib.md5(target_url.encode()).hexdigest()
        graph_config = {"configurable": {"thread_id": thread_id}}

        # ── Step 5: Run the graph loop — same as run_agent() ──
        await queue.put(_sse_msg("status", "Starting agent pipeline..."))

        input_data: dict | Command = initial_state
        result: dict[str, Any] = {}

        while True:
            try:
                await queue.put(_sse_msg("status", "Invoking graph (next iteration)..."))

                result = await graph.ainvoke(input_data, graph_config)

                # Check for interrupts
                snapshot = await graph.aget_state(graph_config)
                if not snapshot.next:
                    await queue.put(_sse_msg("status", "Graph execution completed."))
                    break

                # Handle interrupts (auto-approve for web UI)
                interrupt_data = _find_first_interrupt(snapshot.tasks)
                if interrupt_data is None:
                    await queue.put(_sse_msg("status", "Graph paused with no interrupts — terminating."))
                    break

                itype = interrupt_data.get("type", "approval")

                if itype == "planner_clarification":
                    question = interrupt_data.get("question", "")
                    url_asking = interrupt_data.get("url", "")
                    await queue.put(_sse_msg("interrupt", f"Planner needs input for {url_asking}: {question}"))
                    # Auto-respond with empty string (let planner decide on its own)
                    input_data = Command(resume="")
                else:
                    # Approval interrupt — auto-approve
                    approve_url = interrupt_data.get("url", "unknown")
                    depth = interrupt_data.get("depth", "?")
                    reason = interrupt_data.get("reason", "")
                    await queue.put(_sse_msg("status", f"Auto-approving sub-page: {approve_url} (depth={depth})"))
                    input_data = Command(resume=True)

            except Exception:
                tb = traceback.format_exc()
                await queue.put(_sse_msg("error", f"Pipeline error:\n{tb}"))
                break

        # ── Step 6: Extract and send results ──
        reports = result.get("reports", []) if isinstance(result, dict) else []
        final_report = result.get("final_report", "") if isinstance(result, dict) else ""

        await queue.put(_sse_msg("status", f"Run finished. {len(reports)} report(s) generated."))

        # Send structured results
        await queue.put(_sse_msg("results", json.dumps(reports), reports=reports))

        if final_report:
            await queue.put(_sse_msg("report", final_report))

        # Summary stats
        total_pass = 0
        total_fail = 0
        total_error = 0
        for report in reports:
            results_list = report.get("results", [])
            total_pass += sum(1 for r in results_list if r.get("status") == "pass")
            total_fail += sum(1 for r in results_list if r.get("status") == "fail")
            total_error += sum(1 for r in results_list if r.get("status") == "error")

        summary = f"Total: {total_pass} pass, {total_fail} fail, {total_error} error"
        await queue.put(_sse_msg("summary", summary, pass_count=total_pass, fail_count=total_fail, error_count=total_error))

        await queue.put(_sse_msg("done", "Agent run completed."))

    except Exception:
        tb = traceback.format_exc()
        await queue.put(_sse_msg("error", f"Unhandled error:\n{tb}"))
        await queue.put(_sse_msg("done", "Agent run finished with errors."))

    finally:
        # Restore stdout/stderr and remove logging handler
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        root_logger.removeHandler(queue_handler)
        root_logger.setLevel(original_level)


def _find_first_interrupt(tasks: Any) -> dict[str, Any] | None:
    """Extract the first interrupt value from LangGraph snapshot tasks.

    Same logic as src/main.py:_find_first_interrupt().
    """
    try:
        for task in tasks:
            if hasattr(task, "interrupts") and task.interrupts:
                return task.interrupts[0].value
    except Exception:
        traceback.print_exc()
    return None


# ---------------------------------------------------------------------------
# API endpoint — run agent and stream results via SSE
# ---------------------------------------------------------------------------

@app.get("/api/run")
async def run_agent_sse(url: str, instructions: str = "", config: str = "config.yaml"):
    """Start an agent run and stream all output via SSE.

    Query params:
        url: Target URL to test.
        instructions: Testing instructions (optional).
        config: Path to config YAML (default: config.yaml).
    """


    event_queue: asyncio.Queue[str] = asyncio.Queue()

    async def event_generator():
        """Yield SSE events from the queue."""
        # Start the agent pipeline as a background task
        task = asyncio.create_task(
            _run_agent_pipeline(url, instructions, config, event_queue)
        )

        try:
            while True:
                try:
                    # Wait for next message with a timeout
                    msg = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    yield {"data": msg}

                    # Check if this was the "done" message
                    try:
                        parsed = json.loads(msg)
                        if parsed.get("type") == "done":
                            break
                    except json.JSONDecodeError:
                        pass
                except asyncio.TimeoutError:
                    # Send a heartbeat to keep the connection alive
                    yield {"data": _sse_msg("heartbeat", "")}

                    # Check if the task is done (e.g. crashed without sending "done")
                    if task.done():
                        exc = task.exception()
                        if exc:
                            tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                            yield {"data": _sse_msg("error", f"Agent task crashed:\n{tb_str}")}
                        yield {"data": _sse_msg("done", "Agent run finished.")}
                        break

        except asyncio.CancelledError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        except Exception:
            tb = traceback.format_exc()

            yield {"data": _sse_msg("error", f"SSE error:\n{tb}")}
            yield {"data": _sse_msg("done", "Agent run finished with errors.")}

    try:
        return EventSourceResponse(event_generator())
    except Exception:
        traceback.print_exc()
        return {"error": "Failed to start SSE stream"}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    """Simple health check."""
    return {"status": "ok", "timestamp": _timestamp()}


# ---------------------------------------------------------------------------
# Main entry for `python server.py`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    print(f"[{_timestamp()}] Starting Cragent Web UI server...")
    print(f"[{_timestamp()}] Open http://localhost:8000 in your browser")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
