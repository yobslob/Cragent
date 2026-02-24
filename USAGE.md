# Usage Guide

## Prerequisites

- Python 3.10+
- An LLM API key (OpenAI, Anthropic, Google, OpenRouter, or Groq)
- Playwright browsers installed

## Installation

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Playwright browsers

```bash
playwright install chromium
```

To install all browsers (chromium, firefox, webkit):

```bash
playwright install
```

### 3. Configure environment variables

Copy the example and fill in your API key:

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
# Required: at least one LLM API key
OPENAI_API_KEY=sk-...

# Optional: alternative providers
# ANTHROPIC_API_KEY=sk-ant-...
# GOOGLE_API_KEY=...
# OPENROUTER_API_KEY=sk-or-...
# GROQ_API_KEY=gsk_...

# Optional: LangSmith observability
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=ls-...
LANGCHAIN_PROJECT=autonomous-testing-agent
```

## Quick Start

### Basic run

```bash
python run.py --url "https://example.com"
```

### With testing instructions

```bash
python run.py --url "https://myapp.com" --instructions "Focus on the login and checkout flows"
```

### With custom depth and concurrency

```bash
python run.py --url "https://amazon.in" --max-depth 10 --max-concurrency 5
```

### Visible browser (for debugging)

```bash
python run.py --url "https://example.com" --no-headless
```

## CLI Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--url` | Yes | - | Target URL to test |
| `--instructions` | No | `""` | Testing scope instructions (e.g., "Focus on checkout flow") |
| `--max-depth` | No | `5` | Max planning rounds before forced termination |
| `--max-concurrency` | No | `3` | Max parallel browser contexts |
| `--batch-size` | No | `5` | Test cases generated per planning round |
| `--config` | No | `./config.yaml` | Path to a custom config.yaml file |
| `--headless` | No | `true` | Run browsers in headless mode |
| `--no-headless` | No | - | Run browsers with visible UI |

## Configuration

Configuration uses a three-layer merge system. Each layer overrides the previous:

1. **YAML file** (`config.yaml`) - base defaults
2. **Environment variables** (`ATA_*` prefix) - override YAML
3. **CLI arguments** - highest priority

### Using environment variable overrides

Any config field can be overridden via an `ATA_` prefixed environment variable:

```bash
export ATA_MAX_DEPTH=10
export ATA_MAX_CONCURRENCY=5
export ATA_PRIMARY_MODEL=gpt-4o
export ATA_HEADLESS=false
export ATA_BATCH_SIZE=7
```

Boolean values accept: `true`, `1`, `yes` (truthy) and `false`, `0`, `no` (falsy).
Lists accept JSON format: `ATA_INTER_REQUEST_DELAY_MS=[200,800]` or comma-separated: `ATA_PROXY_LIST=http://p1:8080,http://p2:8080`.

### Full Configuration Reference

Edit `config.yaml` to customize. All fields and their defaults:

#### Core Settings

| Field | Type | Default | Description |
|---|---|---|---|
| `target_url` | string | `""` | Target URL (usually set via `--url` CLI arg) |
| `testing_instructions` | string | `""` | Scope instructions for the Planner LLM |

#### Depth and Batch Control

| Field | Type | Default | Description |
|---|---|---|---|
| `max_depth` | int | `5` | Max planning rounds before forced termination |
| `batch_size` | int | `5` | Test cases generated per round (3-7 recommended) |
| `max_retries` | int | `3` | Per-test-step retry limit |

#### Concurrency

| Field | Type | Default | Description |
|---|---|---|---|
| `max_concurrency` | int | `3` | Max parallel Executor browser contexts |
| `inter_request_delay_ms` | list[int] | `[500, 1500]` | Random delay range between navigations (ms) |
| `stagger_start_delay_ms` | list[int] | `[0, 2000]` | Random delay range for Executor start stagger |

#### Timeouts

| Field | Type | Default | Description |
|---|---|---|---|
| `graph_timeout_seconds` | int | `1800` | Max total run time (30 min) |
| `node_inactivity_timeout_seconds` | int | `90` | Kill Executor if no tool call in this window |
| `node_absolute_timeout_seconds` | int | `300` | Hard ceiling per Executor (5 min) |
| `navigation_timeout_seconds` | int | `30` | Playwright `page.goto` timeout |
| `max_graph_iterations` | int | `50` | Max total graph node executions (catches infinite loops) |

#### LLM Configuration

| Field | Type | Default | Description |
|---|---|---|---|
| `primary_model` | string | `"gpt-4o"` | Primary LLM for Planner and Executor |
| `fallback_model` | string | `"gpt-4o-mini"` | Fallback model if primary fails after retries |
| `evaluator_model` | string | `"gpt-4o-mini"` | Model for the Evaluator node (simpler task) |
| `synthesizer_model` | string | `"gpt-4o-mini"` | Model for the Synthesizer node |
| `temperature` | float | `0.1` | LLM temperature (low = deterministic) |
| `llm_max_retries` | int | `5` | Max retries on LLM API failures |
| `llm_base_delay_seconds` | int | `1` | Base delay for exponential backoff |

Supported model prefixes:

| Prefix | Provider | Example |
|---|---|---|
| `gpt-` | OpenAI | `gpt-4o`, `gpt-4o-mini` |
| `claude-` | Anthropic | `claude-sonnet-4-20250514` |
| `gemini-` | Google | `gemini-2.5-pro` |
| `ollama/` | Ollama (local) | `ollama/llama3:70b` |
| `openrouter/` | OpenRouter | `openrouter/anthropic/claude-sonnet-4-20250514` |
| `groq/` | Groq | `groq/llama-3.3-70b-versatile` |

#### Local Model Support (Ollama)

| Field | Type | Default | Description |
|---|---|---|---|
| `ollama_base_url` | string | `"http://localhost:11434"` | Ollama server URL |

To use local models, update `config.yaml`:

```yaml
primary_model: "ollama/llama3:70b"
fallback_model: "ollama/llama3:8b"
ollama_base_url: "http://localhost:11434"
```

#### OpenRouter

[OpenRouter](https://openrouter.ai/) provides access to 100+ models through a single API endpoint.

| Field | Type | Default | Description |
|---|---|---|---|
| `openrouter_base_url` | string | `"https://openrouter.ai/api/v1"` | OpenRouter API endpoint |

Set the API key in `.env`:

```dotenv
OPENROUTER_API_KEY=sk-or-...
# Optional:
OPENROUTER_REFERRER=https://your-app.com
OPENROUTER_APP_TITLE=Autonomous Testing Agent
```

Then use the `openrouter/` prefix in `config.yaml`. The model name after the prefix is the OpenRouter model ID:

```yaml
primary_model: "openrouter/anthropic/claude-sonnet-4-20250514"
fallback_model: "openrouter/meta-llama/llama-3-70b-instruct"
evaluator_model: "openrouter/google/gemini-2.5-flash"
```

#### Groq

[Groq](https://groq.com/) provides ultra-fast LLM inference.

Set the API key in `.env`:

```dotenv
GROQ_API_KEY=gsk_...
```

Then use the `groq/` prefix in `config.yaml`:

```yaml
primary_model: "groq/llama-3.3-70b-versatile"
fallback_model: "groq/llama-3.1-8b-instant"
evaluator_model: "groq/llama-3.1-8b-instant"
```

#### Browser Configuration

| Field | Type | Default | Description |
|---|---|---|---|
| `headless` | bool | `true` | Run browsers without visible UI |
| `browser` | string | `"chromium"` | Browser engine: `chromium`, `firefox`, or `webkit` |
| `stealth_enabled` | bool | `true` | Apply playwright-stealth anti-detection patches |
| `viewport_width` | int | `1280` | Browser viewport width |
| `viewport_height` | int | `720` | Browser viewport height |

#### Proxy Configuration

| Field | Type | Default | Description |
|---|---|---|---|
| `proxy_list` | list[string] | `[]` | List of proxy URLs |
| `proxy_rotation` | string | `"round-robin"` | Rotation strategy: `round-robin` or `random` |

Example in `config.yaml`:

```yaml
proxy_list:
  - "http://proxy1:8080"
  - "http://proxy2:8080"
  - "socks5://proxy3:1080"
proxy_rotation: "round-robin"
```

#### Context Window Management

| Field | Type | Default | Description |
|---|---|---|---|
| `a11y_tree_max_nodes` | int | `150` | Max A11y tree nodes after pruning |
| `token_budget_past_results` | int | `2000` | Max tokens for past results in Planner prompt |

#### Cookie Consent

| Field | Type | Default | Description |
|---|---|---|---|
| `dismiss_cookie_consent` | bool | `true` | Auto-dismiss cookie banners on first navigation |
| `cookie_consent_timeout_ms` | int | `3000` | Timeout waiting for cookie banner to appear |

#### Authentication

| Field | Type | Default | Description |
|---|---|---|---|
| `auth_bootstrap_enabled` | bool | `true` | Run Auth Bootstrap if credentials are provided |
| `login_url_patterns` | list[string] | `["/login", "/signin", "/auth", "/sso"]` | URL patterns that indicate a login page |

Credentials are provided in the initial state (not in config.yaml) as a domain-keyed dictionary:

```python
credentials = {
    "example.com": {"username": "admin", "password": "s3cret"},
    "staging.myapp.com": {"username": "test", "password": "testpass"},
}
```

The agent uses `{{vault:username}}` and `{{vault:password}}` tokens internally so that the LLM never sees actual credential values.

#### Observability

| Field | Type | Default | Description |
|---|---|---|---|
| `langsmith_enabled` | bool | `true` | Enable LangSmith tracing |
| `langsmith_project` | string | `"autonomous-testing-agent"` | LangSmith project name |
| `credential_redaction_enabled` | bool | `true` | Redact secrets from LangSmith traces |

#### Output

| Field | Type | Default | Description |
|---|---|---|---|
| `report_format` | string | `"markdown"` | Report format: `markdown` or `json` |
| `report_output_path` | string | `"./test-report"` | Output path for the final report |

## CAPTCHA Handling

When the agent encounters a CAPTCHA it cannot bypass, it exports the browser state and pauses. Use the standalone solver to handle it:

```bash
python solve_captcha.py --state /tmp/captcha_state_xxx.json --url "https://example.com/blocked"
```

This opens a headed browser window with the existing session. Solve the CAPTCHA manually, then press Enter in the terminal. The solved state is saved and the agent resumes automatically.

## Running Tests

```bash
# Full test suite
python -m pytest tests/ -v

# Specific test file
python -m pytest tests/test_vault.py -v

# Specific test class
python -m pytest tests/test_tools_unit.py::TestInteractWithElement -v
```

### Test Files

| File | Coverage |
|---|---|
| `test_state.py` | State models, reducers, Pydantic validation |
| `test_config.py` | YAML loading, env var overrides, CLI overrides, type coercion |
| `test_a11y_tree.py` | A11y tree filtering, pruning, node ID assignment, serialization |
| `test_js_sandbox.py` | JS allowlist passes, blocklist blocks, fail-closed defaults |
| `test_compression.py` | Past results compression, budget enforcement, FAIL preservation |
| `test_vault.py` | Credential vault, token resolution, domain matching |
| `test_tools_unit.py` | All 9 executor tools with mocked Playwright Page |
| `test_graph_smoke.py` | Graph compilation, node topology, routing functions |
| `test_integration.py` | Full graph build, node/edge verification |

## Architecture Overview

The agent runs a loop of four phases:

```
Planner -> Executor(s) -> Evaluator -> Synthesizer
    ^                         |
    |--- CONTINUE_TESTING ----|
```

1. **Planner** - LLM inspects the page's accessibility tree and generates test cases
2. **Executor** - Each test case runs in its own stealth browser context with 9 tools
3. **Evaluator** - Reviews results and decides: continue testing, stop, or re-authenticate
4. **Synthesizer** - Aggregates all results into a final Markdown/JSON report

Independent tests run in parallel. Tests with a shared `conflict_group` run sequentially via the Serial Executor.
