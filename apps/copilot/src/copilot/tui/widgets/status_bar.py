from textual.widgets import Static

class CopilotStatusBar(Static):

    def __init__(self):
        super().__init__("Status: Ready")