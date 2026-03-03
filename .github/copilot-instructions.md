# Project Instructions

## Overview

Autonomous website testing agent — CLI tool that crawls a target URL, generates test plans via LLM, executes them with headless browsers, and produces a severity-classified Markdown report. No frontend, no HTTP servers.

**Stack:** Python 3.11+ · `uv` + `pyproject.toml` · browser-use · LangGraph · Rich · Pydantic v2

## Build & Run

```bash
make develop          # Install all deps (uv sync --all-extras)
make run              # Run agent: uv run python -m src.main --config config.yaml
make run-auto         # Run with auto-approval
make check            # Full CI: lint + test
make lint             # ruff check src/ tests/
make format           # ruff format + ruff check --fix
make test             # pytest tests/ -v
make test-slow        # pytest with 300s timeout
make clean            # Remove __pycache__, .pyc, .ruff_cache
```

Always use `make` targets. Run commands via `uv run ...` inside the environment.

## Architecture

LangGraph `StateGraph` with 6 nodes in a loop (`src/graph/builder.py`):

```
START → dequeue → approve → plan → execute → compile → dequeue (loop)
                                                           ↓ (queue empty)
                                                       summarize → END
```

| Node | File | Purpose |
|---|---|---|
| `dequeue_node` | `src/graph/nodes/dequeue.py` | Pops next URL from FCFS queue, skips visited/depth violations |
| `approve_node` | `src/graph/nodes/approve.py` | Human-in-the-loop gate via LangGraph `interrupt()`. Root depth always auto-approved |
| `plan_node` | `src/graph/nodes/plan.py` | Direct `llm.ainvoke()` to produce `TestPlan` JSON. 3-tier fallback: primary → fallback LLM → generic plan |
| `execute_node` | `src/graph/nodes/execute.py` | Parallel `browser_use.Agent` per test case, bounded by `asyncio.Semaphore` |
| `compile_node` | `src/graph/nodes/compile.py` | Aggregates results into `PlannerReport`, enqueues discovered sub-pages |
| `summarize_node` | `src/graph/nodes/summarize.py` | LLM produces final Markdown report, writes to `report.md` |

**Key design decisions:**
- **Planner NEVER uses browser-use Agent** — only direct `llm.ainvoke()`. Browser agents waste steps browsing.
- **Only executor spawns browsers.** Each test case gets its own isolated `BrowserSession`.
- Config bound to nodes via `functools.partial` in `build_graph()`. Node param is named `app_config` (NOT `config`) to avoid conflicts with LangGraph's `RunnableConfig`.
- State is a `TypedDict` (`GraphState` in `src/models/state.py`). Nodes return partial update dicts.
- Pydantic models serialized via `model_dump()` before entering state, deserialized via `model_validate()` when read.

## Code Style

- **`from __future__ import annotations`** in every file.
- Lowercase generics: `dict[str, Any]`, `list[str]`, `X | None` (not `Optional[X]`).
- Ruff rules: `E, F, I, N, W, UP, B, SIM, RUF`. Line length 100.
- Google-style docstrings on every function (summary, `Args:`, `Returns:`, `Raises:`).
- Module-level docstrings describing purpose in every file.
- `logger = logging.getLogger(__name__)` per module. Rich `RichHandler` in `src/main.py`.
- Conventional Commits: `feat:`, `fix:`, `refactor:`. Imperative mood, ≤50 char subject.
- Never swallow exceptions — always `logger.exception()` or `logger.error()`.

## Project Conventions

### LLM Factory (`src/llm/factory.py`)
- Must use `browser_use.llm.*` wrappers (e.g., `ChatOpenRouter`), NOT raw `langchain_*` — browser-use `Agent` checks `llm.provider`.
- `ChatOllama` uses `host=` parameter, not `base_url=`.
- API keys resolved from env vars via `_resolve_api_key()`.
- Lazy imports inside provider `if` branches to avoid unnecessary deps.

### Concurrency (`src/graph/nodes/execute.py`)
- `asyncio.Semaphore` bounds parallel executor count.
- Stagger delay between launches prevents rate-limit bursts.
- `asyncio.gather(*tasks, return_exceptions=True)` — individual failures don't kill the batch.
- `BrowserSession` closed in `finally` blocks.

### Fallback Patterns
- Planner: primary LLM → fallback LLM → `generate_fallback_plan()` (`src/utils/fallback.py`).
- JSON extraction: direct parse → markdown code block → brace-matching with key search.
- Summarizer: LLM → plain string concatenation fallback.
- Executor: `browser_use.Agent(fallback_llm=...)` for auto-retry.

### Auth Propagation
- `PlannerRequest.parent_storage_state` carries browser cookies/localStorage across recursive plans.
- `_is_auth_test()` heuristic detects login tests; storage state exported post-execution.

### URL Utils (`src/utils/url.py`)
- `normalize_url()` for deduplication: lowercases scheme/host, strips trailing slash/fragments, sorts query params.
- `is_same_domain()` for domain boundary checks.

## Configuration

`config.yaml` schema defined in `AppConfig` (`src/config.py`). Key fields:
- `target_url` — must start with `http://` or `https://`
- `llm.planner/executor/summarizer` — independent `LLMProviderConfig` per role (provider, model, base_url, api_key_env)
- `llm.fallback` — optional fallback LLM config
- `concurrency.max_executors` (1–20, default 4), `stagger_delay_seconds`, `step_timeout`
- `depth.max_depth` (default 0 — sub-page recursion rarely needed)
- `approval.mode` — `interrupt` | `auto_approve` (default) | `auto_decline`
- `browser.headless`, `browser.proxy`

Providers: `openrouter`, `groq`, `ollama`, `nvidia`, `openai`.

## Testing

- `pytest-asyncio` with `asyncio_mode = "auto"`. Tests in `tests/`.
- Always `make check` before marking work done.
- Test public interfaces only. Use parametrization and fixtures.

## Lessons Learned (`tasks/lessons.md`)

Review before making changes — hard-won debugging patterns:
1. Planner must NEVER use browser-use Agent.
2. Must use `browser_use.llm` wrappers, not raw LangChain.
3. Node params: use `app_config`, never `config`.
4. `AgentSettings` doesn't exist in browser-use v0.12.1 — use `extend_system_message=`.
5. Always pass `fallback_llm` and enable `flash_mode=True`.
6. `max_steps=15` hard limit — simplify tests instead of increasing.

## Workflow

1. Plan non-trivial tasks in `tasks/todo.md` before starting.
2. Track progress; update `tasks/lessons.md` after any correction.
3. Use subagents for research and parallel analysis.
4. Verify changes work (`make check`) before marking complete.
5. Keep changes minimal and backward-compatible.
