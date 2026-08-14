from textual.binding import Binding
from textual.widgets import TextArea

from copilot.tui.widgets.widget_comm import UserInputSubmitted


class ComposeArea(TextArea):

    BINDINGS = [
        Binding("enter", "submit_message", "Submit", priority=True,),
        Binding("shift+enter", "newline", "New line",),
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
