from __future__ import annotations

from typing import Iterator

import httpx

from gotg.model.types import CompletionRound, StreamingResult
from gotg.model.anthropic import (
    _anthropic_completion,
    _anthropic_agentic,
    _anthropic_raw,
    _anthropic_raw_stream,
)
from gotg.model.openai import (
    _openai_completion,
    _openai_agentic,
    _openai_raw,
    _openai_raw_stream,
)


def chat_completion(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    provider: str = "ollama",
    tools: list[dict] | None = None,
) -> str | dict:
    if provider == "anthropic":
        return _anthropic_completion(base_url, model, messages, api_key, tools)
    return _openai_completion(base_url, model, messages, api_key, tools)


def agentic_completion(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    provider: str = "ollama",
    tools: list[dict] | None = None,
    tool_executor: callable = None,
    max_rounds: int = 10,
) -> dict:
    """Chat completion with automatic tool execution loop.

    Returns: {"content": str, "operations": [{"name", "input", "result"}, ...]}
    """
    if provider == "anthropic":
        return _anthropic_agentic(
            base_url, model, messages, api_key, tools, tool_executor, max_rounds
        )
    return _openai_agentic(
        base_url, model, messages, api_key, tools, tool_executor, max_rounds
    )


# ── Raw completion (single-round, engine-driven tool loop) ──────


def raw_completion(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    provider: str = "ollama",
    tools: list[dict] | None = None,
    max_tokens: int = 16384,
) -> CompletionRound:
    """Single-round completion returning CompletionRound for engine-driven tool loops.

    Used by implementation executor. chat_completion stays unchanged.
    """
    if provider == "anthropic":
        return _anthropic_raw(base_url, model, messages, api_key, tools, max_tokens=max_tokens)
    return _openai_raw(base_url, model, messages, api_key, tools, max_tokens=max_tokens)


# ── Streaming completion (single-round, yields text deltas) ─────


def raw_completion_stream(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    provider: str = "ollama",
    tools: list[dict] | None = None,
    max_tokens: int = 16384,
) -> StreamingResult:
    """Single-round streaming completion returning StreamingResult.

    Yields text deltas as they arrive. The final CompletionRound is
    available on result.round after iteration completes.
    """
    def _provider_stream() -> Iterator[str]:
        if provider == "anthropic":
            return _anthropic_raw_stream(base_url, model, messages, api_key, tools, max_tokens=max_tokens)
        return _openai_raw_stream(base_url, model, messages, api_key, tools, max_tokens=max_tokens)

    result = StreamingResult(_gen=iter(()))

    # Wrap the provider stream so we can capture CompletionRound and provide
    # fallback to non-streaming ONLY before any delta was emitted.
    def _capturing_with_fallback():
        emitted = False
        try:
            stream = _provider_stream()
            while True:
                chunk = next(stream)
                emitted = True
                yield chunk
        except StopIteration as done:
            result.round = done.value
            return
        except (httpx.StreamError, httpx.TransportError):
            if emitted:
                raise
            fallback_round = raw_completion(
                base_url=base_url,
                model=model,
                messages=messages,
                api_key=api_key,
                provider=provider,
                tools=tools,
                max_tokens=max_tokens,
            )
            result.round = fallback_round
            if fallback_round.content:
                yield fallback_round.content
            return

    result._gen = _capturing_with_fallback()
    return result
