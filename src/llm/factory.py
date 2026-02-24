"""
LLM factory — construct the correct LangChain chat model from config strings.

Supports:
  - OpenAI      (gpt-*)
  - Anthropic   (claude-*)
  - Google      (gemini-*)
  - Ollama      (ollama/*)
  - OpenRouter  (openrouter/*)
  - Groq        (groq/*)
"""

import os

from langchain_core.language_models import BaseChatModel


def create_llm(
    model_name: str,
    temperature: float = 0.1,
    ollama_base_url: str = "http://localhost:11434",
    ollama_num_ctx: int = 4096,
    openrouter_base_url: str = "https://openrouter.ai/api/v1",
    **kwargs,
) -> BaseChatModel:
    """
    Create a LangChain chat model from a model name string.

    Supported prefixes:
      - "gpt-*"          -> ChatOpenAI
      - "claude-*"       -> ChatAnthropic
      - "gemini-*"       -> ChatGoogleGenerativeAI
      - "ollama/*"       -> ChatOllama
      - "openrouter/*"   -> ChatOpenAI with OpenRouter base URL
      - "groq/*"         -> ChatGroq
    """
    if model_name.startswith("ollama/"):
        from langchain_ollama import ChatOllama
        actual_model = model_name.split("/", 1)[1]
        return ChatOllama(
            model=actual_model,
            base_url=ollama_base_url,
            temperature=temperature,
            timeout=120,  # 120s request timeout — fail fast if Ollama is unreachable
            num_ctx=ollama_num_ctx,
            **kwargs,
        )
    elif model_name.startswith("openrouter/"):
        from langchain_openai import ChatOpenAI
        actual_model = model_name.split("/", 1)[1]
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        return ChatOpenAI(
            model=actual_model,
            base_url=openrouter_base_url,
            api_key=api_key,
            temperature=temperature,
            default_headers={
                "HTTP-Referer": os.environ.get("OPENROUTER_REFERRER", ""),
                "X-Title": os.environ.get("OPENROUTER_APP_TITLE", "Autonomous Testing Agent"),
            },
            **kwargs,
        )
    elif model_name.startswith("groq/"):
        from langchain_groq import ChatGroq
        actual_model = model_name.split("/", 1)[1]
        return ChatGroq(
            model=actual_model,
            temperature=temperature,
            **kwargs,
        )
    elif model_name.startswith("claude"):
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model_name,
            temperature=temperature,
            **kwargs,
        )
    elif model_name.startswith("gemini"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            **kwargs,
        )
    else:
        # Default to OpenAI (covers gpt-4o, gpt-4o-mini, etc.)
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            **kwargs,
        )
