from textual.containers import Horizontal

from copilot.tui.widgets.workspace import Workspace
import copilot.tui.widgets.sidebar 


class MainArea(Horizontal):
    def __init__(self, state_manager):
        super().__init__()
        self.state_manager = state_manager 

    def compose(self):
        yield copilot.tui.widgets.sidebar.Sidebar(self.state_manager)
        yield Workspace(self.state_manager)
