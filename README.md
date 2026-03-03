# Autonomous Website Testing Agent

CLI tool that crawls a target URL, generates test plans via LLM, executes them with headless browsers, and produces a severity-classified Markdown report.

**Stack:** Python 3.12 · browser-use v0.12.1 · LangGraph · Gemini · Pydantic v2 · Rich

## Quick Start

```bash
make develop                  # Install dependencies (uv sync --all-extras)
cp .env.example .env          # Add API keys (GOOGLE_API_KEY, etc.)
nano config.yaml              # Set target_url and LLM preferences
make run                      # Run the agent
```

## Architecture

LangGraph `StateGraph` with 6 nodes:

```
START → dequeue → approve → plan ─┬→ execute → compile → dequeue (loop)
                                   └→ plan (clarification loop)
                                                   ↓ (queue empty)
                                               summarize → END
```

| Node | Purpose |
|---|---|
| **dequeue** | Pops next URL from queue, skips visited or depth-exceeded |
| **approve** | Human-in-the-loop gate via `interrupt()` (configurable) |
| **plan** | Generates `TestPlan` via Gemini (multimodal) with 3-tier fallback |
| **execute** | Parallel browser-use agents per test case, bounded by semaphore |
| **compile** | Aggregates results, enqueues discovered sub-pages |
| **summarize** | LLM generates final Markdown report → `report.md` |

The planner uses direct LLM calls with screenshots — it never spawns a browser agent. Only the executor uses browser-use.

## CLI Usage

```bash
make run                      # Interactive mode
make run-auto                 # Auto-approve all sub-pages
```

```bash
uv run python -m src.main --config config.yaml \
  --url https://example.com \
  --urls /products /login /cart \
  -i "Test navigation, forms, and interactive elements" \
  --auto-approve -v
```

| Flag | Purpose |
|---|---|
| `--config PATH` | Config file (default: `config.yaml`) |
| `--url URL` | Override `target_url` |
| `--urls PATH...` | Additional pages to seed (resolved against target) |
| `-i TEXT` | Testing instructions (skips interactive prompt) |
| `--auto-approve` | Auto-approve all sub-pages |
| `-v` | Debug logging |

## Configuration

All options in `config.yaml` — see [`src/config.py`](src/config.py) for the full schema.

| Setting | Default | Description |
|---|---|---|
| `target_url` | — | Root URL to test |
| `extra_urls` | `[]` | Additional paths or URLs to seed |
| `llm.planner` | gemini | Planner LLM (multimodal, screenshot-based) |
| `llm.executor` | ollama | Executor LLM (browser interaction) |
| `llm.summarizer` | ollama | Report generation LLM |
| `llm.fallback` | ollama | Fallback when primary planner fails |
| `concurrency.max_executors` | 4 | Parallel browser instances |
| `depth.max_depth` | 2 | Sub-page recursion depth (0 = root only) |
| `approval.mode` | `auto_approve` | `auto_approve` · `interrupt` · `auto_decline` |
| `browser.headless` | `true` | Set `false` to watch execution |

## LLM Providers

| Provider | Use Case | Notes |
|---|---|---|
| `gemini` | Planner | Multimodal via `google-genai` SDK (not through factory) |
| `ollama` | Executor / Fallback | Local; uses `ChatOllamaFixed` wrapper |
| `openrouter` | Any role | Any model via OpenRouter API |
| `groq` | Any role | Fast inference |
| `nvidia` | Any role | NVIDIA NIM endpoints |
| `openai` | Any role | Direct OpenAI API |

## Development

```bash
make check          # Lint + test
make lint           # ruff check src/ tests/
make format         # ruff format + fix
make test           # pytest tests/ -v
make clean          # Remove caches
```

## License

MIT
