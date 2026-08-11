from textual.widgets import Input
from copilot.tui.widgets.widget_comm import UserInputSubmitted

class ComposeArea(Input):

    def __init__(self):
        super().__init__(placeholder="Type your message here...")

    def on_input_submitted(self, event):
        self.post_message(UserInputSubmitted(event.value))
        self.value = ""