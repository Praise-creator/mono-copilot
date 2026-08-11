"""Standalone preview for reviewing the MTN badge before wiring it into the
real chat app.

Run it directly from apps/copilot/:
    uv run --package copilot python test/mtn_badge_demo.py

Press 'b' to toggle busy mode and see the faster rim-pulse/verb rotation
used during OpenAI calls. Press 'q' to quit.
"""

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from copilot.cli.widgets import MTNBadge


class MTNBadgeDemo(App):
    CSS = """
    MTNBadge {
        dock: right;
        margin: 1 2;
    }
    """
    BINDINGS: ClassVar = [("b", "toggle_busy", "Toggle busy"), ("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield MTNBadge(id="mtn-badge")
        yield Footer()

    def action_toggle_busy(self) -> None:
        badge = self.query_one(MTNBadge)
        badge.busy = not badge.busy


if __name__ == "__main__":
    MTNBadgeDemo().run()
