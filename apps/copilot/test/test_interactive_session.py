#!/usr/bin/env python3
"""
Interactive session — the continuous, resumable version of the idea -> BRD
-> PRD -> RFCs -> export flow, all in one running program instead of
separate demo scripts.

This is a thin rendering loop over cli/router.py. Everything that decides
what happens next lives in Router; this file only reads input, shows a
loading animation while Router works, and prints whatever RouterResult
comes back. A real TUI replaces this file, not router.py.

Run from the repo root:

    uv run --package copilot python3 apps/copilot/test/test_interactive_session.py

Type a business idea to start a new project. Type an existing project name
to resume it — including across restarts, since sessions now persist to
projects/{name}/.session.json. Commands: /new, /switch <name>, /quit.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

from copilot.orchestrator import Orchestrator
from copilot.cli.router import Router
from copilot.cli.loading_messages import LoadingAnimator, BA_MESSAGES, PE_MESSAGES, RFC_MESSAGES


GENERIC_MESSAGES = ["Thinking it through...", "Working on it...", "Chewing on that..."]


def _pick_loading_messages(router: Router) -> list:
    """Best-effort guess at which stage is about to run, purely to pick a
    fitting loading message — peeks at current session state before the
    call. Falls back to a generic set whenever the stage can't be inferred
    (no active project yet, or a project just switched)."""
    if router.active_project is None:
        return GENERIC_MESSAGES
    session = router.orchestrator.context_manager.get_session(router.active_project)
    if not session:
        return GENERIC_MESSAGES
    stage = session.get("stage", "")
    if stage.startswith("ba"):
        return BA_MESSAGES
    if stage.startswith("pe"):
        return PE_MESSAGES
    if stage.startswith("rfc"):
        return [msgs[0] for msgs in RFC_MESSAGES.values()]
    return GENERIC_MESSAGES


async def main():
    print("Mono-Copilot — interactive session")
    print("Type a business idea to start a new project, or an existing project name to resume it.")
    print("Commands: /new (start fresh), /switch <name> (switch project), /quit\n")

    orchestrator = Orchestrator()
    router = Router(orchestrator, user_id="kb-interactive")

    resumable = router.list_resumable_projects()
    if resumable:
        print(f"Resumable projects: {', '.join(resumable)}\n")

    while True:
        try:
            user_input = input("> ").strip()
        except EOFError:
            print("\nNo more input — exiting.")
            return

        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit"):
            print("Session ended. Progress is saved — name this project again anytime to resume.")
            return

        messages = _pick_loading_messages(router)
        async with LoadingAnimator(messages):
            result = await router.handle_input(user_input)

        print()
        print(result.message)
        if result.kind == "export_ready":
            print("(Open the PDF path(s) above to view.)")
        print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except EOFError:
        print("\nNo more input — exiting.")
    except KeyboardInterrupt:
        print("\nInterrupted — exiting. Progress is saved.")
