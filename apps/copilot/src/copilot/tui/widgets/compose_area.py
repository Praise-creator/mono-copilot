from textual.binding import Binding
from textual.widgets import TextArea

from copilot.tui.widgets.widget_comm import UserInputSubmitted


class ComposeArea(TextArea):

    BINDINGS = [
        Binding("enter", "submit_message", "Submit", priority=True,),
        # ctrl+j is the one that actually works everywhere. Most terminals
        # send the same bytes for Enter and Shift+Enter, so Textual never
        # receives "shift+enter" at all and that binding silently does
        # nothing. Newer terminals that support the enhanced keyboard
        # protocol (Kitty, WezTerm, Ghostty) do send it, so it is kept for
        # them rather than removed.
        Binding("ctrl+j", "newline", "New line"),
        Binding("shift+enter", "newline", "New line (needs a terminal that sends it)"),
        Binding("ctrl+a", "select_all", "Select all"),
    ]

    def __init__(self):
        super().__init__(
            placeholder="Type your message here..."
        )

    def action_submit_message(self):
        text = self.text.strip()

        if not text:
            return

        self.post_message(UserInputSubmitted(text))
        self.text = ""

    def action_newline(self):
        self.insert("\n")

    def action_select_all(self):
        self.select_all()