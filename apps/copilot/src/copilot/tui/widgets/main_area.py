from textual.containers import Container;
from copilot.tui.widgets.chat_pane import ChatPane 

class MainArea(Container):
    def __init__(self, state):
        super().__init__()
        self.state_manager = state

    def compose(self):
            yield ChatPane(self.state_manager.messages)