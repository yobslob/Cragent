# Plan: Autonomous Website Testing Agent (browser-use + LangGraph)

**TL;DR** — Build a recursive website testing agent using **browser-use v0.12.1** for browser automation and **LangGraph v1.0.10** as the orchestration layer. LangGraph's `StateGraph` manages the FCFS planner queue, with `interrupt()` providing human-in-the-loop approval for sub-page planners. Each planner runs a read-only browser-use `Agent` to produce a structured `TestPlan`, then spawns parallel executor `Agent` instances (semaphore-bounded, stagger-delayed) to run those tests. Auth state propagates to child planners via `storage_state` export. After queue drains, a lightweight LLM summarizer produces a severity-classified Markdown report. LLM providers are fully configurable (Ollama/OpenRouter/Groq/NVIDIA) via a YAML config that maps planner, executor, and summarizer to independent models.

---

## 1. Project Scaffold and Dependencies

Create the project root with `pyproject.toml` using **Python ≥3.11**. Core deps:

- `browser-use==0.12.1` (includes `pydantic==2.12.5`, `openai==2.16.0`, `groq==1.0.0`, `ollama==0.6.1`)
- `langgraph>=1.0.10` (for StateGraph + `interrupt()`)
- `langgraph-checkpoint>=2.1.0` (InMemorySaver for dev, sqlite for persistence)
- `pyyaml` (config loading)
- `rich` (CLI output formatting)

Create `.env.example` with slots for `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY`, `OPENAI_API_KEY` (only the one the user needs).

Create `config.yaml` with sections for:

- `target_url` — root URL to test
- `user_instructions` — optional scope/focus text
- `llm.planner` — `{provider, model, base_url?, api_key_env?}`
- `llm.executor` — same schema
- `llm.summarizer` — same schema
- `concurrency.max_executors` — semaphore bound (default: 4)
- `concurrency.stagger_delay_seconds` — delay between executor launches (default: 2.0)
- `concurrency.step_timeout` — per-agent step timeout (default: 180)
- `depth.max_depth` — max planner recursion depth (default: 2)
- `approval.mode` — `"interrupt"` | `"auto_approve"` | `"auto_decline"`
- `approval.timeout_seconds` — auto-decline after N seconds (default: 120)
- `report.output_path` — Markdown report output path
- `browser.headless` — default `true`
- `browser.proxy` — optional proxy settings
- `browser.use_cloud` — use Browser Use cloud for stealth (default: false)

Directory structure:

```
web_test_agent/
├── pyproject.toml
├── .env.example
├── config.yaml
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── state.py
│   │   ├── test_plan.py
│   │   ├── executor_result.py
│   │   └── report.py
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── builder.py
│   │   └── nodes/
│   │       ├── __init__.py
│   │       ├── dequeue.py
│   │       ├── approve.py
│   │       ├── plan.py
│   │       ├── execute.py
│   │       ├── compile.py
│   │       └── summarize.py
│   ├── llm/
│   │   ├── __init__.py
│   │   └── factory.py
│   └── utils/
│       ├── __init__.py
│       ├── url.py
│       └── fallback.py
```

---

## 2. Define Pydantic Models

### `models/test_plan.py`

The structured output schema the planner agent must produce:

- `TestCase`: `name: str`, `description: str`, `url: str`, `steps: list[str]`, `expected_outcome: str`, `priority: Literal["critical", "high", "medium", "low"]`
- `SubPage`: `url: str`, `reason: str`, `requires_auth: bool`
- `TestPlan`: `test_cases: list[TestCase]`, `sub_pages: list[SubPage]`, `page_summary: str`

### `models/executor_result.py`

Structured output for each executor agent:

- `ExecutorResult`: `test_name: str`, `status: Literal["pass", "fail", "error", "skip"]`, `evidence: str` (extracted text / observation), `error_detail: str | None`, `steps_executed: list[str]`, `duration_seconds: float`

### `models/report.py`

Planner report:

- `PlannerReport`: `url: str`, `depth: int`, `page_summary: str`, `results: list[ExecutorResult]`, `pass_count: int`, `fail_count: int`, `error_count: int`

### `models/state.py`

LangGraph state schema (must be JSON-serializable):

- `PlannerRequest`: `url: str`, `depth: int`, `parent_storage_state: dict | None`, `user_instructions: str`
- `GraphState(TypedDict)`: `queue: list[PlannerRequest]`, `visited_urls: list[str]`, `reports: list[dict]` (serialized PlannerReport), `current_request: PlannerRequest | None`, `current_test_plan: dict | None`, `current_results: list[dict]`, `final_report: str | None`

---

## 3. Build the LLM Factory

### `llm/factory.py`

A function `create_llm(provider_config: dict) -> BaseChatModel` that reads provider/model/base_url from config and returns the appropriate browser-use LLM wrapper:

- `"openrouter"` → `ChatOpenAI(model=..., base_url="https://openrouter.ai/api/v1", api_key=...)`
- `"groq"` → `ChatGroq(model=...)`
- `"ollama"` → `ChatOllama(model=...)`
- `"nvidia"` → `ChatOpenAI(model=..., base_url="https://integrate.api.nvidia.com/v1", api_key=...)`
- `"openai"` → `ChatOpenAI(model=...)`

All imports from `browser_use` (e.g., `from browser_use import ChatOpenAI, ChatGroq, ChatOllama`). These are browser-use's native wrappers, NOT LangChain's.

---

## 4. Build LangGraph StateGraph

### `graph/builder.py`

Construct and compile the graph:

```
StateGraph(GraphState):
  START → dequeue_node
  dequeue_node → approve_node    (conditional: if current_request exists)
  dequeue_node → summarize_node  (conditional: if queue empty + no current_request)
  approve_node → plan_node       (conditional: if approved)
  approve_node → dequeue_node    (conditional: if declined — skip this URL)
  plan_node → execute_node
  execute_node → compile_node
  compile_node → dequeue_node    (loop back)
  summarize_node → END
```

Compile with `InMemorySaver` checkpointer (upgradeable to SQLite for persistence). Thread ID is the root URL hash for uniqueness.

---

## 5. Implement Graph Nodes

### `nodes/dequeue.py`

`dequeue_node(state: GraphState) -> dict`:

- Pop first item from `state["queue"]`
- If queue empty and no current request → set `current_request = None` (signals routing to summarize)
- Otherwise → validate URL not in `visited_urls`, check `depth ≤ max_depth`, normalize URL (strip trailing slash, fragments, sort query params via `utils/url.py`). If duplicate or too deep, skip and pop next. Set `current_request` to the dequeued item. Add URL to `visited_urls`.

### `nodes/approve.py`

`approve_node(state: GraphState) -> dict | Command`:

- If `current_request.depth == 0` (root planner) → auto-approve, return unchanged state
- If config `approval.mode == "auto_approve"` → auto-approve
- If config `approval.mode == "auto_decline"` → auto-decline, return `Command(goto="dequeue")`
- Otherwise → call `interrupt({"url": current_request.url, "depth": current_request.depth, "reason": "Sub-page planner requires approval"})`. The return value of `interrupt()` is the boolean approval.
- Since the node re-executes on resume: guard side effects with an idempotency check (check if `state["current_request"]` is already approved)

### `nodes/plan.py`

`plan_node(state: GraphState) -> dict`:

- Create read-only browser-use agent:

  ```python
  tools = Tools(exclude_actions=[
      "click", "input", "send_keys", "upload_file",
      "select_dropdown", "dropdown_options"
  ])
  session = BrowserSession(headless=config.browser.headless, ...)
  agent = Agent(
      task=build_planner_prompt(state["current_request"]),
      llm=create_llm(config.llm.planner),
      browser_session=session,
      tools=tools,
      output_model_schema=TestPlan,
      use_vision=True,
      max_actions_per_step=3,
      step_timeout=config.concurrency.step_timeout,
  )
  ```

- The planner prompt instructs: "Analyze this page. Produce a TestPlan JSON with concrete test cases and sub-pages worth deeper testing. You can navigate, scroll, extract content, take screenshots, evaluate JavaScript, but you CANNOT click or type. Focus on discovering testable functionality."
- If `current_request.parent_storage_state` is set, inject into session for authenticated access
- Run agent: `result = await agent.run(max_steps=30)`
- Parse structured output. On failure → **3-tier fallback**: (1) Retry once with `fallback_llm` if configured, (2) Attempt regex JSON extraction from raw `extracted_content`, (3) Generate generic fallback plan via `utils/fallback.py` (test all links return 200, all images load, page has no console errors, forms are present)
- Close browser session
- Return `{"current_test_plan": test_plan.model_dump()}`

### `nodes/execute.py`

`execute_node(state: GraphState) -> dict`:

- Read `TestPlan` from `state["current_test_plan"]`
- Create an `asyncio.Semaphore(config.concurrency.max_executors)`
- For each `TestCase`, create an async task:

  ```python
  async def run_executor(test_case, semaphore, stagger_index):
      await asyncio.sleep(stagger_index * config.concurrency.stagger_delay_seconds)
      async with semaphore:
          session = BrowserSession(
              headless=True,
              storage_state=state["current_request"].get("parent_storage_state"),
          )
          agent = Agent(
              task=build_executor_prompt(test_case),
              llm=create_llm(config.llm.executor),
              browser_session=session,
              output_model_schema=ExecutorResult,
              flash_mode=True,
              max_actions_per_step=5,
              step_timeout=config.concurrency.step_timeout,
              use_vision=True,
          )
          try:
              start = time.time()
              result = await agent.run(max_steps=50)
              # parse ExecutorResult from structured output
          except Exception as e:
              # return error ExecutorResult
          finally:
              await session.close()  # CRITICAL: always cleanup
  ```

- Launch all tasks with `asyncio.gather(*tasks, return_exceptions=True)` — `return_exceptions=True` prevents one failure from killing others
- Collect all `ExecutorResult` objects
- Return `{"current_results": [r.model_dump() for r in results]}`

### `nodes/compile.py`

`compile_node(state: GraphState) -> dict`:

- Build `PlannerReport` from `current_results` + `current_request` metadata
- Extract `sub_pages` from `current_test_plan` and create new `PlannerRequest` entries:
  - Set `depth = current_request.depth + 1`
  - Skip if URL already in `visited_urls` or `depth > max_depth`
  - If `requires_auth` on sub-page and current planner had `parent_storage_state`, propagate it. Otherwise, if any executor logged in during this planner's run, export a storage_state from one of the executor sessions (this requires the executor to export state before closing — add a post-run hook)
- Append `PlannerReport` to `state["reports"]`
- Append new `PlannerRequest` items to end of `state["queue"]`
- Clear `current_request`, `current_test_plan`, `current_results`
- Return updated state dict

### `nodes/summarize.py`

`summarize_node(state: GraphState) -> dict`:

- Concatenate all `PlannerReport` objects into a structured text prompt
- Call summarizer LLM (NOT a browser-use agent, just a direct LLM call via the factory):

  ```python
  llm = create_llm(config.llm.summarizer)
  prompt = build_summarizer_prompt(state["reports"])
  response = await llm.ainvoke([
      SystemMessage(content=SUMMARIZER_SYSTEM_PROMPT),
      UserMessage(content=prompt)
  ])
  ```

- The summarizer system prompt instructs: classify findings by severity (Critical / High / Medium / Low / Info), group by page, write an executive summary, list all failures with reproduction steps
- Write final Markdown report to `config.report.output_path`
- Return `{"final_report": response.content}`

---

## 6. Implement the CLI Entry Point

### `main.py`

- Parse CLI args: `--config config.yaml` (required), `--url` (override), `--auto-approve` (flag)
- Load and validate config via `config.py` (Pydantic Settings model)
- Build the LangGraph graph via `graph/builder.py`
- Seed initial state: `queue=[PlannerRequest(url=target_url, depth=0, ...)]`, empty everything else
- Run the graph:

  ```python
  config = {"configurable": {"thread_id": hashlib.md5(target_url.encode()).hexdigest()}}

  # Stream to handle interrupts
  result = None
  input_data = initial_state
  while True:
      result = await graph.ainvoke(input_data, config)
      if "__interrupt__" in result:
          interrupt_data = result["__interrupt__"][0].value
          # CLI prompt with timeout
          approved = await async_input_with_timeout(
              f"Approve planner for {interrupt_data['url']}? [y/n]: ",
              timeout=config.approval.timeout_seconds,
              default=False
          )
          input_data = Command(resume=approved)
      else:
          break  # Graph completed
  ```

- Print summary to terminal via `rich`
- Exit with code 0 (all pass) or 1 (any failures)

---

## 7. Implement Utility Modules

### `utils/url.py`

`normalize_url(url: str) -> str` — lowercase scheme/host, strip trailing slash, strip fragment, sort query params, resolve relative URLs against base. `is_same_domain(url: str, base: str) -> bool` — ensure sub-pages stay on the same domain.

### `utils/fallback.py`

`generate_fallback_plan(url: str) -> TestPlan` — generic test plan when structured output fails:

- Test 1: All navigation links return HTTP 200
- Test 2: All images have valid `src` and load
- Test 3: No JavaScript console errors
- Test 4: Page loads within 5 seconds
- Test 5: All forms have associated labels
- Test 6: Page has valid heading hierarchy

### `config.py`

Pydantic `BaseSettings` model with `model_validator` ensuring at least one LLM provider is configured. Load from YAML + env vars. Validate `max_depth ≥ 0`, `max_executors ≥ 1`, etc.

---

## 8. Storage State Propagation for Auth Flows

In `nodes/execute.py`, after each executor finishes but BEFORE closing the session:

- If the executor's test involved authentication (detected via test case metadata `requires_auth` or URL pattern matching login/auth paths):

  ```python
  storage = await session.export_storage_state()
  ```

- Store the latest auth-bearing `storage_state` in a node-scoped variable
- In `nodes/compile.py`, if any executor produced a `storage_state`, attach it to child `PlannerRequest` objects where `sub_page.requires_auth == True`

**Important constraint**: Use `storage_state` only (not `user_data_dir`) since browser-use warns about `user_data_dir` conflicts in parallel use.

---

## 9. Error Handling and Resilience

- **LLM rate limits**: Set `fallback_llm` on all browser-use Agents. e.g., if primary is Groq, fallback could be Ollama local
- **Executor crashes**: `return_exceptions=True` in `asyncio.gather`. Failed executors produce `ExecutorResult(status="error", error_detail=str(exception))`
- **Browser session leaks**: Wrap every session in `try/finally` with explicit `await session.close()`. Alternatively, explore if browser-use sessions support `async with`
- **Planner structured output failure**: 3-tier fallback (retry → regex extract → generic plan)
- **Total cost guard**: If `calculate_cost=True`, track cumulative $ across all agents. If approaching `max_total_cost`, stop enqueuing new planners and proceed to summarize with partial results
- **Interrupt timeout**: `async_input_with_timeout` uses `asyncio.wait_for` wrapping `run_in_executor(input)`. On timeout, returns configured default (decline)

---

## 10. Prompt Engineering

Create a `prompts/` directory or constants module with carefully crafted prompts:

- **Planner system prompt**: "You are a website quality assurance analyst. Analyze the page at {url} using only observation tools (navigate, scroll, extract, screenshot, evaluate JS). Produce a structured TestPlan with specific, actionable test cases. Each test case must have concrete steps an automated browser can follow and a clear expected outcome. Identify sub-pages that warrant deeper testing — prefer interactive pages (forms, carts, dashboards) over static content (about, privacy policy). {user_instructions}"

- **Executor system prompt**: "You are a browser automation test executor. Execute the following test case precisely: {test_case}. Navigate to {url}, follow the steps, and report whether the expected outcome matches reality. If the test fails, capture evidence (screenshot, extracted text). Report your findings as structured ExecutorResult."

- **Summarizer system prompt**: "You are a QA report writer. Given the raw test results from multiple page planners, produce a severity-classified executive report in Markdown. Classify each finding as Critical/High/Medium/Low/Info. Group by page URL. Start with an executive summary. For each failure, include reproduction steps."

---

## Verification

1. **Unit test**: Mock browser-use Agent to test LangGraph state transitions, dequeue logic, URL dedup, depth limiting
2. **Integration test**: Run against a local test site (e.g., `python -m http.server` serving a small multi-page HTML site) with `auto_approve` mode, verify Markdown report is generated with correct structure
3. **Interrupt test**: Run against any URL with `approval.mode = "interrupt"`, verify CLI prompts appear and decline/approve works correctly with `Command(resume=...)`
4. **Fallback test**: Configure planner LLM to a broken endpoint, verify generic fallback plan is used and executors still run
5. **Cost guard test**: Set `max_total_cost: 0.01`, verify pipeline stops early and produces partial report
6. **Manual smoke test**: Run against a real e-commerce site (e.g., demo.opencart.com) with depth 1, verify homepage + 1-2 sub-pages are tested and report is coherent

---

## Decisions

- **LangGraph over pure asyncio**: Chosen because `interrupt()` cleanly handles HITL, checkpointing enables resume-after-crash, and the state machine maps naturally to the FCFS queue pattern. The cost is one additional dependency and JSON-serializability constraint on state.
- **browser-use native LLM wrappers over LangChain wrappers**: browser-use v0.12.1 has its own `BaseChatModel` abstraction. Using `from browser_use import ChatOpenAI, ChatGroq, ChatOllama` is the supported path. NVIDIA and OpenRouter both work through `ChatOpenAI` with custom `base_url`.
- **Semaphore + stagger in execute node over LangGraph sub-graph parallelism**: LangGraph's `Send()` API could theoretically parallelize executor nodes, but browser-use agents are async-native and `asyncio.gather` with semaphore gives finer control over stagger delay and resource cleanup.
- **storage_state over user_data_dir for auth propagation**: browser-use explicitly warns about `user_data_dir` conflicts in parallel sessions. `storage_state` (cookies + localStorage JSON) is safe to share across sessions.
- **InMemorySaver for v1, SQLite recommended for production**: Keeps v1 simple with no external deps. Users can swap to `langgraph-checkpoint-sqlite` by changing one line in `builder.py`.
- **Markdown report over JSON**: Per user preference. The summarizer LLM writes directly in Markdown. Structured data (pass/fail counts, per-test results) is preserved in LangGraph state for programmatic access if needed later.

---

## Loopholes Identified and Mitigations

| # | Loophole | Severity | Mitigation |
|---|---|---|---|
| 1 | Read-only planner misses dynamic content (modals, lazy-loaded sections, SPA routes) | High | Give planner `evaluate` action (JS execution) + `scroll` to trigger lazy-load. Inspect DOM for route definitions. |
| 2 | No max depth = infinite recursion | High | `max_depth` config (default: 2). Queue rejects requests exceeding depth. |
| 3 | Duplicate URL crawling across planners | Medium | Global `visited_urls: set` checked at enqueue time. URLs normalized before comparison. |
| 4 | Structured output parse failure wastes entire planner run | Medium | 3-tier fallback: retry with fallback_llm → regex JSON extraction → generic test plan template. |
| 5 | N executors = N Chrome instances = memory explosion | Medium | Semaphore bounds concurrency (default: 4). `headless=True`. Immediate session close after executor finishes. Configurable `max_executors_per_planner`. |
| 6 | Stateful cross-planner flows (login→checkout) impossible | Medium | Export `storage_state` from auth executors. Propagate to child `PlannerRequest` where `requires_auth=True`. |
| 7 | Human-in-the-loop blocks entire pipeline if user unresponsive | Medium | `approval_timeout` (default: 120s) with configurable `default_on_timeout`. `auto_approve` mode for CI. |
| 8 | Target site rate limiting / bot detection | Medium | Stagger delay. Enable default extensions (uBlock, ClearURLs). Optional proxy rotation. Randomize viewport. Tune `wait_between_actions`. |
| 9 | Executor result format unstructured → unreliable report compilation | Medium | `ExecutorResult` Pydantic model via `output_model_schema` on every executor. |
| 10 | FCFS linear scaling (7 planners = 7× serial time) | Low | Accept for v1. Future: bounded parallel planners (e.g., 2 concurrent). Per-planner executor parallelism already provides speedup. |
| 11 | No cost/token budgeting | Low | `Agent(calculate_cost=True)` on all agents. Cumulative tracking in orchestrator. `max_total_cost` config halts pipeline with partial report. |
| 12 | Error in one executor crashes all others | Low | `asyncio.gather(*tasks, return_exceptions=True)`. Failed executors marked `status=error` in result. |