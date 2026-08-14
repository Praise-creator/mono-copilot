"""
The chat-bubble loading indicator shown while an agent call is in flight --
the same "Claude-Code-style flibbertigibetting..." feel the plain-terminal
CLI already has via LoadingAnimator, just as a real chat bubble instead of a
carriage-return-animated terminal line (which would corrupt Textual's own
screen rendering if reused directly here -- confirmed during Workstream 1).

Message pools and their default rotation interval are the actual
BA_MESSAGES/PE_MESSAGES/RFC_MESSAGES from cli/loading_messages.py, imported
rather than duplicated, so both interfaces show the same phrases.
"""
import time

from textual.widgets import Static

from copilot.cli.loading_messages import BA_MESSAGES, PE_MESSAGES, RFC_MESSAGES

GENERIC_MESSAGES = ["Thinking it through...", "Working on it...", "Chewing on that..."]

_MESSAGE_POOLS = {
    "ba": BA_MESSAGES,
    "pe": PE_MESSAGES,
    "rfc": [msgs[0] for msgs in RFC_MESSAGES.values()],
    "generic": GENERIC_MESSAGES,
}

_DOT_FRAMES = ["", ".", "..", "..."]
_DOT_INTERVAL = 0.4
_MESSAGE_INTERVAL = 4.0


class LoadingBubble(Static):

    def __init__(self, stage_key: str = "generic"):
        super().__init__(classes="message loading-message")
        self._messages = _MESSAGE_POOLS.get(stage_key, GENERIC_MESSAGES)
        self._message_index = 0
        self._dot_index = 0
        self._start_time = time.monotonic()

    def on_mount(self) -> None:
        self._render_frame()
        self.set_interval(_DOT_INTERVAL, self._tick_dots)
        self.set_interval(_MESSAGE_INTERVAL, self._tick_message)

    def _tick_dots(self) -> None:
        self._dot_index = (self._dot_index + 1) % len(_DOT_FRAMES)
        self._render_frame()

    def _tick_message(self) -> None:
        self._message_index = (self._message_index + 1) % len(self._messages)
        self._render_frame()

    def _render_frame(self) -> None:
        message = self._messages[self._message_index]
        dots = _DOT_FRAMES[self._dot_index]
        elapsed = int(time.monotonic() - self._start_time)
        base = message[:-3] if message.endswith("...") else message
        self.update(f"[bold]{base}{dots}[/bold] ({elapsed}s)")
