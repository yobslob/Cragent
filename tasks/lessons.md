# Lessons Learned

## Architecture — THE MOST IMPORTANT LESSON

- **The planner must NEVER use browser-use Agent.** Using a browser agent to "discover" tests wastes 15+ steps browsing randomly, extracting irrelevant data, clicking blindly, and getting stuck in loops. The planner should be a simple direct LLM `ainvoke()` call that generates a TestPlan JSON from the URL + user instructions. Only the executor needs a browser.
- **When user gives specific instructions, generate ONLY focused tests.** If user says "test add to basket button", generate 1-3 tests for that button. Don't generate 6 generic tests about heading hierarchy, link validation, etc.
- **Default to `max_depth: 0`.** Sub-page recursion is almost never needed unless the user explicitly asks for it.
- **Default to `auto_approve`.** The interrupt mode just adds friction for no benefit in most cases.

## browser-use API

- **MUST use `browser_use.llm` wrappers**, NOT `langchain_openai`/`langchain_groq`/`langchain_ollama`. browser-use Agent checks `llm.provider` which only exists on its own wrappers.
- `browser_use.llm.ChatOllama` uses `host=` param, NOT `base_url=`.
- **`ChatOllama.ainvoke()` returns `ChatInvokeCompletion` — access `.completion`, NOT `.content`.** The `.content` attribute does not exist. Use `response.completion` for the text output. Always guard with `hasattr()` for portability across providers.
- `AgentSettings` does NOT exist in browser-use v0.12.1. Use `extend_system_message=` param on Agent directly.
- **Always pass `fallback_llm`** to Agent — browser-use auto-retries with it on failures.
- **Always enable `flash_mode=True`** for local/smaller models — simplifies action schema.
- **Ollama models often output wrong action key names** (e.g. `"type"` instead of `"input"`/`"click"`/`"navigate"`). Use `ChatOllamaFixed` wrapper (`src/llm/ollama_wrapper.py`) which intercepts structured output and fixes malformed action keys by inferring the correct name from inner field patterns (index+text→input, index→click, url→navigate, etc.).
- Use `browser_use.llm.SystemMessage` / `UserMessage` for direct LLM calls.

## Executor Settings

- **max_steps=15** is the hard limit. If a test needs more, it's too complex — simplify the test.
- **`max_actions_per_step=1`** for Ollama models — multi-action steps cause schema validation failures. The model outputs wrong JSON structure (e.g. `type`/`selector` instead of `input`/`index`). One action per step is more reliable.
- **`include_tool_call_examples=True`** — critical for Ollama models that don't natively understand browser-use's action schema. Shows examples of correct JSON format.
- **`use_thinking=False`** for Ollama — thinking output can confuse the action parser.
- `max_failures=5` is fine — don't inflate too much or the agent loops forever.
- **Use the same capable model for executor as for planner.** llama3.1:8b is too weak for browser interaction.
- **Set `ollama_options={'temperature': 0, 'num_ctx': 16384}`** — temperature=0 makes output more deterministic and schema-conformant. Larger context window helps model attend to the full action schema.

## LangGraph

- `interrupt()` requires a checkpointer (`MemorySaver`) on compiled graph.
- State must be JSON-serializable — `.model_dump()` for Pydantic models.
- Don't name node params `config` — conflicts with LangGraph's `RunnableConfig`.
