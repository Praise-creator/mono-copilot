#!/usr/bin/env python3
"""
Tests for the Textual TUI (tui/app.py and its widgets) -- app boot, and the
real behavioural bugs found and fixed while wiring the TUI to the real
backend this session, driven through Textual's own Pilot test harness
rather than reasoning about the code by eye.

Run from the repo root:

    uv run --package copilot python3 apps/copilot/test/test_tui.py

No API key needed for most sections -- Router.handle_input is stubbed at
the app level, same pattern as everywhere else in this suite. The one
section that constructs a real Router (missing-API-key handling) needs no
key either, since that is the exact case it's testing.

THE ONE TEST THAT MATTERS MOST
------------------------------
Section 3. Before this session, keyboard focus silently moved from the
input box to the chat pane every time a response rendered -- not just
once at launch, on every single turn. A real person would need to click
back into the input box after every single message, forever. If this
section ever goes red, that's back.
"""

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

from _offline import bootstrap, Checks

bootstrap()

from copilot.tui.app import CopilotApp
from copilot.tui.widgets.compose_area import ComposeArea
from copilot.tui.widgets.chat_pane import ChatPane
from copilot.tui.widgets.header import CopilotHeader
from copilot.tui.widgets.status_bar import CopilotStatusBar
from copilot.tui.widgets.sidebar import Sidebar
from copilot.tui.widgets.loading_bubble import LoadingBubble
from copilot.cli.router import RouterResult
from textual.widgets import Static, Button

check = Checks()


def chat_text(app) -> str:
    pane = app.query_one(ChatPane)
    return "\n".join(str(s.content) for s in pane.query(Static))


def in_temp_projects_dir():
    """Returns a context manager-like pair (enter/exit) for chdir'ing into
    a throwaway directory -- used as a plain function here rather than a
    real contextmanager since every section below is already inside its
    own async function."""
    original_cwd = Path.cwd()
    tmp = Path(tempfile.mkdtemp())
    import os
    os.chdir(tmp)
    return original_cwd, tmp


def cleanup(original_cwd, tmp):
    import os
    os.chdir(original_cwd)
    shutil.rmtree(tmp, ignore_errors=True)


async def test_boots_with_every_expected_widget_present():
    check.section("[1] app boots cleanly with the full real layout, nothing missing")
    original_cwd, tmp = in_temp_projects_dir()
    try:
        app = CopilotApp()
        async with app.run_test() as pilot:
            check("Sidebar present", app.query_one(Sidebar) is not None)
            check("CopilotHeader present", app.query_one(CopilotHeader) is not None)
            check("ChatPane present", app.query_one(ChatPane) is not None)
            check("ComposeArea present", app.query_one(ComposeArea) is not None)
            check("CopilotStatusBar present", app.query_one(CopilotStatusBar) is not None)
            check("welcome message shown", "Welcome to Mono-Copilot" in chat_text(app))
    finally:
        cleanup(original_cwd, tmp)


async def test_missing_api_key_degrades_gracefully_instead_of_crashing():
    check.section("[2] no OPENAI_API_KEY at all -- must not crash, must say why clearly")
    import os
    saved = os.environ.pop("OPENAI_API_KEY", None)
    original_cwd, tmp = in_temp_projects_dir()
    try:
        app = CopilotApp()
        async with app.run_test() as pilot:
            check("router is None rather than a half-built object", app.router is None)
            compose = app.query_one(ComposeArea)
            compose.text = "hello"
            await pilot.press("enter")
            await pilot.pause()
            check("clear message shown, no crash", "Backend isn't available" in chat_text(app))
    finally:
        cleanup(original_cwd, tmp)
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved


async def test_focus_returns_to_input_after_every_turn_not_just_the_first():
    check.section("[3] keyboard focus returns to the input box after EVERY turn, not just once at launch")
    original_cwd, tmp = in_temp_projects_dir()
    try:
        app = CopilotApp()
        app.router.handle_input = AsyncMock(return_value=RouterResult(kind="message", message="ok", active_project=None))
        async with app.run_test() as pilot:
            compose = app.query_one(ComposeArea)
            check("focused on launch", app.focused is compose)

            compose.text = "first message"
            await pilot.press("enter")
            await pilot.pause(0.1)
            check("focus survives the FIRST turn", app.focused is compose)

            compose.text = "second message"
            await pilot.press("enter")
            await pilot.pause(0.1)
            check("focus survives the SECOND turn too -- this is the one that broke before the fix",
                  app.focused is compose)

            compose.text = "third message"
            await pilot.press("enter")
            await pilot.pause(0.1)
            check("focus survives a third turn as well", app.focused is compose)
    finally:
        cleanup(original_cwd, tmp)


async def test_normal_turn_end_to_end():
    check.section("[4] a normal turn: message bubble, busy-disable, response, live status bar and header")
    original_cwd, tmp = in_temp_projects_dir()
    try:
        app = CopilotApp()
        app.orchestrator.context_manager.init_session("demo", "tui-user", "a real problem")
        app.orchestrator.context_manager.update_session("demo", "stage", "ba_approval")
        app.orchestrator.context_manager.update_session("demo", "run_count", 1)
        app.router.active_project = "demo"
        app.router.handle_input = AsyncMock(return_value=RouterResult(
            kind="document_ready", message="BRD ready -> projects/demo/markdown/ba-output.md", active_project="demo",
        ))

        async with app.run_test() as pilot:
            compose = app.query_one(ComposeArea)
            compose.text = "reduce churn in Nigeria"
            await pilot.press("enter")
            await pilot.pause(0.05)
            check("user message renders immediately", "reduce churn in Nigeria" in chat_text(app))

            await pilot.pause(0.1)
            check("assistant response renders", "BRD ready" in chat_text(app))
            check("input re-enabled after completion", compose.disabled is False)
            check("header shows the active project", "demo" in str(app.query_one(CopilotHeader).content))
            status_text = app.query_one(CopilotStatusBar).render()
            check("status bar reflects real stage and run count", "ba_approval" in status_text and "1" in status_text, status_text)
    finally:
        cleanup(original_cwd, tmp)


async def test_backend_exception_never_crashes_the_app():
    check.section("[5] an exception from Router must surface as a message, never crash the app")
    original_cwd, tmp = in_temp_projects_dir()
    try:
        app = CopilotApp()
        async def failing(text):
            raise ConnectionError("simulated network failure")
        app.router.handle_input = failing

        async with app.run_test() as pilot:
            compose = app.query_one(ComposeArea)
            compose.text = "will this crash"
            await pilot.press("enter")
            await pilot.pause(0.1)
            check("error surfaces as a normal message", "Something went wrong" in chat_text(app))
            check("input re-enabled, app stays usable", compose.disabled is False)
    finally:
        cleanup(original_cwd, tmp)


async def test_loading_bubble_appears_animates_and_clears():
    check.section("[6] the loading bubble appears immediately, animates, and disappears once the real response lands")
    original_cwd, tmp = in_temp_projects_dir()
    try:
        app = CopilotApp()
        import asyncio
        async def slow_handle_input(text):
            await asyncio.sleep(1.0)
            return RouterResult(kind="message", message="done", active_project=None)
        app.router.handle_input = slow_handle_input

        async with app.run_test() as pilot:
            compose = app.query_one(ComposeArea)
            compose.text = "go"
            await pilot.press("enter")
            await pilot.pause(0.05)

            bubbles = app.query_one(ChatPane).query(LoadingBubble)
            check("bubble appears immediately", len(bubbles) == 1)
            frame_1 = str(bubbles.first().content)

            await pilot.pause(0.5)
            frame_2 = str(app.query_one(ChatPane).query(LoadingBubble).first().content)
            check("dots genuinely animate over time", frame_1 != frame_2, f"{frame_1!r} vs {frame_2!r}")

            await pilot.pause(0.8)
            check("bubble is gone once the real response arrives",
                  len(app.query_one(ChatPane).query(LoadingBubble)) == 0)
            check("real response shown instead", "done" in chat_text(app))
    finally:
        cleanup(original_cwd, tmp)


async def test_sidebar_lists_real_projects_and_stays_current():
    check.section("[7] sidebar lists real projects from disk, marks the active one, updates live")
    original_cwd, tmp = in_temp_projects_dir()
    try:
        app = CopilotApp()
        app.orchestrator.file_manager.save_brd("Falcon", "# BRD")
        app.orchestrator.context_manager.init_session("Falcon", "x", "y")
        app.orchestrator.file_manager.save_brd("Liason", "# BRD")
        app.orchestrator.context_manager.init_session("Liason", "x", "y")

        # active_project deliberately left as None until the click happens
        # below -- pre-setting it to "Falcon" first would make app.py's own
        # "already the active project, do nothing" guard correctly suppress
        # the switch, and the assertions would then pass for the wrong
        # reason (because the value was set by hand, not by the click).
        async def fake_switch(text):
            app.router.active_project = "Falcon"
            return RouterResult(kind="resumed", message="Resumed 'Falcon'", active_project="Falcon")

        async with app.run_test() as pilot:
            sidebar = app.query_one(Sidebar)
            buttons = list(sidebar.query(Button))
            check("both real projects listed", len(buttons) == 2)

            app.router.handle_input = fake_switch

            falcon_button = [b for b in buttons if "Falcon" in str(b.label)][0]
            await pilot.click(falcon_button)
            await pilot.pause(0.2)

            check("clicking switched to the real project", app.router.active_project == "Falcon")
            check("visible bubble shown, same as typing /switch would produce",
                  "/switch Falcon" in chat_text(app))
            falcon_after = [b for b in app.query_one(Sidebar).query(Button) if "Falcon" in str(b.label)][0]
            check("active project marked in the sidebar", "current-project" in falcon_after.classes)
    finally:
        cleanup(original_cwd, tmp)


async def test_long_project_names_truncate_instead_of_wrapping():
    check.section("[8] a genuinely long project name stays on one line in the sidebar, truncated rather than wrapped")
    original_cwd, tmp = in_temp_projects_dir()
    try:
        app = CopilotApp()
        # 40 filler projects, matching the real condition that exposed this
        # bug: the sidebar's own scrollbar appears once there are enough
        # projects, and that scrollbar eats width an idealized (scrollbar
        # free) measurement would miss entirely.
        for i in range(40):
            name = f"filler-project-{i}"
            app.orchestrator.file_manager.save_brd(name, "# x")
            app.orchestrator.context_manager.init_session(name, "x", "y")
        long_name = "AI_IVR_Integration_VOICE"
        app.orchestrator.file_manager.save_brd(long_name, "# x")
        app.orchestrator.context_manager.init_session(long_name, "x", "y")

        async with app.run_test(size=(120, 40)) as pilot:
            sidebar = app.query_one(Sidebar)
            target = [b for b in sidebar.query(Button) if b.project_name == long_name][0]
            check("stays on one line even with a real scrollbar present", target.region.height == 3, target.region.height)
            check("label is genuinely truncated, not the full name", str(target.label) != long_name)
            check("clicking it would still switch to the FULL, correct name",
                  target.project_name == long_name)
    finally:
        cleanup(original_cwd, tmp)


async def main():
    await test_boots_with_every_expected_widget_present()
    await test_missing_api_key_degrades_gracefully_instead_of_crashing()
    await test_focus_returns_to_input_after_every_turn_not_just_the_first()
    await test_normal_turn_end_to_end()
    await test_backend_exception_never_crashes_the_app()
    await test_loading_bubble_appears_animates_and_clears()
    await test_sidebar_lists_real_projects_and_stays_current()
    await test_long_project_names_truncate_instead_of_wrapping()


import asyncio
asyncio.run(main())
sys.exit(check.report())
