from copilot.tui.state_manager import StateManager
from copilot.tui.widgets.chat_pane import ChatPane
from textual.app import App
from copilot.tui.widgets.header import CopilotHeader
from copilot.tui.widgets.main_area import MainArea
from copilot.tui.widgets.compose_area import ComposeArea
from copilot.tui.widgets.status_bar import CopilotStatusBar
from copilot.tui.widgets.sidebar import Sidebar
from copilot.tui.state import Message
from copilot.tui.widgets.widget_comm import StateUpdated, UserInputSubmitted, ProjectSelected

from copilot.orchestrator import Orchestrator
from copilot.cli.router import Router


class CopilotApp(App):
    CSS_PATH = "app.tcss"

    def __init__(self, project: str | None = None):
        super().__init__()
        self.state_manager = StateManager()
        self._initial_project = project
        self._busy = False
        self.orchestrator = None
        self.router = None

        # Router's constructor builds a ChatSkill, which itself requires a
        # real OPENAI_API_KEY and raises if one isn't set. That failure
        # must not crash the whole app before a single frame renders --
        # it needs to show up as a normal, readable message instead.
        backend_error: str | None = None
        try:
            self.orchestrator = Orchestrator()
            self.router = Router(self.orchestrator, user_id="tui-user")
        except Exception as exc:
            backend_error = str(exc)

        self.state_manager.state.active_project = project

        if backend_error:
            welcome = (
                "Mono-Copilot couldn't start the backend: "
                f"{backend_error}\n"
                "Check that OPENAI_API_KEY is set (see .env) and restart."
            )
        else:
            welcome = "Welcome to Mono-Copilot."
            if project:
                welcome += f" Resuming '{project}'..."

        self.state_manager.add_message(Message(role="Assistant", content=welcome))

    def compose(self):
        yield MainArea(self.state_manager)

    def on_mount(self) -> None:
        # Without this, focus lands on Sidebar (the first focusable widget
        # Textual finds), not the input box -- a real person launching this
        # would type, press enter, and nothing would happen, with no visible
        # reason why. Confirmed this was the actual default before fixing it.
        try:
            self.query_one(ComposeArea).focus()
        except Exception:
            pass
        if self.router is not None and self._initial_project:
            self._start_router_call(f"/resume {self._initial_project}")

    # Typed commands the app handles itself, before anything reaches Router.
    # Router has no idea what /quit means, so without this it falls through to
    # normal input handling: with a project open it is read as review feedback
    # and regenerates a document, and with no project open it reaches
    # IntakeAgent, which is a paid API call. Neither is what someone typing
    # "/quit" wants. The plain CLI has always supported these, so people
    # reasonably expect them here too.
    _EXIT_COMMANDS = ("/quit", "/exit")

    def on_user_input_submitted(self, event: UserInputSubmitted):
        if event.text.strip().lower() in self._EXIT_COMMANDS:
            self.exit()
            return

        if self._busy:
            return
        self.state_manager.add_message(Message(role="User", content=event.text))
        self._refresh_chat_pane()

        if self.router is None:
            self.state_manager.add_message(
                Message(role="Assistant", content="Backend isn't available. Fix the startup error above and restart.")
            )
            self._refresh_chat_pane()
            return

        self._start_router_call(event.text)

    def on_project_selected(self, event: ProjectSelected) -> None:
        # Clicking a project should feel exactly like typing /switch <name>
        # -- same visible "User: /switch ..." bubble for context, same
        # busy-guard, same backend-not-available handling -- not a second,
        # separate implementation of switching that could quietly drift
        # from the one already tested.
        if self.router is not None and event.project_name == self.router.active_project:
            return
        self.on_user_input_submitted(UserInputSubmitted(f"/switch {event.project_name}"))

    def _start_router_call(self, text: str) -> None:
        self.run_worker(self._run_router(text), exclusive=True, group="router")

    async def _run_router(self, text: str) -> None:
        self._set_busy(True)
        self._refresh_chat_pane()
        try:
            result = await self.router.handle_input(text)
            self.state_manager.add_message(Message(role="Assistant", content=result.message))
        except Exception as exc:
            # Deliberately broad: a worker exception must never crash the
            # whole TUI. Any failure (network, a bug in Router we haven't
            # foreseen, anything) surfaces as a message instead, and the
            # app stays usable for the next turn.
            self.state_manager.add_message(
                Message(role="Assistant", content=f"Something went wrong talking to the backend: {exc}")
            )
        finally:
            self._set_busy(False)
            self._refresh_chat_pane()
            self._sync_workspace_display()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.state_manager.state.loading = busy
        try:
            self.query_one(ComposeArea).disabled = busy
        except Exception:
            pass
        self._refresh_status_bar_widget()

    def _refresh_chat_pane(self) -> None:
        chat_pane = self.query_one(ChatPane)
        chat_pane.post_message(StateUpdated(self.state_manager.state))
        # ChatPane's own refresh (remove_children + remount, to render the
        # new message) silently steals focus from ComposeArea every single
        # time this runs -- not just once at launch, which is what the
        # earlier on_mount fix assumed. Confirmed happening on every second
        # message in a real session, not merely the first one: without
        # this, a real person would need to click back into the input box
        # after every single exchange, forever, not just once at startup.
        self.call_after_refresh(self._refocus_compose_area)

    def _refocus_compose_area(self) -> None:
        try:
            self.query_one(ComposeArea).focus()
        except Exception:
            pass

    def _sync_workspace_display(self) -> None:
        # Keeps the header and status bar honest for the whole session, not
        # just at launch. CopilotHeader only reads active_project once, at
        # construction time -- with no fix here, a session that starts
        # without --project, then creates a brand new one through the
        # intake flow, would show "No Active Project" forever even once a
        # real project genuinely exists.
        project = self.router.active_project if self.router else None
        stage = None
        run_count = None
        if project and self.orchestrator:
            session = self.orchestrator.context_manager.get_session(project)
            if session:
                stage = session.get("stage")
                run_count = session.get("run_count")

        self.state_manager.state.active_project = project
        self.state_manager.state.workflow_stage = stage
        if run_count is not None:
            self.state_manager.state.run_count = run_count

        try:
            self.query_one(CopilotHeader).update(project or "No Active Project")
        except Exception:
            pass
        try:
            self.query_one(Sidebar).refresh_projects()
        except Exception:
            pass
        self._refresh_status_bar_widget()

    def _refresh_status_bar_widget(self) -> None:
        try:
            self.query_one(CopilotStatusBar).refresh()
        except Exception:
            pass