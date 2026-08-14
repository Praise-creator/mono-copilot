#!/usr/bin/env python3
"""
Tests for cli/__main__.py's argparse structure and cli/commands.py's actual
behaviour -- the `mono` entrypoint's non-interactive surface (projects,
show, start, approve, feedback, chat), as opposed to the TUI or the
plain-terminal interactive session.

Run from the repo root:

    uv run --package copilot python3 apps/copilot/test/test_command_parser.py

No API key needed for the parser and dry-run sections. Sections that touch
approve/feedback stub the actual BA/PE agent calls, same as
test_chat_routing.py stubs ChatSkill's model call -- no network, no spend.

THE ONE TEST THAT MATTERS MOST
------------------------------
Section 6. `mono chat --project X` is meant to open the TUI directly into
project X's existing state, not a fresh, disconnected session -- this is
the one command whose whole point is continuity with everything else in
this repo (context_manager.py's disk persistence, router.py's /switch path).
If this test ever fails, --project silently became decorative.
"""

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from _offline import bootstrap, Checks

bootstrap()

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "copilot" / "cli"))
import importlib
main_module = importlib.import_module("copilot.cli.__main__")

from copilot.cli import commands
from copilot.services.context_manager import ContextManager
from copilot.services.file_manager import FileManager

check = Checks()


def parse(argv):
    old_argv = sys.argv
    sys.argv = ["mono"] + argv
    try:
        return main_module.parse_args()
    finally:
        sys.argv = old_argv


def in_temp_projects_dir(fn):
    original_cwd = Path.cwd()
    tmp = Path(tempfile.mkdtemp())
    try:
        import os
        os.chdir(tmp)
        return fn()
    finally:
        import os
        os.chdir(original_cwd)
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    check.section("[1] projects -- no arguments needed")
    args = parse(["projects"])
    check("cmd recognized", args.cmd == "projects")

    check.section("[2] show -- requires a valid 'what' and a project")
    args = parse(["show", "brd", "--project", "demo"])
    check("what=brd accepted", args.what == "brd")
    check("project captured", args.project == "demo")
    for bad_what in ("rfc", "adr", "everything"):
        try:
            parse(["show", bad_what, "--project", "demo"])
            check(f"'{bad_what}' should have been rejected", False)
        except SystemExit:
            check(f"invalid what '{bad_what}' rejected by argparse", True)
    try:
        parse(["show", "brd"])
        check("missing --project should have been rejected", False)
    except SystemExit:
        check("missing --project is rejected", True)

    check.section("[3] start -- problem is required, segment and dry-run are optional")
    args = parse(["start", "--project", "demo", "--problem", "reduce churn"])
    check("segment defaults to empty string", args.segment == "")
    check("dry_run defaults to False", args.dry_run is False)
    args = parse(["start", "--project", "demo", "--problem", "x", "--segment", "postpaid_consumer", "--dry-run"])
    check("segment captured when given", args.segment == "postpaid_consumer")
    check("--dry-run flag captured", args.dry_run is True)
    try:
        parse(["start", "--project", "demo"])
        check("missing --problem should have been rejected", False)
    except SystemExit:
        check("missing --problem is rejected", True)

    check.section("[4] approve -- stage must be ba/pe/rfc, decision defaults to approve")
    args = parse(["approve", "--project", "demo", "--stage", "ba"])
    check("decision defaults to approve", args.decision == "approve")
    for stage in ("ba", "pe", "rfc"):
        args = parse(["approve", "--project", "demo", "--stage", stage])
        check(f"stage '{stage}' accepted", args.stage == stage)
    try:
        parse(["approve", "--project", "demo", "--stage", "adr"])
        check("stage 'adr' should have been rejected", False)
    except SystemExit:
        check("stage 'adr' correctly rejected (ADR isn't in this build's scope)", True)
    for decision in ("approve", "needs_changes", "clarification", "jump_back_to_ba"):
        args = parse(["approve", "--project", "demo", "--stage", "pe", "--decision", decision])
        check(f"decision '{decision}' accepted", args.decision == decision)

    check.section("[5] feedback -- message is required alongside project and stage")
    args = parse(["feedback", "--project", "demo", "--stage", "rfc", "--message", "add MFA detail"])
    check("message captured", args.message == "add MFA detail")
    try:
        parse(["feedback", "--project", "demo", "--stage", "rfc"])
        check("missing --message should have been rejected", False)
    except SystemExit:
        check("missing --message is rejected", True)

    check.section("[6] chat -- --project is genuinely optional, and threads through to main() correctly")
    args = parse(["chat"])
    check("no --project defaults to None", args.project is None)
    args = parse(["chat", "--project", "my-old-project"])
    check("--project captured when given", args.project == "my-old-project")

    with patch.object(main_module, "CopilotApp") as MockApp:
        sys.argv = ["mono", "chat", "--project", "my-old-project"]
        main_module.main()
        MockApp.assert_called_once_with(project="my-old-project")
        MockApp.return_value.run.assert_called_once()
    check("chat --project reaches CopilotApp's constructor, not just parse_args", True)

    check.section("[7] start_headless dry-run genuinely creates a real, resumable session")
    def _dry_run():
        result = commands.start_headless(project="dry-demo", problem="reduce churn", segment="postpaid_consumer", dry_run=True)
        cm = ContextManager()
        session = cm.get_session("dry-demo")
        brd = FileManager().load_brd("dry-demo")
        return result, session, brd

    result, session, brd = in_temp_projects_dir(_dry_run)
    check("dry run reports success", result["status"] == "success")
    check("a real session was actually created on disk", session is not None)
    check("segment made it into the real session", session.get("segment") == "postpaid_consumer")
    check("a placeholder BRD file was actually written", brd is not None and "dry-demo" in brd)

    check.section("[8] approve() on a project with no session fails clearly rather than crashing")
    def _approve_nonexistent():
        return commands.approve(project="never-existed", stage="ba", decision="approve")

    result = in_temp_projects_dir(_approve_nonexistent)
    check("returns an error result rather than raising", result.get("status") == "error", result)

    check.section("[9] feedback() genuinely drives BA rework through the real orchestrator, agent call stubbed")
    def _feedback_flow():
        from copilot.orchestrator import Orchestrator
        cm = ContextManager()
        cm.init_session("feedback-demo", "cli", "reduce churn")
        cm.update_session("feedback-demo", "stage", "ba_approval")
        cm.update_session("feedback-demo", "ba_output", {"markdown": "# BRD v1", "status": "success", "quality_gates_passed": True})
        cm.update_session("feedback-demo", "run_count", 1)

        async def fake_ba_run(self, **kwargs):
            return {"status": "success", "markdown": "# BRD v2 with tighter exception handling",
                    "quality_gates": {"exception_management": True}, "quality_gates_passed": True, "document_id": "BRD-2"}

        import copilot.agents.ba_agent as ba_agent_module
        with patch.object(ba_agent_module.BAAgent, "run", new=fake_ba_run):
            result = commands.feedback(project="feedback-demo", stage="ba", message="tighten the exception handling")

        # A fresh instance for the check, not the same `cm` used for setup --
        # commands.feedback() constructs its own Orchestrator/ContextManager
        # internally, and `cm` here would otherwise return its own stale
        # in-memory copy from before that ran, exactly the kind of mistake
        # test_context_manager.py's round-trip test exists to catch.
        final_session = ContextManager().get_session("feedback-demo")
        return result, final_session

    result, final_session = in_temp_projects_dir(_feedback_flow)
    check("approval step (needs_changes) succeeded", result["approval_step"]["status"] == "success", result["approval_step"])
    check("clarification step succeeded", result["clarification_step"]["status"] == "success", result["clarification_step"])
    check("the rework genuinely landed on disk", "tighter exception handling" in (final_session.get("ba_output") or {}).get("markdown", ""))


main()
sys.exit(check.report())
