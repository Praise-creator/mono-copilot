import re

from textual.containers import VerticalScroll, Right
from textual.widgets import Static
from copilot.tui.state import CopilotState

from copilot.tui.widgets.widget_comm import StateUpdated
from copilot.tui.widgets.loading_bubble import LoadingBubble

# TUI-only display styling. Deliberately not touched in orchestrator.py --
# that text is shared with the plain-terminal CLI and the HTTP API, where
# literal [bold] Rich markup would show up as ugly bracket text instead of
# actual bold. This only reformats what's already been rendered here for
# display, never the underlying message content itself.
_AWAITING_APPROVAL_RE = re.compile(r"(Awaiting approval[^.]*\.)")
_APPROVE_WORD_RE = re.compile(r"\b(approve)\b", re.IGNORECASE)


def _style_for_display(text: str) -> str:
    text = _AWAITING_APPROVAL_RE.sub(r"[bold]\1[/bold]", text)
    text = _APPROVE_WORD_RE.sub(r"[bold]\1[/bold]", text)
    return text


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
            content = message.content
            if message.role.lower() == "assistant":
                content = _style_for_display(content)

            message_widget = Static(
               content, 
               classes= f"message {message.role.lower()}-message"
               )

    
            if message.role.lower() == "user":
                self.mount(Right(message_widget))
            else:
                self.mount(message_widget)

            self.call_after_refresh(self.scroll_end)

        if self.state.loading:
            self.mount(LoadingBubble(stage_key=self._current_stage_key()))
            self.call_after_refresh(self.scroll_end)

    def _current_stage_key(self) -> str:
        stage = self.state.workflow_stage or ""
        if stage.startswith("ba"):
            return "ba"
        if stage.startswith("pe"):
            return "pe"
        if stage.startswith("rfc"):
            return "rfc"
        return "generic"

    def on_state_updated(self, event: StateUpdated):
        self.state = event.state
        self.refresh_messages()