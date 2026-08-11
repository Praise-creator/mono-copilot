from copilot.tui.state import CopilotState, Message

class StateManager:

    def __init__(self):
        self._state = CopilotState()

    @property
    def state(self) -> CopilotState:
        return self._state

    def add_message(self, role: str, content: str) -> None:
        self._state.messages.append(
            Message(role=role, content=content)
        )

    