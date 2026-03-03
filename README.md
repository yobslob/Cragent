# Autonomous Website Testing Agent

A recursive website testing agent that uses **browser-use** for browser automation and **LangGraph** for orchestration.

## Quick Start

```bash
# 1. Install dependencies
make develop

# 2. Copy and fill in your API keys
cp .env.example .env

# 3. Edit config.yaml with your target URL and LLM preferences

# 4. Run
make run
```

## How It Works

1. **Planner** — A read-only browser-use agent analyzes the target page, producing a structured `TestPlan` with test cases and sub-pages.
2. **Approval** — Sub-page planners require human approval (configurable: auto-approve, auto-decline, or interactive interrupt).
3. **Executors** — Parallel browser-use agents execute each test case, reporting pass/fail with evidence.
4. **Recursion** — Discovered sub-pages are enqueued for planning at the next depth level.
5. **Report** — After all planners complete, a summarizer LLM produces a severity-classified Markdown report.

## Configuration

See `config.yaml` for all options. Key settings:

| Setting | Description |
|---|---|
| `target_url` | Root URL to test |
| `llm.planner/executor/summarizer` | Independent LLM configs per role |
| `concurrency.max_executors` | Max parallel browser instances |
| `depth.max_depth` | Max recursion depth |
| `approval.mode` | `interrupt` / `auto_approve` / `auto_decline` |

## Supported LLM Providers

- **OpenRouter** — Any model via `openrouter` provider
- **Groq** — Fast inference via `groq` provider
- **Ollama** — Local models via `ollama` provider
- **NVIDIA** — NVIDIA NIM via `nvidia` provider
- **OpenAI** — Direct OpenAI API via `openai` provider
