from copilot.tui.state_manager import StateManager
from textual.app import App
from copilot.tui.widgets.header import CopilotHeader
from copilot.tui.widgets.main_area import MainArea
from copilot.tui.widgets.compose_area import ComposeArea
from copilot.tui.widgets.status_bar import CopilotStatusBar
from copilot.tui.state import CopilotState, Message
from copilot.tui.widgets.widget_comm import UserInputSubmitted
from textual.reactive import reactive

class CopilotApp(App):
    CSS_PATH = "app.tcss"
    messages = reactive([])
    def __init__(self):
        super().__init__()
        self.state_manager = StateManager()
        new_message = Message(
                role="Assistant", 
                content="Welcome to Mono-Copilot.")
        self.messages.append(new_message)
        self.messages = self.state_manager.state.messages.copy()

    def on_user_input_submitted(self, event: UserInputSubmitted):
        self.state_manager.add_message(role="User", content=event.text)
        self.messages = self.state_manager.state.messages.copy()

    def compose(self):
        yield CopilotHeader()
        yield MainArea(self.state_manager.state)
        yield ComposeArea()
        yield CopilotStatusBar()