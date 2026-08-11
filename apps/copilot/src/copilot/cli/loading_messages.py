"""
Rotating status messages shown while an agent call is in flight — the
Claude-Code-style "flibbertigibetting..." feel instead of a silent 30-60s pause.

Usage:

    async with LoadingAnimator(BA_MESSAGES):
        result = await orchestrator.process_input(...)

The animator cancels itself cleanly on exit (success or exception) and clears
the terminal line — it never leaves stray output or hangs on a dead call.
"""

import asyncio
import itertools
import sys
import time
from typing import List, Optional

# No emojis, matching house style. Playful but not precious — these rotate on
# a timer, so keep each one short enough to read at a glance.

BA_MESSAGES: List[str] = [
    "Interviewing the problem statement...",
    "Chasing down regulatory footnotes...",
    "Mapping the customer journey...",
    "Weighing benefits against scope...",
    "Drafting user stories...",
]

PE_MESSAGES: List[str] = [
    "Stress-testing the architecture...",
    "Poking at failure paths...",
    "Negotiating with the NFRs...",
    "Sketching the integration map...",
    "Working out the rollback plan...",
]

RFC_MESSAGES: dict = {
    "ui_ux": [
        "Walking through the user journey...",
        "Checking contrast and tab order...",
        "Sketching the information architecture...",
    ],
    "security": [
        "Red-teaming the design...",
        "Tracing the data across systems...",
        "Checking the encryption story...",
    ],
    "qa": [
        "Inventing edge cases...",
        "Trying to break the happy path...",
        "Writing exit criteria...",
    ],
    "devops": [
        "Planning the rollout...",
        "Wiring up the alerts...",
        "Testing the rollback in theory...",
    ],
    "system_design": [
        "Drawing component boundaries...",
        "Working out the API contracts...",
        "Reconciling the data models...",
    ],
}


class LoadingAnimator:
    """
    Async context manager that cycles messages on an interval while the real
    work happens inside the `async with` block. Cancels itself cleanly and
    clears the line on exit, regardless of whether the block succeeded,
    raised, or was itself cancelled.
    """

    def __init__(self, messages: List[str], interval: float = 4.0):
        if not messages:
            raise ValueError("LoadingAnimator needs at least one message")
        self.messages = messages
        self.interval = interval
        self._task: Optional[asyncio.Task] = None
        self._start_time: Optional[float] = None

    async def __aenter__(self) -> "LoadingAnimator":
        self._start_time = time.monotonic()
        self._task = asyncio.create_task(self._animate())
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._clear_line()
        return False  # never suppress the real exception

    async def _animate(self) -> None:
        cycle = itertools.cycle(self.messages)
        try:
            while True:
                message = next(cycle)
                elapsed = time.monotonic() - (self._start_time or time.monotonic())
                line = f"{message} ({elapsed:.0f}s)"
                sys.stdout.write("\r" + line.ljust(70))
                sys.stdout.flush()
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            raise

    def _clear_line(self) -> None:
        sys.stdout.write("\r" + " " * 70 + "\r")
        sys.stdout.flush()
