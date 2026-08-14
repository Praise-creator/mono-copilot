from textual.containers import VerticalScroll, Horizontal
from textual.widgets import Static
from copilot.cli.widgets import MTNBadge

class Sidebar(VerticalScroll):

    def compose(self):
        yield Horizontal(
            MTNBadge(id="mtn-badge"),
            Static("MONO-COPILOT", classes="sidebar-title"),
            classes="brand-row"
        )
        
        yield Static("+ New Chat", classes="new-chat")
        yield Static("Projects", classes="sidebar-section")
        yield Static("  • Current Project", classes="Current-Project")
        yield Static("  • Previous", classes="sidebar-subsection")