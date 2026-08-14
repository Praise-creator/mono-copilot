from textual.widgets import Static

class CopilotStatusBar(Static):

    def __init__(self, state):
        self.state = state
        super().__init__()

    def render(self):
        stage = self.state.workflow_stage or "Idle"
        run = self.state.run_count

        status = "Processing..." if self.state.loading else "✓ Ready"

        return f"● {stage}  •  Run {run}                                                              {status}"
