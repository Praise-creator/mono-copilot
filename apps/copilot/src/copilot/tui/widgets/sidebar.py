from pathlib import Path

from textual.containers import VerticalScroll, Horizontal
from textual.widgets import Static, Button
from copilot.cli.widgets import MTNBadge
from copilot.cli.entry_classifier import list_projects_on_disk
from copilot.tui.widgets.widget_comm import ProjectSelected

# Measured against the real, worst-case rendering, not an idealized one:
# with enough projects to trigger the list's own scrollbar (which the first
# pass at this measurement didn't account for -- confirmed via a real 24-
# character name still wrapping to 2 lines despite fitting the earlier,
# scrollbar-free measurement), 23 characters is the actual limit before
# Textual's Button grows in height rather than truncating. 20 leaves real
# margin below that rather than sitting right at the edge.
_MAX_DISPLAY_LEN = 20


def _display_name(name: str) -> str:
    if len(name) <= _MAX_DISPLAY_LEN:
        return name
    return name[: _MAX_DISPLAY_LEN - 1] + "…"


class Sidebar(VerticalScroll):

    def __init__(self, state_manager):
        super().__init__()
        self.state_manager = state_manager

    def compose(self):
        yield Horizontal(
            MTNBadge(id="mtn-badge"),
            Static("MONO-COPILOT", classes="sidebar-title"),
            classes="brand-row"
        )

        yield Static("+ New Chat", classes="new-chat")
        yield Static("Projects", classes="sidebar-section")
        yield VerticalScroll(id="project-list-container")

    def on_mount(self) -> None:
        self.refresh_projects()

    def refresh_projects(self) -> None:
        # Real, clickable bubbles now, not static bullet-point text. Each
        # one carries the FULL real project name separately from its
        # (possibly truncated) display label, and posts ProjectSelected on
        # press with the real name -- a long name being shortened for
        # display must never switch to the wrong project.
        container = self.query_one("#project-list-container")
        container.remove_children()

        active = self.state_manager.state.active_project
        projects = list_projects_on_disk(Path("projects"))

        if not projects:
            container.mount(Static("  (no projects yet)", classes="sidebar-item"))
            return

        for name in projects:
            is_active = name == active
            classes = "sidebar-project-button current-project" if is_active else "sidebar-project-button"
            button = Button(_display_name(name), compact=True, classes=classes)
            button.project_name = name
            container.mount(button)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        project_name = getattr(event.button, "project_name", None)
        if project_name is None:
            return
        self.post_message(ProjectSelected(project_name))
