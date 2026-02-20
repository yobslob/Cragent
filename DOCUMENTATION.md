# 🧪 LLM-Powered Autonomous Website Testing Agent

> A multi-node, loop-driven agentic system that leverages Large Language Models and Playwright to autonomously plan, execute, and iteratively deepen website testing — without human intervention.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [What It Does](#2-what-it-does)
3. [Key Capabilities](#3-key-capabilities)
4. [Architecture](#4-architecture)
   - [High-Level Flow](#41-high-level-flow)
   - [Node Descriptions](#42-node-descriptions)
   - [The Replanning Loop](#43-the-replanning-loop)
   - [State Schema](#44-state-schema)
   - [Stopping Conditions](#45-stopping-conditions)
5. [Tooling](#5-tooling)
   - [Planner Tools](#51-planner-tools)
   - [Executor Tools](#52-executor-tools)
   - [Tool Reference Table](#53-tool-reference-table)
   - [Tool Consolidation Map](#54-tool-consolidation-map)
6. [Human-in-the-Loop (HITL) System](#6-human-in-the-loop-hitl-system)
   - [Conversational Planner Interface](#61-conversational-planner-interface)
   - [Mid-Run Clarifications via Graph Interrupts](#62-mid-run-clarifications-via-graph-interrupts)
   - [Credentials & Secrets Vault](#63-credentials--secrets-vault)
7. [Bot Defense System](#7-bot-defense-system)
   - [Layer 1: Passive Avoidance (Stealth Shield)](#71-layer-1-passive-avoidance-stealth-shield)
   - [Layer 2: Human Circuit Breaker (State Handoff)](#72-layer-2-human-circuit-breaker-state-handoff)
8. [Observability & Tracing](#8-observability--tracing)
   - [Why LangSmith](#81-why-langsmith)
   - [Integration](#82-integration)
   - [What You See](#83-what-you-see)
9. [Design Decisions & Rationale](#9-design-decisions--rationale)
   - [Why Not Reuse the Original 16 Browsing Tools](#91-why-not-reuse-the-original-16-browsing-tools)
   - [Headless-First Philosophy](#92-headless-first-philosophy)
   - [Accessibility Tree as Primary Observation](#93-accessibility-tree-as-primary-observation)
   - [Context Window Management](#94-context-window-management)
10. [Testing Scope & Strategy](#10-testing-scope--strategy)
    - [What Can Be Tested](#101-what-can-be-tested)
    - [What Cannot Be Tested](#102-what-cannot-be-tested)
    - [Testing Categories](#103-testing-categories)
11. [System Prompts](#11-system-prompts)
    - [Planner System Prompt](#111-planner-system-prompt)
    - [Executor System Prompt](#112-executor-system-prompt)
12. [Edge Cases & Failure Handling](#12-edge-cases--failure-handling)
13. [Technology Stack](#13-technology-stack)
14. [Future Considerations](#14-future-considerations)

---

## 1. Project Overview

This project is an **autonomous website testing agent** built on a **Planner-Executor loop architecture**. It takes a target URL (e.g., `amazon.in`, `amazon.in/cart`) as input and autonomously:

- Explores and understands the website's structure
- Generates a comprehensive suite of test cases
- Executes those tests by interacting with the live website through a browser
- Reports pass/fail results with detailed observations
- **Re-plans** and dives deeper into complex areas that need more thorough testing

The agent treats the website as a **black box** — it has no access to backend code, databases, or APIs. It operates purely as an end-user would, navigating pages, clicking elements, filling forms, and observing outcomes. The underlying browser automation is powered by **Playwright running in headless mode**, and the intelligent reasoning is driven by **LLMs** (compatible with both cloud APIs and local models via Ollama/vLLM).

The Executor uses a **lean 9-tool architecture** — 6 core tools that cover ~90% of testing scenarios plus 3 edge-case tools for specialized situations. This is a deliberate pruning of the original 16 human-simulation browsing tools from the open-source codebase, designed to reduce LLM decision fatigue, lower token usage, and eliminate rendering latency by shifting mechanical complexity into the backend code of each tool.

The system includes three cross-cutting concerns integrated with zero or negative token overhead:

- **Human-in-the-Loop (HITL)** — A conversational interface on the Planner for initial scoping, mid-run clarifications, and credential injection via LangGraph interrupts (not blocking tools).
- **Bot Defense** — A defense-in-depth strategy using `playwright-stealth` for passive avoidance and a State Handoff pattern for human CAPTCHA solving, both operating entirely outside the LLM's context.
- **Observability** — Full tool-level tracing via LangSmith, running as an async background thread with zero token overhead and zero latency impact.

---

## 2. What It Does

Given a URL and optional context about the site, the agent:

1. **Accepts user instructions** — Before the run starts, the user can chat with the Planner to specify scope (e.g., "Focus only on the checkout flow"), provide credentials, or give context. This is injected into the agent's starting state.
2. **Fetches the page's structural state** via the Accessibility Tree (A11y Tree) — a clean, hierarchical representation of all interactive elements on the page.
3. **Plans a batch of tests** — The Planner LLM analyzes the page structure and generates a prioritized list of test cases covering functionality, navigation, forms, links, and usability.
4. **Executes those tests in parallel** — Multiple Executor instances (each with their own isolated browser context) carry out the tests by interacting with the live website.
5. **Self-heals on failure** — If a test step fails (e.g., an element moved or loaded late), the Executor retries with alternative strategies before marking a hard failure.
6. **Handles bot defenses** — If a CAPTCHA or bot-stopper is encountered, the system suspends gracefully (zero tokens burned), hands off to a human solver, and resumes without losing state.
7. **Reports results** — Each Executor returns a structured result (Pass/Fail + observations).
8. **Evaluates and re-plans** — The Planner reviews all results, decides if deeper testing is needed for specific areas (e.g., "The checkout form is complex — generate 5 boundary-value tests"), and loops back for another round.
9. **Terminates** — When the configured depth limit is reached or all test areas are satisfactorily covered, the agent produces a final summary report.

---

## 3. Key Capabilities

| Capability | Description |
|---|---|
| **Generalized Testing** | Works on any general-purpose website (e-commerce, blogs, SaaS, news portals, etc.) without site-specific configuration. |
| **Autonomous Exploration** | Discovers pages, forms, and interactive elements on its own by reading the Accessibility Tree. |
| **Iterative Depth** | Starts with surface-level tests, then drills deeper into complex components across multiple planning rounds. |
| **Parallel Execution** | Spins up multiple isolated Executor instances to run tests concurrently, dramatically reducing total test time. |
| **Self-Healing** | Retries failed interactions with alternative locators/strategies before reporting a hard failure. |
| **Structured Reporting** | Produces machine-readable and human-readable test reports with pass/fail status, observations, and screenshots. |
| **Context-Aware Memory** | Maintains compressed state of past results across planning rounds to avoid redundant tests and inform deeper exploration. |
| **Black-Box Perspective** | Tests entirely from the user's perspective — no backend access, no source code, no database queries. |
| **Headless Execution** | Runs entirely in headless mode — no visible browser window — optimized for speed and CI/CD integration. |
| **Minimal Tool Surface** | Uses only 9 purpose-built tools instead of 16, reducing LLM decision paralysis, token consumption, and hallucination risk per reasoning step. |
| **Conversational Planner** | Supports pre-run chat for scoping, mid-run clarifications via graph interrupts, and secure credential injection — all without blocking tools or burning tokens. |
| **Bot-Defense Resilient** | Passively avoids detection via `playwright-stealth`; gracefully suspends and hands off to a human for CAPTCHAs with zero token waste. |
| **Full Observability** | Every tool call, token usage, and latency metric is traced via LangSmith in a zero-overhead async background thread. |

---

## 4. Architecture

### 4.1 High-Level Flow

```
    ┌──────────────────────────────────────────────────────────────┐
    │                        USER INTERFACE                        │
    │  Chat: "Test amazon.in, focus on checkout. Here are creds." │
    │  Credentials → Secrets Vault                                 │
    │  Scope/Instructions ��� AgentState.testing_instructions        │
    └──────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
                ┌──────────────────────────────────┐
                │        PLANNER NODE (LLM)        │
                │                                  │
                │  1. Fetch A11y Tree (tool call)  │
                │  2. Read past_results (if any)   │
                │  3. Read testing_instructions     │
                │  4. Generate test batch           │
                │  5. Route to Executors            │
                └──────────────┬──────────────────┘
                               │
                ┌──────────────┼──────────────────┐
                │              │                   │
                ▼              ▼                   ▼
        ┌─────────────┐ ┌─────────────┐   ┌─────────────┐
        │ EXECUTOR 1  │ │ EXECUTOR 2  │   │ EXECUTOR N  │
        │ (Isolated   │ │ (Isolated   │   │ (Isolated   │
        │  Browser    │ │  Browser    │ … │  Browser    │
        │  + Stealth) │ │  + Stealth) │   │  + Stealth) │
        └──────┬──────┘ └──────┬──────┘   └──────┬──────┘
               │               │                  │
               │  ┌────────────┴──────────────┐   │
               │  │ CAPTCHA? → State Handoff  │   │
               │  │ (Suspend → Human → Resume)│   │
               │  └───────────────────────────┘   │
               │               │                  │
               └───────────────┼──────────────────┘
                               │
                               ▼
                ┌──────────────────────────────────┐
                │    EVALUATOR / REPLANNER          │
                │    (Part of Planner Node)         │
                │                                  │
                │  • Aggregate results              │
                │  • Display results to user        │
                │  • Decide: go deeper or finish?   │
                └──────────────┬──────────────────┘
                               │
                      ┌────────┴────────┐
                      │                 │
                [DEEPER TESTING]   [SUFFICIENT]
                      │                 │
                      ▼                 ▼
                Loop back to      ┌──────────────┐
                PLANNER with      │  SYNTHESIZER  │
                new URL/focus     │  Final Report │
                                  └──────────────┘

    ════════════════════════════════════════════════════════════
    OBSERVABILITY LAYER (runs in background, zero token overhead)
    LangSmith traces every node, tool call, token count, latency
    ════════════════════════════════════════════════════════════
```

### 4.2 Node Descriptions

#### Node 1: Planner (The Strategist)

- **Role:** Generates, prioritizes, and manages test plans.
- **Tools:** `fetch_accessibility_tree(url)` — used to "see" the current page before generating tests.
- **Inputs:**
  - The target URL.
  - The A11y Tree snapshot of the current page.
  - `past_results` — a compressed log of all previously executed tests and their outcomes.
  - `testing_instructions` — user-provided scope and context from the pre-run chat.
  - `chat_history` — conversational memory for multi-turn interactions.
- **Outputs:** A structured JSON array of test cases, each containing a test ID, description, steps, and expected outcomes.
- **Behavior on Replan:**
  - Reads `past_results` to understand what has been tested and what failed.
  - If a new URL is targeted (e.g., navigating from `amazon.in` to `amazon.in/cart`), it calls its A11y tool to fetch the new page state.
  - Generates a fresh batch of focused test cases for the new target area.
  - Displays the summary of previous round results before issuing the new plan.
- **Behavior on Blocker (needs user info):**
  - Sets `status = "AWAITING_USER_INPUT"` and `pending_message` describing what it needs.
  - LangGraph suspends the graph (checkpoint saved, compute freed).
  - User responds via chat; response is injected into state. Graph resumes.

#### Node 2: Executor (The Doer)

- **Role:** Receives a single test case and executes it step-by-step using the lean 9-tool browser automation toolkit.
- **Tools:** 6 core tools + 3 edge-case tools (see [Section 5.2](#52-executor-tools)).
- **Browser Setup:** Each instance launches with `playwright-stealth` applied at the context level for passive bot avoidance.
- **Inputs:** A single test case object from the Planner (ID, description, steps, expected outcome).
- **Outputs:** A structured test result: `{ test_id, status: PASS|FAIL|BLOCKED_CAPTCHA, observations, retry_count }`.
- **Self-Healing Behavior:** If a tool call fails (e.g., `interact_with_element` returns an error because the element is detached), the Executor:
  1. Re-fetches the page state via `get_page_state`.
  2. Attempts to locate the target element using the fresh element IDs from the updated A11y tree.
  3. Retries up to `MAX_RETRIES` (configurable, default: 3).
  4. If all retries fail, reports a hard `FAIL` with the error log.
- **Bot Defense Behavior:** If the Executor detects a CAPTCHA (e.g., reCAPTCHA iframe or specific text in the A11y tree), it immediately returns `status="BLOCKED_CAPTCHA"` instead of burning retries. This triggers the State Handoff flow (see [Section 7.2](#72-layer-2-human-circuit-breaker-state-handoff)).
- **Isolation:** Each Executor instance runs in its **own Playwright BrowserContext**. This prevents race conditions where one executor's actions (e.g., adding an item to cart) corrupt another executor's test state.

#### Node 3: Evaluator / Replanner (The Critic)

- **Role:** Acts as a strategic checkpoint after each batch of tests completes.
- **Implementation:** This is logically part of the Planner node, activated after all Executors return.
- **Inputs:** The aggregated `past_results` array from the just-completed batch.
- **Decision Logic:**
  - **Route to Planner (Replan):** If complex components were discovered (multi-step forms, search with auto-suggest, payment flows), or if failures suggest an unexplored user flow, or if the current `depth < MAX_DEPTH`.
  - **Route to Synthesizer (Finish):** If `depth >= MAX_DEPTH`, or all critical paths have been tested with satisfactory coverage, or the Planner determines no further actionable testing surfaces exist.

#### Node 4: Synthesizer (The Reporter)

- **Role:** Generates the final, comprehensive test report.
- **Inputs:** The complete `past_results` array across all planning rounds.
- **Outputs:** A structured Markdown report including:
  - Overall health score.
  - Tests passed vs. failed vs. blocked.
  - Critical issues discovered.
  - Areas tested and their depth.
  - Retry/self-healing logs for transparency.

### 4.3 The Replanning Loop

The core innovation is that the architecture is **not linear**. It is a **cyclic graph** where the Planner and Executors continuously interact until a termination condition is met.

```
Round 1: Planner scans amazon.in → generates 5 surface-level tests → Executors run them
         → Results: All pass, but "cart page" and "search bar" flagged as complex

Round 2: Planner fetches A11y tree for amazon.in/cart → generates 5 cart-specific tests
         → Results: 4 pass, 1 fail (coupon input doesn't validate)

Round 3: Planner fetches A11y tree for amazon.in search → generates 5 search tests
         → Results: All pass

Round 4: Depth limit reached → Synthesizer generates final report
```

### 4.4 State Schema

A shared state object is passed between nodes throughout the execution lifecycle:

```python
class AgentState(TypedDict):
    # Core Fields
    target_url: str                    # The original URL provided by the user
    current_url: str                   # The active page being tested in this round
    a11y_tree: str                     # Latest Accessibility Tree snapshot (JSON/YAML)
    tasks_to_execute: list[TestCase]   # Current batch of test cases
    past_results: list[TestResult]     # Append-only log of all completed tests (compressed)
    current_depth: int                 # How many planning rounds have occurred
    max_depth: int                     # Configurable depth limit (default: 5)
    max_retries: int                   # Per-test retry limit (default: 3)
    status: str                        # "planning" | "executing" | "evaluating"
                                       # | "awaiting_user_input" | "blocked_captcha" | "done"

    # Human-in-the-Loop Fields
    testing_instructions: str          # User-provided scope/context from pre-run chat
    chat_history: list[dict]           # Conversational memory [{role, content}, ...]
    pending_message: str               # Message to display when awaiting user input
    user_provided_context: str         # Latest user response injected after interrupt

    # Bot Defense Fields
    storage_state_path: str            # Path to storage_state.json for State Handoff
    blocked_url: str                   # URL where CAPTCHA was encountered

    # Credentials
    credentials: dict                  # Pre-loaded secrets vault: {domain: {user, pass}}
```

**Test Case Schema:**

```json
{
  "test_id": "TC-001",
  "description": "Verify that the search bar accepts input and returns results",
  "target_url": "https://amazon.in",
  "steps": [
    "Navigate to https://amazon.in",
    "Get page state to identify the search input element",
    "Interact with [search-input]: type 'wireless headphones'",
    "Interact with [search-button]: click",
    "Wait for condition: network_idle",
    "Get page state to verify results loaded",
    "Verify that search results page displays relevant products"
  ],
  "expected_outcome": "Search results page displays products matching 'wireless headphones'"
}
```

**Test Result Schema (Compressed):**

```json
{
  "test_id": "TC-001",
  "status": "PASS",
  "tested_surface": "search_bar",
  "target_url": "https://amazon.in",
  "observations": "Auto-suggest dropdown appeared after 2 characters. Results loaded in ~1.2s.",
  "discovered_elements": ["auto_suggest_dropdown", "filter_sidebar", "sort_dropdown"],
  "retry_count": 0
}
```

### 4.5 Stopping Conditions

| Condition | Scope | Trigger |
|---|---|---|
| **Depth limit reached** | Whole test run | `current_depth >= max_depth` |
| **Max retries exhausted** | Single test case | A test step fails `max_retries` times consecutively |
| **Planner deems coverage sufficient** | Whole test run | The Planner/Evaluator decides no further actionable testing surfaces remain |
| **Critical failure** | Whole test run | The target site is unreachable, returns a server error, or the browser context crashes unrecoverably |

---

## 5. Tooling

### 5.1 Planner Tools

The Planner has access to **one tool** — this is intentional to keep its role strictly strategic:

| Tool | Parameters | Description |
|---|---|---|
| `fetch_accessibility_tree` | `url: string` | Navigates to the given URL in a lightweight headless context and returns the Accessibility Tree (A11y Tree) — a clean, hierarchical JSON/YAML representation of all interactive elements (buttons, links, inputs, dropdowns) stripped of styling and layout noise. This is how the Planner "sees" a new page before generating tests. |

### 5.2 Executor Tools

The Executor uses a **lean 9-tool architecture**: 6 core tools that handle ~90% of all testing scenarios, plus 3 edge-case tools for specialized situations. This is a deliberate reduction from the original 16 human-simulation tools — the complexity of scrolling, tab management, and per-action-type tool selection is pushed into the backend code of each tool, freeing the LLM to focus purely on test logic.

#### Core Tools (6)

| # | Tool | Parameters | Input | Processing | Output |
|---|---|---|---|---|---|
| 1 | `navigate_to` | `url: string` | A fully qualified URL (e.g., `https://staging-app.com/login`). | Playwright calls its native `goto` method and waits for the network to reach an idle state. This ensures the initial HTML and essential assets are fully loaded before the agent takes its next step. | A success string (e.g., `"Navigated to URL successfully"`) or an error message if the page fails to load or times out. |
| 2 | `get_page_state` | *(none)*, or optional `focus_element_id: string` to narrow scope | A trigger command from the agent. | Executes a script within the page context that traverses the Accessibility (A11y) Tree or a pruned DOM. It assigns a unique, temporary identifier (e.g., `[node-12]`) to every interactive element (buttons, links, inputs) and strips out all styling, SVGs, and layout fluff. Playwright can access all elements regardless of viewport position, so **no scrolling is needed**. | A compact JSON or Markdown representation of the page's interactive elements and their current text/values, each tagged with a unique node ID. |
| 3 | `interact_with_element` | `element_id: string`, `action_type: enum(click, type, select, hover)`, `input_value: string` (optional) | The target element's assigned ID (retrieved from `get_page_state`), the type of action to perform, and any required payload (like the text to type into an input field). | The backend maps the custom ID (e.g., `[node-12]`) back to its actual Playwright locator. It then routes the request: if `action_type` is `type`, it executes `locator.fill(input_value)`; if `click`, it executes `locator.click()`; if `select`, it executes `locator.selectOption(input_value)`. This single tool **replaces** the old `click_element_tool`, `input_text_tool`, `send_keys_tool`, `get_dropdown_options_tool`, and `select_dropdown_option_tool`. | A confirmation string indicating the action was successfully performed, or an error if the element is disabled, hidden, or detached from the DOM. |
| 4 | `navigate_back` | *(none)* | A trigger command from the agent. | Calls the browser's native `goBack()` method and waits for the previous state to resolve. | Success confirmation or an error if there is no history to navigate back to. |
| 5 | `report_test_result` | `status: enum(PASS, FAIL)`, `observations: string` | The final verdict (`PASS` or `FAIL`) and a brief explanation of why the agent made that decision based on the DOM state. | The backend intercepts this payload and formats it into the test reporting system (like JUnit XML, a database log, or a console output). | A string acknowledging that the report was successfully saved. |
| 6 | `done_tool` | *(none)* | A trigger command from the agent. | Signals the overarching orchestrator to end the current run, tear down the browser context, and clean up memory. In graph-based execution architectures, this is the crucial signal that prevents the LLM from getting stuck in an infinite loop. | Execution terminates; no output is returned to the LLM. |

#### Edge-Case Tools (3)

| # | Tool | Parameters | Input | Processing | Output |
|---|---|---|---|---|---|
| 7 | `upload_file` | `element_id: string`, `file_path: string` | The ID of the `<input type="file">` element and the path to a mock file stored locally on the server running the test. | Locates the input element and uses Playwright's `locator.setInputFiles(file_path)` to attach the file programmatically. This **bypasses the OS-level file picker dialog** which headless browsers and LLMs cannot interact with. | A success confirmation that the file was attached to the input. |
| 8 | `evaluate_javascript` | `script: string` | A valid, self-contained JavaScript snippet or function written by the LLM. | The engine passes the string to `page.evaluate()`, executes it within the live browser context, and serializes the return value back to the backend. Useful for checking hidden application state like `localStorage`, `sessionStorage`, cookies, tokens, or Redux/global JS state. | The evaluated result of the script (returned as a string, number, or JSON object), or a clean syntax error if the script fails. |
| 9 | `wait_for_condition` | `condition_type: enum(network_idle, element_visible, timeout)`, `value: string or int` (optional) | The type of condition to wait for and, if applicable, the specific element ID or time duration (in milliseconds). | Translates the request into native Playwright wait commands (e.g., `waitForLoadState('networkidle')` or `waitForSelector()`). It suspends execution until the condition is true or the internal timeout is reached. Stabilizes tests that deal with async operations, slow DB writes, or delayed animations where `get_page_state` might fire too early. | A confirmation that the condition was met (allowing the agent to proceed), or a timeout error prompting the LLM to rethink its strategy. |

### 5.3 Tool Reference Table

```
┌──────────────────────────┬──────────────────────────────────────────────┐
│      PLANNER TOOLS       │          EXECUTOR TOOLS                      │
├──────────────────────────┼──────────────────────────────────────────────┤
│                          │  Core Tools (6)                              │
│  fetch_accessibility_    │  ├── navigate_to(url)                        │
│  tree(url)               │  ├── get_page_state()                        │
│                          │  ├── interact_with_element(id, action, val)  │
│                          │  ├── navigate_back()                         │
│                          │  ├── report_test_result(status, obs)         │
│                          │  └── done_tool()                             │
│                          │                                              │
│                          │  Edge-Case Tools (3)                         │
│                          │  ├── upload_file(element_id, file_path)      │
│                          │  ├── evaluate_javascript(script)             │
│                          │  └── wait_for_condition(type, value)         │
└──────────────────────────┴──────────────────────────────────��───────────┘
```

### 5.4 Tool Consolidation Map

This table shows how the original 16 human-simulation tools from the open-source browsing codebase map onto the lean 9-tool architecture:

| Original Tool (Dropped) | Replaced By | How |
|---|---|---|
| `go_to_url_tool` | `navigate_to` | Direct 1:1 replacement. |
| `go_back_tool` | `navigate_back` | Direct 1:1 replacement. |
| `click_element_tool` | `interact_with_element` | Pass `action_type="click"`. |
| `input_text_tool` | `interact_with_element` | Pass `action_type="type"`, `input_value="..."`. |
| `send_keys_tool` | `interact_with_element` | Pass `action_type="type"` with key commands, or handled via `evaluate_javascript` for complex key combos. |
| `get_dropdown_options_tool` | `get_page_state` | The A11y tree already lists all dropdown options with their node IDs. |
| `select_dropdown_option_tool` | `interact_with_element` | Pass `action_type="select"`, `input_value="Option B"`. |
| `extract_content_tool` | `get_page_state` | Returns the A11y tree / pruned DOM instead of raw text/markdown. More structured, fewer tokens. |
| `scroll_down_tool` | **Eliminated** | Playwright interacts with off-screen elements directly via the DOM. No viewport dependency. |
| `scroll_up_tool` | **Eliminated** | Same as above. |
| `scroll_to_text_tool` | **Eliminated** | Same as above. `get_page_state` captures all elements regardless of scroll position. |
| `switch_tab_tool` | **Eliminated** | Backend intercepts new-tab URLs and loads them in the current headless context automatically. |
| `open_tab_tool` | **Eliminated** | Same as above. Sequential single-context navigation replaces tab management. |
| `search_google_tool` | `navigate_to` | Navigate directly to `https://www.google.com/search?q=...` if needed. |
| `report_test_result` | `report_test_result` | Kept as-is. |
| `done_tool` | `done_tool` | Kept as-is. |

---

## 6. Human-in-the-Loop (HITL) System

The agent supports human interaction at strategic points **without using a blocking `ask_user()` tool**. A synchronous tool that waits for user input is an anti-pattern — it blocks the execution thread, risks hitting LLM API timeout limits, and pollutes the context window with conversational back-and-forth.

Instead, the system uses **LangGraph Interrupts** (suspend/resume with state injection), which are zero-cost when the agent is paused.

### 6.1 Conversational Planner Interface

**Before the run starts**, the user interacts with the system via a chat interface:

| User Input | How It's Handled |
|---|---|
| Test scope (e.g., "Only test the checkout flow") | Injected into `AgentState.testing_instructions`. The Planner's system prompt respects this: *"Prioritize your test generation based on these user instructions: {testing_instructions}."* |
| Login credentials | Stored in the **Secrets Vault** (`AgentState.credentials`), never passed through the Planner's reasoning logs. |
| General context (e.g., "This is a staging environment, ignore SSL errors") | Injected into `AgentState.testing_instructions`. |

This is **not a tool call**. The user provides this information in the UI before the graph starts, and it's passed directly into the initial state.

### 6.2 Mid-Run Clarifications via Graph Interrupts

When the Planner or Executor encounters a blocker that requires human input (e.g., a 2FA code, an unexpected login wall, or ambiguity about what to test next):

```
1. DETECTION:
   Agent detects blocker (e.g., 2FA prompt in A11y tree).
   Sets: status = "AWAITING_USER_INPUT"
         pending_message = "I hit a 2FA screen. What is the verification code?"

2. SUSPENSION:
   LangGraph detects the status and triggers a Graph Interrupt.
   Full state checkpoint is saved (memory, past_results, browser state).
   Compute resources are freed. Zero tokens burned while waiting.

3. CHAT:
   Frontend displays pending_message to the user.
   User types the answer (e.g., "The code is 482910").

4. INJECTION:
   User response is injected into AgentState.user_provided_context.
   Status is set back to "planning" or "executing".

5. RESUMPTION:
   Graph resumes from the exact checkpoint.
   Agent reads user_provided_context and continues the test.
```

### 6.3 Credentials & Secrets Vault

Standard passwords and API keys should **not** be requested via mid-run chat. They are pre-loaded:

1. **Pre-load:** Before the test begins, the user provides credentials in a secure form in the UI (not the chat).
2. **State Injection:** Passed to the agent as a secure dictionary in `AgentState.credentials`:

   ```json
   {
     "amazon.in": {"username": "test_user", "password": "secure123"},
     "staging.myapp.com": {"username": "admin", "password": "admin456"}
   }
   ```

3. **Executor Access:** The Executor uses `evaluate_javascript` or `interact_with_element` to fill login forms, pulling credentials from the vault. Passwords never appear in the Planner's reasoning logs or test plan outputs.

---

## 7. Bot Defense System

Bot-stopping mechanisms (CAPTCHAs, fingerprint checks, behavioral analysis) are a critical obstacle for automated testing. The system uses a **Defense-in-Depth** approach: deflect first, detect second, handoff as a last resort.

**Overhead Impact Summary:**

| Layer | Solution | Token Overhead | Latency Impact |
|---|---|---|---|
| Passive Avoidance | `playwright-stealth` | **None** (backend only) | **None** |
| Human Circuit Breaker | LangGraph Interrupt + State Handoff | **Negative** (saves tokens by pausing immediately) | Depends on human response time |

### 7.1 Layer 1: Passive Avoidance (Stealth Shield)

Before involving a human, minimize how often the agent looks like a bot.

**Tool:** `playwright-stealth` (Python port of the JS library).

**Integration:** Zero-token overhead. Applied at the browser context level in backend code, not via the LLM. The agent has no idea stealth patches are active.

**Effect:** Patches the "headless" leaks that cheap bot detectors use — `navigator.webdriver` flags, Chrome automation indicators, missing plugins, etc.

**Implementation:**

```python
from playwright_stealth import stealth_async

# Inside Executor Node browser setup
context = await browser.new_context()
page = await context.new_page()
await stealth_async(page)  # Patches bot signals invisibly
```

### 7.2 Layer 2: Human Circuit Breaker (State Handoff)

When stealth isn't enough and a CAPTCHA appears, the system does **not** try to solve it with the LLM. It does **not** burn retries or tokens reasoning about an unsolvable puzzle. Instead, it performs a **State Handoff**.

**Why not switch to "headed" mode on the fly?**
Toggling a running headless browser to headed mode is technically unstable and often crashes the driver. The robust solution is to export the browser's brain (cookies/storage), let a human solve the puzzle in a separate instance, and import the brain back.

**The Workflow:**

```
1. DETECTION (Executor Node):
   Executor detects CAPTCHA (reCAPTCHA iframe, hCaptcha text, etc. in A11y tree).
   Immediately returns: status = "BLOCKED_CAPTCHA"
   Does NOT try to solve it. Does NOT burn retries.

2. SUSPENSION (LangGraph Checkpoint):
   Graph detects BLOCKED_CAPTCHA status and triggers a LangGraph Interrupt.
   System saves current storage_state.json (cookies, localStorage, session tokens).
   Graph pauses completely. Zero tokens are burned.

3. HUMAN SOLVER (Separate Utility):
   User runs a lightweight local script: python solve_captcha.py
   Script launches a HEADED Chrome instance (visible browser).
   Injects the storage_state.json from the bot.
   Navigates to the blocked URL.
   User solves the CAPTCHA manually.
   User presses Enter in terminal.
   Script saves the NEW storage_state.json (containing "I am human" cookies).

4. RESUMPTION:
   User sends "resume" command to the LangGraph agent.
   Executor restarts the blocked step.
   Loads the new storage_state.json.
   Reloads the page — website sees valid cookies and lets the agent pass.
   Testing continues from where it left off with full state preserved.
```

**Why this is efficient:**

- **Zero Token Waste:** The LLM stops immediately upon CAPTCHA detection.
- **Zero Context Loss:** LangGraph checkpoints preserve the full memory and past_results.
- **Stability:** The production headless driver is never at risk — the human solves in a completely separate browser instance.

---

## 8. Observability & Tracing

### 8.1 Why LangSmith

Since the project uses LangGraph for orchestration, **LangSmith** is the recommended observability solution for the following reasons:

| Factor | LangSmith | LangFuse |
|---|---|---|
| **LangGraph Integration** | Native — renders executions as a flowchart (Planner → Executor → Tool calls). | Treats traces as linear lists, harder to debug loop-based agents. |
| **Token Overhead** | **Zero.** Works via an async background callback in a separate thread. Never touches the prompt context. The LLM has no idea it's being watched. | Similar async model, but requires explicit decorator/API calls for custom pipelines. |
| **Latency Impact** | **None.** Uses non-blocking HTTP requests. Does not slow down parallel Executors. | Comparable, but requires more manual tuning for custom workloads. |
| **Setup Effort** | 3 environment variables. No code changes. | Requires wrapper setup and schema design for non-standard pipelines. |
| **Self-Hosting** | Enterprise-only. | Full OSS parity, self-hostable. Better for data sovereignty. |

**Decision:** LangSmith for this project due to native LangGraph support and true zero-config setup. If data sovereignty or self-hosting becomes a requirement, LangFuse is the migration path.

### 8.2 Integration

No code changes required. Only environment variables:

```bash
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_ENDPOINT="https://api.smith.langchain.com"
export LANGCHAIN_API_KEY="<your-api-key>"
export LANGCHAIN_PROJECT="autonomous-testing-agent"
```

### 8.3 What You See

| Trace Data | Description |
|---|---|
| **Tool Inputs/Outputs** | Click on any `interact_with_element` node in the trace and see the exact `element_id` the LLM selected, the `action_type`, and the result. |
| **Token Usage per Node** | How many tokens the Planner used vs. each Executor instance. Identifies where to optimize costs. |
| **Latency Waterfalls** | Visual breakdown of time spent in each tool call. Reveals if `fetch_accessibility_tree` or `wait_for_condition` is the bottleneck in the loop. |
| **Graph Flow Visualization** | LangGraph-native flowchart view: Planner → Executor 1/2/3 → Evaluator → Planner (loop). See the full cyclic execution. |
| **Error Traces** | Full stack traces for failed tool calls, with the exact state at the time of failure. |
| **Interrupt Events** | When the graph suspended for HITL input or CAPTCHA handoff, and how long it was paused. |

---

## 9. Design Decisions & Rationale

### 9.1 Why Not Reuse the Original 16 Browsing Tools

The original open-source browsing codebase provides 16 tools designed for **human-like agentic browsing** — where a user watches the agent work on a visible browser instance. While functionally complete, these tools introduce significant overhead for an automated testing pipeline:

| Concern | Impact |
|---|---|
| **Visible browser rendering** | Unnecessary compute for layout painting, GPU compositing, and screen updates. Testing does not need a visible window. |
| **Too many tools = decision paralysis** | Every time the LLM must choose between 16 tools, it burns tokens on reasoning and increases the chance of picking the wrong tool. With 9 tools (and really only 6 for most scenarios), the decision space shrinks dramatically. |
| **Scroll tools are wasteful** | Headless Playwright can interact with any DOM element regardless of viewport position. The LLM never needs to reason about "is this in the viewport?" — that's a visual-simulation artifact. |
| **Tab tools add cognitive load** | Tab management forces the LLM to track multiple contexts. The backend can automatically intercept new-tab URLs and load them in the current context, eliminating this complexity entirely. |
| **Separate click/type/select/keys = redundant decisions** | Four tools that all do "interact with an element" force the LLM to make an extra routing decision. `interact_with_element` consolidates them into one call with an `action_type` parameter, and the backend handles the routing. |
| **No testing-specific primitives** | The original 16 lack `wait_for_condition`, `upload_file`, and `evaluate_javascript` — tools that are critical for robust test automation against real-world sites. |

**Decision:** Build a lean 9-tool architecture (6 core + 3 edge-case) that pushes mechanical complexity into the backend and gives the LLM a clean, minimal decision surface. The Planner gets its own dedicated A11y Tree extraction tool rather than relying on the Executor's observation tools.

### 9.2 Headless-First Philosophy

All browser instances run in **headless mode** (`chromium.launch({ headless: true })`). This provides:

- **~40-60% faster page loads** (no rendering pipeline).
- **Lower memory footprint** (no GPU compositing).
- **CI/CD compatibility** (runs on servers without display).
- **No visual dependency** — the LLM reasons about DOM structure, not pixels.
- **Scroll tools become unnecessary** — Playwright can target any element in the DOM directly, regardless of its viewport position.

### 9.3 Accessibility Tree as Primary Observation

Instead of feeding raw HTML (which bloats the context window with `<div>`, `<style>`, `<script>` noise) or plain text (which loses structural context), both the Planner (via `fetch_accessibility_tree`) and the Executor (via `get_page_state`) use the **Accessibility Tree** — extracted via Playwright's `page.accessibility.snapshot()`.

**Why this matters:**

```
Raw HTML:          ~50,000-200,000 tokens for a complex page (unusable)
Plain Text:        ~2,000-10,000 tokens (loses structure)
A11y Tree:         ~500-3,000 tokens (clean, hierarchical, interactive-element-focused)
```

The A11y Tree provides:

- **Role** of each element (button, link, textbox, heading).
- **Name/label** of each element.
- **Current value** (for inputs).
- **Hierarchical nesting** (which elements are inside which containers).
- **Unique temporary IDs** (e.g., `[node-12]`) assigned by `get_page_state` for direct targeting.
- **No styling, no scripts, no layout divs.**

This is the optimal representation for an LLM to reason about what actions are available on a page. The LLM reads `[node-5] button "Add to Cart"` and simply outputs `interact_with_element("[node-5]", "click")` — no guessing, no hallucinated selectors.

### 9.4 Context Window Management

Because the agent loops multiple times, context accumulates. Without management, the LLM prompt will overflow within 2-3 rounds.

**Strategy: Compressed State Passing**

- **DO NOT** pass raw Playwright execution traces, stack dumps, or full HTML to the Planner.
- **DO** pass compressed test result summaries (see [State Schema](#44-state-schema)).
- Each test result is limited to: `test_id`, `status`, `tested_surface`, `observations` (1-2 sentences), and `discovered_elements`.
- When `past_results` exceeds a token threshold, the oldest round's results are summarized into a single aggregate entry (e.g., "Round 1: 5/5 passed on homepage surface-level checks").

---

## 10. Testing Scope & Strategy

### 10.1 What Can Be Tested

Given the black-box, headless browser approach with the lean 9-tool architecture, the agent can test:

| Area | Examples | Primary Tools Used |
|---|---|---|
| **Navigation & Routing** | Internal links work, back button preserves state, breadcrumbs are accurate, 404 pages are handled. | `navigate_to`, `navigate_back`, `get_page_state` |
| **Search Functionality** | Search returns relevant results, handles empty queries, special characters, auto-suggest works. | `interact_with_element(type)`, `interact_with_element(click)`, `get_page_state` |
| **Forms & Input Validation** | Required fields enforce validation, email/phone formats are checked, password rules are enforced, form submission works. | `interact_with_element(type)`, `interact_with_element(click)`, `get_page_state` |
| **Authentication Flows** | Login with valid/invalid credentials, signup flow, password reset link exists, logout works. | `navigate_to`, `interact_with_element`, `get_page_state`, `evaluate_javascript` (for token checks) |
| **E-Commerce Flows** | Add to cart, remove from cart, update quantity, proceed to checkout, apply coupon code. | `interact_with_element(click, type, select)`, `navigate_to`, `get_page_state` |
| **Dropdown & Select Menus** | All options are present, selection updates the page, multi-select behavior. | `get_page_state` (lists options), `interact_with_element(select)` |
| **Dynamic / Async Content** | Content loads after API calls, loading spinners resolve, deferred content appears. | `wait_for_condition`, `get_page_state` |
| **Cross-Page Consistency** | Headers/footers are consistent, navigation menus are uniform, branding elements persist. | `navigate_to`, `get_page_state` (across multiple pages) |
| **Error Handling** | Graceful handling of invalid URLs, server errors, empty states. | `navigate_to`, `get_page_state` |
| **Keyboard Accessibility** | Tab navigation order, Enter to submit, Escape to close modals. | `interact_with_element(type)` with key commands, `evaluate_javascript` |
| **Link Integrity** | External links resolve correctly, no dead links on critical paths. | `navigate_to`, `get_page_state` |
| **Content Verification** | Page titles are correct, headings are hierarchical, critical content is present. | `get_page_state`, `evaluate_javascript` |
| **File Upload Flows** | Upload forms accept files, validation on file type/size works. | `upload_file` |
| **Hidden State Assertions** | Tokens in localStorage, cookies set after login, session state. | `evaluate_javascript` |

### 10.2 What Cannot Be Tested

| Limitation | Reason |
|---|---|
| **Backend logic / API correctness** | No access to server-side code, databases, or API endpoints. |
| **Visual / pixel-perfect design** | The agent reads DOM structure, not screenshots (no multimodal vision in this version). |
| **Performance benchmarks** | No access to Lighthouse, WebVitals, or network timing APIs (partial coverage possible via `evaluate_javascript`). |
| **Security penetration testing** | While basic input injection can be attempted, the agent lacks specialized security tooling. |

### 10.3 Testing Categories

The Planner organizes tests into these categories, prioritized by criticality:

```
Priority 1 (Critical Path):
├── Core navigation (homepage → key pages)
├── Primary user flows (search → product → cart → checkout)
└── Authentication (login, logout)

Priority 2 (Functional):
├── Form validation (all input types)
├── Dropdown/select behavior
├── Error states and edge cases
└── Search functionality depth

Priority 3 (Structural):
├── Link integrity (internal + external)
├── Cross-page consistency (header, footer, nav)
├── Content presence and hierarchy
└── Dynamic/async content loading

Priority 4 (Accessibility & UX):
├── Keyboard navigation
├── ARIA label presence
├── Tab order logic
└── Focus management
```

---

## 11. System Prompts

### 11.1 Planner System Prompt

```text
You are the PLANNER — the strategic intelligence of an autonomous website testing agent.

═══════════════════════════════════════════════════════════
ROLE & IDENTITY
═══════════════════════════════════════════════════════════

You are a senior QA architect. You do NOT interact with the website directly. You analyze
the website's structure and generate precise, actionable test plans for your team of
Executor agents to carry out. You think in terms of user journeys, edge cases, and risk.

═══════════════════════════════════════════════════════════
YOUR TOOL
════════════════════════════════════════════════════════��══

You have access to ONE tool:

  fetch_accessibility_tree(url: string) → string

This tool navigates to the given URL and returns the Accessibility Tree (A11y Tree) —
a hierarchical representation of every interactive element on the page (buttons, links,
inputs, headings, dropdowns) with their roles, names, and values. Use this to "see" any
page before generating tests.

ALWAYS call this tool:
  - At the start of every planning round.
  - When the Evaluator routes you to a new URL for deeper testing.
  - When you need to understand a page you haven't seen before.

═══════════════════════════════════════════════════════════
INPUT YOU RECEIVE
═══════════════════════════════════════════════════════════

Each time you are activated, you receive a state object containing:

  target_url:            The original URL provided by the user.
  current_url:           The URL you should focus on for this round.
  testing_instructions:  User-provided scope and context (e.g., "Focus on checkout").
                         ALWAYS respect these instructions when generating tests.
  past_results:          An array of compressed test results from all previous rounds.
                         Each entry contains: test_id, status, tested_surface,
                         observations, discovered_elements, retry_count.
  current_depth:         How many planning rounds have occurred so far.
  max_depth:             The maximum allowed depth (stop when current_depth >= max_depth).
  credentials:           Available (do NOT log or display these — the Executor retrieves
                         them securely from the Secrets Vault when needed).

═══════════════════════════════════════════════════════════
YOUR RESPONSIBILITIES
═══════════════════════════════════════════════════════════

1. OBSERVE: Call fetch_accessibility_tree(current_url) to get the page structure.

2. REVIEW HISTORY: If past_results is non-empty, analyze it:
   - What surfaces have already been tested?
   - What passed? What failed?
   - What new elements were discovered that need deeper testing?
   - Were any tests BLOCKED_CAPTCHA? (Skip those surfaces or note for user.)
   - Present a brief summary of the previous round's results before proceeding.

3. RESPECT USER INSTRUCTIONS: If testing_instructions is non-empty, constrain your
   test generation to match the user's stated scope. Do not test areas the user
   explicitly excluded.

4. GENERATE TESTS: Produce a JSON array of 3-7 test cases. Each test case must include:
   {
     "test_id":          "TC-XXX",
     "description":      "Clear, one-line description of what is being tested",
     "category":         "navigation|forms|search|auth|e-commerce|accessibility|content",
     "priority":         1-4 (1 = critical path, 4 = nice-to-have),
     "target_url":       "The specific URL where this test begins",
     "steps":            ["Step 1: ...", "Step 2: ...", ...],
     "expected_outcome": "What the Executor should observe if the test passes",
     "failure_criteria":  "What constitutes a failure"
   }

5. PRIORITIZE: Order tests by priority. Critical user paths first, edge cases later.

6. AVOID REDUNDANCY: Never generate a test that overlaps with a PASS in past_results
   unless there is reason to believe the state has changed.

7. REQUEST INFO IF NEEDED: If you encounter a situation where you cannot proceed
   without user input (e.g., you see a login form but no credentials are available
   in the vault), set status = "AWAITING_USER_INPUT" with a clear pending_message.
   Do NOT guess credentials or skip auth flows silently.

═══════════════════════════════════════════════════════════
TEST GENERATION STRATEGY
═══════════════════════════════════════════════════════════

Apply these principles when generating test cases:

BREADTH FIRST, THEN DEPTH:
  Round 1: Surface-level tests across the main page (navigation, key links, search,
           primary CTAs). Identify complex components for future rounds.
  Round 2+: Dive into specific components flagged as complex or failed.

THINK LIKE A USER, TEST LIKE AN ENGINEER:
  - What would a first-time visitor do? (Happy path)
  - What would a confused user do? (Edge cases)
  - What would a malicious user do? (Boundary values, special characters)

CATEGORY COVERAGE: Ensure each batch covers at least 2 different testing categories
(navigation, forms, search, content, accessibility) unless the round is specifically
focused on one deep-dive area.

THE EXECUTOR'S CAPABILITIES:
  The Executor has access to exactly 9 tools. Write steps that map to these tools:

  Core Tools:
  - navigate_to(url)                       → Navigate to a URL
  - get_page_state()                       → Get the A11y tree with element IDs
  - interact_with_element(id, action, val) → Click, type, select, or hover
  - navigate_back()                        → Go back in browser history
  - report_test_result(status, obs)        → Report PASS/FAIL
  - done_tool()                            → End execution

  Edge-Case Tools (use only when needed):
  - upload_file(element_id, file_path)     → Attach a file to an upload input
  - evaluate_javascript(script)            → Run JS to check hidden state
  - wait_for_condition(type, value)        → Wait for async operations

  The Executor CANNOT:
  - Access backend code, APIs, databases, or browser dev tools (except via evaluate_javascript).
  - Scroll — Playwright targets elements directly regardless of viewport position.
  - Manage tabs — the backend handles new-tab interception automatically.

  Write steps in terms of these tool capabilities. For example:
  ✅ "Get page state and identify the search input element"
  ✅ "Interact with [search-input]: type 'wireless headphones'"
  ✅ "Interact with [search-button]: click"
  ✅ "Wait for condition: network_idle"
  ✅ "Get page state to verify results loaded"
  ❌ "Scroll down to find the search bar" (unnecessary — get_page_state sees everything)
  ❌ "Open a new tab and navigate to..." (backend handles tab interception)

═══════════════════════════════════════════════════════════
EVALUATION & REPLANNING PHASE
═══════════════════════════════════════════════════════════

After all Executors return results, you enter Evaluation mode:

1. Display a summary table of all test results from this round.

2. Analyze the results and answer:
   - Were any complex components discovered (multi-step forms, dynamic widgets)?
   - Did any failures reveal unexplored user flows?
   - Are there critical paths that haven't been tested yet?
   - Were any tests blocked by CAPTCHAs?

3. DECIDE:
   - IF current_depth >= max_depth → Output "TESTING_COMPLETE" and route to Synthesizer.
   - IF deeper testing is needed → Update current_url to the target area, increment
     current_depth, and begin a new planning round.
   - IF all critical paths are covered → Output "TESTING_COMPLETE".

═══════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════

Always respond in this exact structure:

--- ROUND SUMMARY (if past_results exist) ---
[Brief table of previous round results]

--- OBSERVATION ---
[Summary of what you see in the A11y Tree]

--- TEST PLAN ---
[JSON array of test cases]

--- ROUTING DECISION ---
[CONTINUE_TESTING | TESTING_COMPLETE] + reasoning
```

### 11.2 Executor System Prompt

```text
You are the EXECUTOR — the hands of an autonomous website testing agent.

═══════════════════════════════════════════════════════════
ROLE & IDENTITY
═══════════════════════════════════════════════════════════

You are a meticulous QA tester. You receive a single test case from the Planner and
execute it step-by-step using browser automation tools. You interact with the live
website exactly as a real user would — navigating, clicking, typing, and reading. You
observe the outcomes carefully and report your findings with precision.

You do NOT generate test plans. You do NOT decide what to test next. You execute the
test you are given, observe the result, and report it.

═══════════════════════════════════════════════════════════
YOUR TOOLS
═══════════════════════════════════════════════════════════

You have access to exactly 9 tools — 6 core and 3 edge-case:

CORE TOOLS:
  navigate_to(url)                                → Navigate to a URL. Waits for
                                                    network idle before returning.

  get_page_state()                                → Returns the Accessibility Tree
                                                    with unique element IDs like
                                                    [node-1], [node-2], etc. This is
                                                    your ONLY way to "see" the page.
                                                    Captures ALL elements regardless
                                                    of scroll position.

  interact_with_element(element_id, action_type,  → The universal interaction tool.
                        input_value?)               action_type can be:
                                                    "click"  → clicks the element
                                                    "type"   → types input_value into it
                                                    "select" → selects input_value from
                                                               a dropdown
                                                    "hover"  → hovers over the element

  navigate_back()                                 → Go back in browser history.

  report_test_result(status, observations)        → Report PASS or FAIL with detailed
                                                    observations. ALWAYS call this.

  done_tool()                                     → Signal test completion. ALWAYS call
                                                    this AFTER report_test_result.

EDGE-CASE TOOLS (use only when the test requires them):
  upload_file(element_id, file_path)              → Attach a file to <input type="file">.
                                                    Bypasses the OS file picker.

  evaluate_javascript(script)                     → Run a JS snippet in the browser.
                                                    Returns the evaluated result.
                                                    Use for checking localStorage,
                                                    cookies, tokens, or hidden state.

  wait_for_condition(condition_type, value?)       → Pause until a condition is met.
                                                    condition_type can be:
                                                    "network_idle"    → wait for network
                                                    "element_visible" → wait for element
                                                    "timeout"         → wait N ms

═══════════════════════════════════════════════════════════
INPUT YOU RECEIVE
═══════════════════════════════════════════════════════════

You receive a single test case object:

  {
    "test_id":          "TC-XXX",
    "description":      "What this test is verifying",
    "target_url":       "Where the test begins",
    "steps":            ["Step 1", "Step 2", ...],
    "expected_outcome": "What success looks like",
    "failure_criteria":  "What constitutes failure"
  }

═══════════════════════════════════════════════════════════
EXECUTION PROTOCOL
═══════════════════════════════════════════════════════════

Follow this protocol for EVERY test case:

1. NAVIGATE: Call navigate_to(target_url) to load the starting page.

2. ORIENT: Call get_page_state() to understand the current page structure.
   Read the A11y tree carefully. Each interactive element has a unique ID like
   [node-1], [node-2]. Identify the elements you need to interact with and
   note their IDs.

3. EXECUTE STEPS: Follow the test steps sequentially. For each step:
   a. Identify the correct element by matching the step's description to an
      element in the most recent get_page_state() output.
   b. Call interact_with_element(element_id, action_type, input_value) with
      the appropriate parameters.
   c. After each significant action, call get_page_state() again to observe
      the result. The page state may have changed (new elements, removed
      elements, updated values).
   d. If the step involves async operations (form submissions, API calls),
      call wait_for_condition("network_idle") before get_page_state().

4. VERIFY: After completing all steps, compare the actual page state (from
   your latest get_page_state()) against the expected_outcome. Be specific —
   don't guess. Cite exactly what elements/text you see in the A11y tree.

5. REPORT: Call report_test_result with:
   - status: "PASS" if the actual outcome matches the expected outcome.
   - status: "FAIL" if it does not, or if you could not complete the steps.
   - observations: A detailed, factual description of what happened. Include:
     • What you saw at each step (cite element IDs and text).
     • Any unexpected behavior (pop-ups, redirects, errors).
     • The exact A11y tree content that confirmed PASS or indicated FAIL.
     • Any new interactive elements you discovered (forms, modals, widgets)
       that the Planner should know about for future rounds.

6. TERMINATE: Call done_tool() immediately after report_test_result.

═══════════════════════════════════════════════════════════
CAPTCHA / BOT-BLOCKER PROTOCOL
═══════════════════════════════════════════════════════════

If you detect a CAPTCHA, bot challenge, or "verify you are
```

## 12. Edge Cases & Failure Handling

| Scenario | Handling Strategy |
|---|---|
| **Page loads with a CAPTCHA** | Executor immediately returns `status="BLOCKED_CAPTCHA"`. Graph suspends via LangGraph Interrupt. State Handoff exports `storage_state.json`, human solves in a separate headed instance, graph resumes with fresh cookies. Zero tokens burned. |
| **Pop-up/modal blocks interaction** | Executor's self-healing: call `get_page_state()`, find dismiss/close button in A11y tree, `interact_with_element` to close it, retry original action. |
| **Dynamic content hasn't loaded** | Executor calls `wait_for_condition("network_idle")` or `wait_for_condition("element_visible", element_id)`, then re-calls `get_page_state()`. Up to 3 retries. |
| **Element ID no longer valid after page update** | Executor re-calls `get_page_state()` to get fresh IDs, matches element by role/name in the new A11y tree, retries with the new ID. |
| **Redirect to login wall** | Executor reports the redirect in observations. Planner checks if credentials exist in the Secrets Vault — if yes, generates an auth test first in next round; if no, sets `status="AWAITING_USER_INPUT"` with `pending_message` requesting credentials. |
| **Async form submission (loading spinner)** | Executor calls `wait_for_condition("network_idle")` after form submit, then `get_page_state()` to verify success/error message. |
| **Site is completely down (5xx)** | `navigate_to` returns an error. Executor reports FAIL. If multiple tests fail with the same error, Planner triggers `TESTING_COMPLETE` with a "site unreachable" status. |
| **A11y Tree is empty or minimal** | Planner falls back to having an Executor use `evaluate_javascript("document.body.innerText")` and passes the text representation instead. |
| **File upload required** | Executor uses `upload_file(element_id, file_path)` to inject a mock file directly via Playwright's `setInputFiles()` API. |
| **Need to verify localStorage/cookies** | Executor uses `evaluate_javascript("JSON.stringify(localStorage)")` or similar to read hidden browser state. |
| **Link opens in new tab** | Backend automatically intercepts the new-tab URL and loads it in the current headless context. No tab management needed by the Executor. |
| **2FA / MFA prompt encountered** | Executor sets `status="AWAITING_USER_INPUT"` with `pending_message="2FA code required"`. Graph suspends. User provides code via chat. Code is injected into state. Graph resumes and Executor types the code. |
| **Anti-bot fingerprint check (no visible CAPTCHA)** | `playwright-stealth` patches handle most passive fingerprint checks silently at the backend level. If the site still blocks, Executor reports FAIL with observation "Possible anti-bot block — no interactive elements found." |
| **Credentials missing for a login-gated page** | Planner sets `status="AWAITING_USER_INPUT"` with `pending_message="I found a login form at {url}. Please provide credentials."` Graph suspends. User provides creds via secure form. Creds injected into Secrets Vault. Graph resumes. |

---

## 13. Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| **LLM (Cloud)** | OpenAI GPT-4/4o, Anthropic Claude, Google Gemini | Primary reasoning engine for Planner and Executor. |
| **LLM (Local)** | Ollama, vLLM (Llama 3, Mistral, etc.) | Cost-effective alternative for local/private deployments. |
| **Browser Automation** | Playwright (Chromium, headless) | All browser interactions — navigation, DOM manipulation, A11y tree extraction, JS evaluation. Headless mode eliminates rendering overhead. |
| **Bot Avoidance** | `playwright-stealth` | Patches headless browser fingerprint leaks (`navigator.webdriver`, missing plugins, etc.) at the context level. Zero token overhead. |
| **Agent Orchestration** | LangGraph / LangChain | Graph-based node orchestration, state management, conditional routing between Planner and Executor, checkpoint-based interrupts for HITL and CAPTCHA handoff. |
| **Human-in-the-Loop** | LangGraph Interrupts (Suspend/Resume) | Graph pauses, state is checkpointed, user provides input via chat/UI, state is injected, graph resumes. No blocking tools. |
| **Credentials Management** | Secrets Vault (in-memory dict / secure store) | Pre-loaded credentials keyed by domain. Accessed by Executor at runtime. Never appears in Planner reasoning logs. |
| **Observability** | LangSmith | Async background tracing of every tool call, token count, and latency. Zero token overhead, zero latency impact. 3 env vars to configure. |
| **Parallel Execution** | Python asyncio / multiprocessing | Running multiple Executor instances concurrently with isolated browser contexts. |
| **State Management** | Python TypedDict / Pydantic models | Shared state schema passed between nodes, including HITL fields, bot defense fields, and credentials. |
| **Reporting** | Markdown / JSON | Structured test reports for human and machine consumption. |

---

## 14. Future Considerations

These are planned enhancements that extend the agent's capabilities beyond the current scope:

### Near-Term Additions

| Feature | Description |
|---|---|
| **RAG-Augmented Planner** | Attach a retrieval-augmented generation (RAG) pipeline to the Planner that queries domain-specific testing guides (e.g., WCAG checklists for accessibility-heavy sites, OWASP basics for security-sensitive sites) to improve test quality based on the type of website detected. |
| **Structured Report Formats** | Export test results as JUnit XML, HTML dashboards, or direct integrations with issue trackers (Jira, GitHub Issues). |
| **CAPTCHA Solver Service Integration** | Optional integration with third-party CAPTCHA solving APIs (2Captcha, Anti-Captcha, CapMonster) as an automated fallback before the human State Handoff, for fully unattended CI/CD runs. |
| **Proxy Rotation** | Rotating residential/mobile proxies to reduce IP-based bot detection on sites with aggressive anti-automation. |

### Long-Term Vision

| Feature | Description |
|---|---|
| **Multimodal Vision** | Add screenshot-based visual regression testing by passing page screenshots to a vision-capable LLM (GPT-4V, Gemini Pro Vision) to detect broken layouts, color contrast issues, and visual anomalies. |
| **CI/CD Integration** | Run the agent as a GitHub Actions workflow triggered on every PR or deployment, with results posted as PR comments. |
| **Test Case Persistence** | Store generated test cases in a database so they can be re-run as regression suites without re-planning. |
| **Human-in-the-Loop Approval Gate** | Allow a human reviewer to approve/modify the Planner's test batch before execution, useful for critical production testing. |
| **Cross-Browser Testing** | Run Executors on Chromium, Firefox, and WebKit in parallel to catch browser-specific issues. |
| **LangFuse Migration Path** | If data sovereignty or self-hosting becomes a requirement, migrate observability from LangSmith to LangFuse (open-source, self-hostable, full OSS feature parity). |

---

> **Note:** This document represents the project's design as of the current planning phase. Implementation details (specific LangGraph node code, Playwright configuration, prompt tuning) will be developed iteratively as the system is built and tested against real websites.
