from textual.binding import Binding
from textual.widgets import TextArea

from copilot.tui.widgets.widget_comm import UserInputSubmitted


class ComposeArea(TextArea):

    BINDINGS = [
        Binding("enter", "submit_message", "Submit", priority=True,),
        # ctrl+j is the one that works everywhere. Terminals send the same
        # bytes for Enter and Shift+Enter unless they support the enhanced
        # keyboard protocol, so on Terminal.app and iTerm2 with default
        # settings Textual never receives shift+enter and that binding can
        # never fire. Since enter is priority=True and always submits, that
        # left no way to type a multi-line message at all.
        #
        # shift+enter is kept for the terminals that do send it (Kitty,
        # WezTerm, Ghostty) rather than dropped.
        Binding("ctrl+j", "newline", "New line"),
        Binding("shift+enter", "newline", "New line"),
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
