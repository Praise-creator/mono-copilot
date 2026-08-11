from textual.widgets import Static
from copilot.tui.state import CopilotState

from copilot.tui.widgets.widget_comm import StateUpdated

class ChatPane(Static):

    def __init__(self, state: CopilotState):
        super().__init__()
        self.state = state

    def on_mount(self):
        self.refresh_messages()

    def refresh_messages(self):
        if not self.state.messages:
            self.update("No messages yet.")
            return

        self.update(
            "\n\n".join(
                f"{m.role}: {m.content}"
                for m in self.state.messages
            )
        )

    def on_state_updated(self, event: StateUpdated):
        self.state = event.state
        self.refresh_messages()