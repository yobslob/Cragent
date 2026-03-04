# Autonomous Website Testing Agent

Automated testing tool that takes a website URL, generates test cases using an LLM, runs them in a headless browser, and outputs a severity-classified Markdown report.

## Prerequisites

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** — Python package manager
- **Playwright** browsers (installed automatically on first run)
- At least one LLM provider set up (see [Supported LLMs](#supported-llms))

## Installation

```bash
git clone <repo-url> && cd Cragent
make develop
```

This installs all dependencies via `uv sync`.

## Setup

1. **Create your env file:**

   ```bash
   cp .env.example .env
   ```

   Add your API keys here (e.g. `GOOGLE_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, etc.).

2. **Create / edit `config.yaml`:**

   ```yaml
   target_url: https://example.com

   extra_urls:
     - /login
     - /products

   llm:
     planner:
       provider: gemini
       model: gemini-2.0-flash
     executor:
       provider: ollama
       model: qwen2.5:7b
     summarizer:
       provider: ollama
       model: qwen2.5:7b
     fallback:
       provider: ollama
       model: qwen2.5:7b

   concurrency:
     max_executors: 4

   depth:
     max_depth: 2

   approval:
     mode: auto_approve

   browser:
     headless: true
   ```

## Usage

**Quick run:**

```bash
make run                      # Interactive mode (prompts for instructions)
make run-auto                 # Auto-approve all sub-pages
```

**Full CLI:**

```bash
uv run python -m src.main --config config.yaml \
  --url https://example.com \
  --urls /products /login /cart \
  -i "Test navigation, forms, and interactive elements" \
  --auto-approve -v
```

### CLI Flags

| Flag | Description |
|---|---|
| `--config PATH` | Path to config file (default: `config.yaml`) |
| `--url URL` | Override `target_url` from config |
| `--urls PATH...` | Additional pages to test |
| `-i TEXT` | Testing instructions (skips the interactive prompt) |
| `--auto-approve` | Skip approval prompts for sub-pages |
| `-v` | Enable debug logging |

### Output

The agent produces a `report.md` file with test results classified by severity.

## Configuration Reference

| Setting | Default | Description |
|---|---|---|
| `target_url` | — | Root URL to test |
| `extra_urls` | `[]` | Additional paths or full URLs to include |
| `llm.planner` | — | LLM used to generate test plans |
| `llm.executor` | — | LLM used to drive the browser |
| `llm.summarizer` | — | LLM used to write the final report |
| `llm.fallback` | — | Fallback LLM if the planner fails |
| `concurrency.max_executors` | `4` | Number of parallel browser instances |
| `depth.max_depth` | `2` | How many levels deep to follow sub-pages (0 = root only) |
| `approval.mode` | `auto_approve` | `auto_approve`, `interrupt` (manual), or `auto_decline` |
| `browser.headless` | `true` | Set to `false` to watch the browser in real time |
| `report.output_path` | `report.md` | Where to save the report |

## Supported LLMs

Each LLM role (planner, executor, summarizer, fallback) can use any of these providers:

| Provider | Config value | Requirements |
|---|---|---|
| Google Gemini | `gemini` | `GOOGLE_API_KEY` in `.env` |
| Ollama | `ollama` | Local Ollama instance running |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` in `.env` |
| Groq | `groq` | `GROQ_API_KEY` in `.env` |
| NVIDIA NIM | `nvidia` | `NVIDIA_API_KEY` in `.env` |
| OpenAI | `openai` | `OPENAI_API_KEY` in `.env` |

### Provider config format

Each LLM entry in `config.yaml` takes:

```yaml
provider: gemini          # One of the providers above
model: gemini-2.0-flash   # Model identifier
base_url: null            # Optional: custom endpoint URL
api_key_env: null         # Optional: override env var name for the API key
```

## Development

```bash
make check          # Lint + test
make lint           # Linting only
make format         # Auto-format code
make test           # Run tests
make clean          # Remove caches
```

## License

MIT
