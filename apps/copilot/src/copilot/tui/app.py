from copilot.tui.state_manager import StateManager
from copilot.tui.widgets.chat_pane import ChatPane
from textual.app import App
from copilot.tui.widgets.header import CopilotHeader
from copilot.tui.widgets.main_area import MainArea
from copilot.tui.widgets.compose_area import ComposeArea
from copilot.tui.widgets.status_bar import CopilotStatusBar
from copilot.tui.state import Message
from copilot.tui.widgets.widget_comm import StateUpdated, UserInputSubmitted

class CopilotApp(App):
    CSS_PATH = "app.tcss"
    def __init__(self):
        super().__init__()
        self.state_manager = StateManager()
        self.state_manager.add_message(Message(role="Assistant", content="Welcome to Mono-Copilot."))
        

    def on_user_input_submitted(self, event: UserInputSubmitted):
        self.state_manager.add_message(Message(role="User", content=event.text))

        chat_pane = self.query_one(ChatPane)

        chat_pane.post_message(
            StateUpdated(self.state_manager.state)
)

    def compose(self):
        yield CopilotHeader()
        yield MainArea(self.state_manager)
        yield ComposeArea()
        yield CopilotStatusBar()