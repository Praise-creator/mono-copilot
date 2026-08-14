from textual.containers import Vertical

from copilot.tui.widgets.chat_pane import ChatPane
from copilot.tui.widgets.compose_area import ComposeArea
from copilot.tui.widgets.header import CopilotHeader
from copilot.tui.widgets.status_bar import CopilotStatusBar


class Workspace(Vertical):

    def __init__(self, state_manager):
        super().__init__()
        self.state_manager = state_manager

    def compose(self):
        yield CopilotHeader(self.state_manager.state.active_project)
        yield ChatPane(self.state_manager.state)
        yield ComposeArea()
        yield CopilotStatusBar(self.state_manager.state)