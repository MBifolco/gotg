"""Cooperative pause controller for CLI sessions.

Installs a SIGINT handler that sets a flag on first Ctrl+C.
Second Ctrl+C within 2s triggers hard kill (exit 130).
"""

from __future__ import annotations

import os
import signal
import sys
import time
from typing import Any


# Sentinel for "resume without injecting a message"
class _ResumeSentinel:
    """Sentinel value returned by prompt_for_interjection when user presses Enter."""
    def __repr__(self) -> str:
        return "RESUME"

RESUME = _ResumeSentinel()


class PauseController:
    """Manages cooperative SIGINT-based pause for CLI sessions."""

    def __init__(self) -> None:
        self._pause_requested = False
        self._interrupt_count = 0
        self._last_interrupt_time: float = 0.0
        self._original_handler: Any = None

    def install(self) -> None:
        """Install custom SIGINT handler. Call in try/finally with uninstall()."""
        self._original_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._handle_sigint)

    def uninstall(self) -> None:
        """Restore original SIGINT handler."""
        if self._original_handler is not None:
            signal.signal(signal.SIGINT, self._original_handler)
            self._original_handler = None

    def request_pause(self) -> None:
        """Programmatically request a pause (same as first Ctrl+C)."""
        self._pause_requested = True

    def is_pause_requested(self) -> bool:
        """Check if pause has been requested. Does NOT reset the flag."""
        return self._pause_requested

    def reset(self) -> None:
        """Clear pause flag and interrupt count for next session loop."""
        self._pause_requested = False
        self._interrupt_count = 0

    def _handle_sigint(self, signum: int, frame: Any) -> None:
        now = time.monotonic()

        if self._interrupt_count > 0 and (now - self._last_interrupt_time) < 2.0:
            # Second Ctrl+C within 2s — hard kill
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            os.kill(os.getpid(), signal.SIGINT)
            return  # unreachable, but satisfies type checker

        self._interrupt_count += 1
        self._last_interrupt_time = now
        self._pause_requested = True
        print("\nPause requested — will stop after current turn completes...", file=sys.stderr)


def prompt_for_interjection(resume_hint: str) -> str | _ResumeSentinel | None:
    """Prompt the user for input after a pause.

    Returns:
        str: User typed a message to inject
        RESUME: User pressed Enter (resume without message)
        None: User pressed Ctrl+C or EOF (stop session)
    """
    try:
        print("---")
        print(f"Paused. Enter a message, press Enter to resume, or Ctrl+C to stop.")
        print(f"(To resume later: `{resume_hint}`)")
        text = input("> ").strip()
        if not text:
            return RESUME
        return text
    except (KeyboardInterrupt, EOFError):
        print()
        return None
