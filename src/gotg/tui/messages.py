"""Custom Textual Messages for worker thread → UI communication."""

from __future__ import annotations

from textual.message import Message


class EngineEvent(Message):
    """Wraps any engine event for delivery from worker thread to UI."""

    def __init__(self, event: object) -> None:
        super().__init__()
        self.event = event


class SessionError(Message):
    """Worker thread encountered an error."""

    def __init__(self, error: str) -> None:
        super().__init__()
        self.error = error


class ToolProgress(Message):
    """Wraps a ToolCallProgress event for delivery from worker thread to UI."""

    def __init__(self, event: object) -> None:
        super().__init__()
        self.event = event


class TextDeltaMsg(Message):
    """Batched text delta from streaming LLM response."""

    def __init__(self, agent: str, turn_id: str, text: str) -> None:
        super().__init__()
        self.agent = agent
        self.turn_id = turn_id
        self.text = text
