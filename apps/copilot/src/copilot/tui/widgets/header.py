from textual.widgets import Static

class CopilotHeader(Static):

    def __init__(self, active_project: str | None=None):
        title = active_project or "No Active Project"
        super().__init__(title)