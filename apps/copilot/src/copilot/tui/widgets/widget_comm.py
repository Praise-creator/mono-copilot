from textual.message import Message
from copilot.tui.state import CopilotState

class UserInputSubmitted(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text

class StateUpdated(Message):
    def __init__(self, state: CopilotState) -> None:
        super().__init__()
        self.state = state