from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass
class CompletionRound:
    """Result of a single LLM round that may contain tool calls."""
    content: str
    tool_calls: list[dict]    # [{"name", "input", "id"}]
    _provider: str
    _raw: dict                # Provider-specific raw response data

    def build_continuation(self, tool_results: list[dict]) -> list[dict]:
        """Build messages to append for the next LLM round.

        Args: tool_results = [{"id": str, "result": str}, ...]
        Returns: list of message dicts (provider-formatted)
        """
        if self._provider == "anthropic":
            return [
                {"role": "assistant", "content": self._raw["content_blocks"]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": r["id"], "content": r["result"]}
                    for r in tool_results
                ]},
            ]
        else:
            msgs = [self._raw["message"]]
            for r in tool_results:
                msgs.append({"role": "tool", "tool_call_id": r["id"], "content": r["result"]})
            return msgs


@dataclass
class StreamingResult:
    """Wraps a generator that yields text deltas and captures final CompletionRound."""
    _gen: Iterator[str]
    round: CompletionRound | None = None

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self._gen)
        except StopIteration:
            raise
