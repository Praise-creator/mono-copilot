from textual.containers import VerticalScroll, Right
from textual.widgets import Static
from copilot.tui.state import CopilotState

from copilot.tui.widgets.widget_comm import StateUpdated

class ChatPane(VerticalScroll):

    def __init__(self, state: CopilotState):
        super().__init__()
        self.state = state

    def on_mount(self):
        self.refresh_messages()

    def refresh_messages(self):
        self.remove_children()

        if not self.state.messages:
            self.mount(Static("No messages yet."))
            return

        for message in self.state.messages:
            message_widget = Static(
               message.content, 
               classes= f"message {message.role.lower()}-message"
               )

    
            if message.role.lower() == "user":
                self.mount(Right(message_widget))
            else:
                self.mount(message_widget)

            self.call_after_refresh(self.scroll_end)


    def on_state_updated(self, event: StateUpdated):
        self.state = event.state
        self.refresh_messages()