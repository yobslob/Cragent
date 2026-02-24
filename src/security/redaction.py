"""
Credential redaction callback handler for LangSmith traces.

Strips sensitive values from tool inputs/outputs before they reach
the observability backend.
"""

import re
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


class RedactingCallbackHandler(BaseCallbackHandler):
    """
    Strips vault references and credential values from trace data.

    Applied as a callback handler to all LLM and tool calls.
    Ensures no credentials appear in LangSmith traces.
    """

    REDACT_PATTERNS = [
        r'"password"\s*:\s*"[^"]*"',
        r'"api_key"\s*:\s*"[^"]*"',
        r'"secret"\s*:\s*"[^"]*"',
        r'"token"\s*:\s*"[^"]*"',
        r'\{\{vault:[^}]+\}\}',
    ]

    def __init__(self, extra_patterns: list[str] | None = None):
        super().__init__()
        self._patterns = list(self.REDACT_PATTERNS)
        if extra_patterns:
            self._patterns.extend(extra_patterns)
        self._compiled = [re.compile(p) for p in self._patterns]

    def _redact(self, text: str) -> str:
        """Apply all redaction patterns to a string."""
        for pattern in self._compiled:
            text = pattern.sub('"***REDACTED***"', text)
        return text

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Redact tool inputs before tracing."""
        if isinstance(input_str, str):
            kwargs["input_str"] = self._redact(input_str)

    def on_tool_end(
        self,
        output: str,
        **kwargs: Any,
    ) -> None:
        """Redact tool outputs before tracing."""
        if isinstance(output, str):
            kwargs["output"] = self._redact(output)

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        """Redact LLM prompt inputs before tracing."""
        kwargs["prompts"] = [self._redact(p) for p in prompts]
