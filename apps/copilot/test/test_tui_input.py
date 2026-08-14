#!/usr/bin/env python3
"""
Input handling and worker lifecycle in the terminal app.

Run from the repo root:

    uv run --package copilot python3 apps/copilot/test/test_tui_input.py

No API key needed, no network. Router is stubbed throughout.

Covers #27, #28 and #30, all found in a walkthrough rather than by a test,
which is why they are written down here.

  #27  /quit did not quit. It went to Router, which has never known that
       command, so with a project open it was read as review feedback and
       regenerated a document, and with none open it reached IntakeAgent,
       which is a paid API call.
  #28  No key made a new line. enter is priority and always submits, and
       shift+enter cannot fire on terminals that send the same bytes for
       both, which is the default on Terminal.app and iTerm2.
  #30  Quitting during a generation raised out of the worker, because the
       finally block touched widgets that were already gone.

The thing worth protecting most is that /quit must never reach Router. A
regression there costs money quietly rather than failing loudly.
"""

import asyncio
import sys
from unittest.mock import AsyncMock

from _offline import bootstrap, Checks

bootstrap()

from copilot.tui.app import CopilotApp
from copilot.tui.widgets.compose_area import ComposeArea
from copilot.cli.router import RouterResult

check = Checks()


class RecordingRouter:
    """Stands in for Router and remembers everything it was asked to handle."""

    def __init__(self, delay: float = 0.0):
        self.seen = []
        self._delay = delay
        self.active_project = None

    def list_resumable_projects(self):
        return []

    async def handle_input(self, text: str) -> RouterResult:
        self.seen.append(text)
        if self._delay:
            await asyncio.sleep(self._delay)
        return RouterResult(kind="message", message=f"echo: {text}")


async def submit(app, pilot, text: str, settle: int = 6):
    """Type `text` into the box and send it, the way a person would."""
    area = app.query_one(ComposeArea)
    area.focus()
    await pilot.pause()
    area.text = text
    area.action_submit_message()
    for _ in range(settle):
        await pilot.pause()


async def main():
    check.section("[1] /quit and /exit close the app without reaching Router (#27)")
    for command in ("/quit", "/exit", "/QUIT", "  /quit  ", "/Exit"):
        app = CopilotApp()
        router = RecordingRouter()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.router = router
            await submit(app, pilot, command, settle=3)
        check(f"{command!r} never reached Router", router.seen == [], str(router.seen))

    check.section("[2] text that merely contains 'quit' is still normal input (#27)")
    for command in ("/quitter", "quit", "quit the project", "please /quit later"):
        app = CopilotApp()
        router = RecordingRouter()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.router = router
            await submit(app, pilot, command)
        check(f"{command!r} went to Router as usual", router.seen == [command], str(router.seen))

    check.section("[3] ordinary input still reaches Router and comes back (#27)")
    app = CopilotApp()
    router = RecordingRouter()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.router = router
        await submit(app, pilot, "a business idea about upsell")
        replies = [m.content for m in app.state_manager.state.messages]
    check("Router saw it", router.seen == ["a business idea about upsell"])
    check("the reply was rendered", any("echo: a business idea" in r for r in replies), str(replies))

    check.section("[4] ctrl+j makes a new line, enter still submits (#28)")
    app = CopilotApp()
    router = RecordingRouter()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.router = router
        area = app.query_one(ComposeArea)
        area.focus()
        await pilot.pause()
        await pilot.press("a")
        await pilot.press("ctrl+j")
        await pilot.press("b")
        await pilot.pause()
        typed = area.text
        await pilot.press("enter")
        for _ in range(6):
            await pilot.pause()
        # Read while the app is still up. Querying after the run_test block
        # exits raises NoMatches, since the widgets are gone by then.
        cleared = area.text == ""
    check("ctrl+j inserted a real newline", typed == "a\nb", repr(typed))
    check("enter submitted the multi-line text", router.seen == ["a\nb"], str(router.seen))
    check("the box was cleared after sending", cleared)

    check.section("[5] shift+enter still works where the terminal sends it (#28)")
    # Pilot delivers the key directly, so this checks the binding rather than
    # the terminal. Kitty, WezTerm and Ghostty do send it; Terminal.app and
    # iTerm2 on defaults do not, which is why ctrl+j exists.
    app = CopilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        area = app.query_one(ComposeArea)
        area.focus()
        await pilot.pause()
        await pilot.press("x")
        await pilot.press("shift+enter")
        await pilot.press("y")
        await pilot.pause()
        text = area.text
    check("shift+enter still bound to newline", text == "x\ny", repr(text))

    check.section("[6] ctrl+a still selects all (#28 did not disturb it)")
    app = CopilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        area = app.query_one(ComposeArea)
        area.focus()
        area.text = "some text"
        await pilot.pause()
        await pilot.press("ctrl+a")
        await pilot.pause()
        check("selection is not empty", area.selected_text == "some text", repr(area.selected_text))

    check.section("[7] quitting during a generation does not raise (#30)")
    raised = None
    app = CopilotApp()
    try:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.router = RecordingRouter(delay=3.0)
            await submit(app, pilot, "something slow", settle=1)
            app.exit()
            await pilot.pause()
    except Exception as exc:
        raised = exc
    check("no exception on quit mid-generation", raised is None,
          f"{type(raised).__name__}: {raised}" if raised else "")

    check.section("[8] a turn that finishes normally still updates the screen (#30)")
    app = CopilotApp()
    router = RecordingRouter()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.router = router
        await submit(app, pilot, "hello")
        messages = [m.content for m in app.state_manager.state.messages]
        busy_after = app._busy
    check("reply rendered", any("echo: hello" in m for m in messages), str(messages))
    check("busy flag cleared", busy_after is False)

    check.section("[9] a Router failure still becomes a message, not a crash (#30)")
    app = CopilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        class BrokenRouter:
            active_project = None
            def list_resumable_projects(self): return []
            async def handle_input(self, text):
                raise RuntimeError("backend exploded")

        app.router = BrokenRouter()
        await submit(app, pilot, "anything")
        messages = [m.content for m in app.state_manager.state.messages]
        still_usable = app._busy is False
    check("failure surfaced as a message", any("backend exploded" in m for m in messages), str(messages))
    check("app still usable afterwards", still_usable)


asyncio.run(main())
sys.exit(check.report())
