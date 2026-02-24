"""
LLM API retry wrapper with exponential backoff and fallback model support.

Handles rate-limit (429) errors intelligently:
  - Reads Retry-After / x-ratelimit-reset-requests response headers when present
  - Falls back to a configurable minimum wait floor (rate_limit_min_wait_seconds)
    to respect provider RPM limits (OpenRouter free tier: ~20 RPM)
"""

import random

from tenacity import (
    retry,
    stop_after_attempt,
    retry_if_exception_type,
)
from tenacity.wait import wait_base
from langchain_core.language_models import BaseChatModel


# Common retryable exception types across LLM providers
_RETRYABLE_EXCEPTIONS = (Exception,)

try:
    from openai import RateLimitError, APITimeoutError, APIConnectionError
    _RETRYABLE_EXCEPTIONS = (RateLimitError, APITimeoutError, APIConnectionError)
    _RATE_LIMIT_EXCEPTION = RateLimitError
except ImportError:
    _RATE_LIMIT_EXCEPTION = None


class _SmartWait(wait_base):
    """
    Wait strategy aware of rate-limit vs transient errors.

    For RateLimitError (429):
      1. Parse Retry-After (or x-ratelimit-reset-requests) response header.
      2. If absent, use rate_limit_min_wait with exponential growth per attempt.

    For all other errors: standard exponential backoff from base_delay.
    """

    def __init__(
        self,
        base_delay: float = 1.0,
        rate_limit_min_wait: float = 3.0,
        max_wait: float = 120.0,
    ):
        self.base_delay = base_delay
        self.rate_limit_min_wait = rate_limit_min_wait
        self.max_wait = max_wait

    def __call__(self, retry_state) -> float:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        attempt = retry_state.attempt_number

        # Try to read Retry-After from the HTTP response headers
        if exc is not None:
            response = getattr(exc, "response", None)
            if response is not None:
                headers = getattr(response, "headers", None) or {}
                for header in ("Retry-After", "retry-after", "x-ratelimit-reset-requests"):
                    val = headers.get(header)
                    if val:
                        try:
                            explicit = float(val)
                            return min(explicit + random.uniform(0, 2), self.max_wait)
                        except (ValueError, TypeError):
                            pass

        # Determine whether this is a rate-limit error
        is_rate_limit = (
            _RATE_LIMIT_EXCEPTION is not None
            and exc is not None
            and isinstance(exc, _RATE_LIMIT_EXCEPTION)
        )

        if is_rate_limit:
            # Grow from rate_limit_min_wait: 15s, 30s, 60s, 120s …
            wait = min(self.rate_limit_min_wait * (2 ** (attempt - 1)), self.max_wait)
        else:
            # Standard exponential: 1s, 2s, 4s, 8s …
            wait = min(self.base_delay * (2 ** (attempt - 1)), self.max_wait)

        return wait + random.uniform(0, 2)


def _create_retry_decorator(
    max_retries: int = 5,
    base_delay: float = 1.0,
    rate_limit_min_wait: float = 3.0,
):
    """Create a tenacity retry decorator with rate-limit-aware wait."""
    return retry(
        stop=stop_after_attempt(max_retries),
        wait=_SmartWait(
            base_delay=base_delay,
            rate_limit_min_wait=rate_limit_min_wait,
        ),
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        reraise=True,
    )


async def call_llm_with_retry(
    llm: BaseChatModel,
    messages: list,
    max_retries: int = 5,
    base_delay: float = 1.0,
    rate_limit_min_wait: float = 3.0,
    **kwargs,
):
    """
    Invoke an LLM with exponential backoff retry on transient failures.

    Retries on: RateLimitError, APITimeoutError, APIConnectionError.
    Rate-limit errors use a longer minimum wait floor to respect provider RPM limits.
    """
    decorator = _create_retry_decorator(max_retries, base_delay, rate_limit_min_wait)

    @decorator
    async def _invoke():
        return await llm.ainvoke(messages, **kwargs)

    return await _invoke()


async def call_llm_with_fallback(
    primary_llm: BaseChatModel,
    fallback_llm: BaseChatModel | None,
    messages: list,
    max_retries: int = 5,
    base_delay: float = 1.0,
    rate_limit_min_wait: float = 3.0,
    **kwargs,
):
    """
    Try primary model, fall back to cheaper model on persistent failure.
    """
    try:
        return await call_llm_with_retry(
            primary_llm, messages, max_retries, base_delay, rate_limit_min_wait, **kwargs
        )
    except Exception:
        if fallback_llm:
            return await call_llm_with_retry(
                fallback_llm, messages, max_retries, base_delay, rate_limit_min_wait, **kwargs
            )
        raise
