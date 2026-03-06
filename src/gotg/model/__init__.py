"""LLM API dispatch — provider-agnostic chat completion and streaming.

Routes calls to Anthropic or OpenAI backends based on model config. Provides
chat_completion, agentic_completion (multi-round tool loop), raw_completion,
and raw_completion_stream. Called by engine.py, transitions.py, and CLI.
"""

from gotg.model.types import CompletionRound, StreamingResult
from gotg.model.routing import (
    chat_completion,
    agentic_completion,
    raw_completion,
    raw_completion_stream,
)

__all__ = [
    "CompletionRound",
    "StreamingResult",
    "chat_completion",
    "agentic_completion",
    "raw_completion",
    "raw_completion_stream",
]
