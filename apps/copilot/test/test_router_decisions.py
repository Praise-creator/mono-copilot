#!/usr/bin/env python3
"""
Tests for cli/router.py's workflow decisions -- approval routing, project
switching and resuming, and the two stuck-state bugs (GitHub issues #16 and
#17) found and fixed this session. Ad-hoc Q&A routing already has its own
dedicated coverage in test_chat_routing.py; this file is everything else
Router decides.

Run from the repo root:

    uv run --package copilot python3 apps/copilot/test/test_router_decisions.py

No API key needed, no network, no spend. Agent calls are stubbed at the
orchestrator/agent boundary, same pattern as test_chat_routing.py and
test_command_parser.py.

THE ONE TEST THAT MATTERS MOST
------------------------------
Section 3. Before this session, a BA or PE rework that failed for any
reason other than hitting the deep-dive or max-attempts threshold exactly
left the project stuck at *_reworking forever -- unrecoverable through the
CLI, surviving restarts because the stage was written to disk. Demi filed
this as issue #16 with a working repro. If this section ever goes red, that
bug is back.
"""

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from _offline import bootstrap, Checks

bootstrap()

from copilot.orchestrator import Orchestrator, OrchestratorState
from copilot.cli.router import Router

check = Checks()


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
    check.section("[1] approval words drive a real BA -> PE transition")
    def _approve_ba():
        orch = Orchestrator()
        router = Router(orch, user_id="router-test")
        router.active_project = "demo"
        orch.context_manager.sessions["demo"] = {
            "stage": "ba_approval", "run_count": 1, "problem_statement": "x", "segment": "y",
            "ba_output": {"markdown": "# BRD", "status": "success", "quality_gates_passed": True},
            "pe_output": None, "history": [],
        }

        async def fake_pe_run(self, **kwargs):
            return {"status": "success", "markdown": "# PRD", "quality_gates": {}, "quality_gates_passed": True, "document_id": "PRD-1"}

        import copilot.agents.pe_agent as pe_agent_module
        with patch.object(pe_agent_module.PEAgent, "run", new=fake_pe_run):
            import asyncio
            result = asyncio.run(router.handle_input("approve"))
        return result, orch.context_manager.get_session("demo")

    result, session = in_temp_projects_dir(_approve_ba)
    check("recognized as document_ready", result.kind == "document_ready", result.kind)
    check("PRD is now ready", "PRD ready" in result.message, result.message)
    check("no raw quality-gate dict leaked into the message", "Quality gates" not in result.message)
    check("real transition happened, not just a canned reply", session["stage"] == "pe_approval")

    check.section("[2] a bare project name with no active project resumes it, exactly like /switch")
    def _bare_resume():
        orch = Orchestrator()
        # EntryClassifier's exact-match fast path scans real directories on
        # disk (list_projects_on_disk), not the in-memory session dict --
        # a project only set via context_manager.sessions directly, with no
        # real folder, is invisible to it and falls through to the
        # AI-assisted intake path instead, which needs real network access.
        orch.file_manager.save_brd("old-project", "# BRD")
        orch.context_manager.sessions["old-project"] = {
            "stage": "pe_approval", "run_count": 1, "problem_statement": "x", "segment": "y",
            "ba_output": {"markdown": "# BRD"}, "pe_output": {"markdown": "# PRD"}, "history": [],
        }
        router = Router(orch, user_id="router-test")
        import asyncio
        result = asyncio.run(router.handle_input("old-project"))
        return result, router.active_project

    result, active = in_temp_projects_dir(_bare_resume)
    check("resumed without needing /switch", result.kind == "resumed", result.kind)
    check("router now tracks it as active", active == "old-project")
    check("correct stage surfaced", "pe_approval" in result.message)

    check.section("[3] issue #16 -- a transient BA/PE failure recovers, it does not get stuck")
    # Deliberately calling orchestrator.handle_clarification_response
    # directly here, matching Demi's own real reproduction of issue #16 --
    # not through router.handle_input(). Router's _submit_feedback does the
    # needs_changes-then-rework combo atomically in one call starting from
    # ba_approval; it was never meant to be invoked standalone against a
    # session already sitting at ba_clarifying, which is what routing this
    # through Router here would actually exercise instead.
    def _ba_transient_failure():
        orch = Orchestrator()
        orch.context_manager.sessions["stuck-ba"] = {
            "stage": "ba_clarifying", "run_count": 1, "problem_statement": "x", "segment": "y",
            "ba_output": {"markdown": "# BRD v1", "status": "success"}, "pe_output": None, "history": [],
        }

        async def failing_ba_run(self, **kwargs):
            return {"status": "error", "document_id": None, "error": "rate limit exceeded", "markdown": None, "quality_gates_passed": False}

        import copilot.agents.ba_agent as ba_agent_module
        import asyncio
        with patch.object(ba_agent_module.BAAgent, "run", new=failing_ba_run):
            result = asyncio.run(orch.handle_clarification_response("stuck-ba", "ba", {"feedback": "the exception handling is thin"}))
        return result, orch.context_manager.get_session("stuck-ba")

    result, session = in_temp_projects_dir(_ba_transient_failure)
    check("stage recovered to ba_approval, not stuck at ba_reworking",
          session["stage"] == "ba_approval", session["stage"])
    check("the real underlying error is surfaced, not swallowed",
          "rate limit exceeded" in result["message"], result["message"])
    check("the previous BRD is still there, untouched", session["ba_output"]["markdown"] == "# BRD v1")

    def _ba_recovers_and_can_actually_be_used_afterward():
        """The stuck-state fix isn't just 'doesn't error' -- the recovered
        project has to genuinely support the next real turn too, exactly
        as Demi's repro checked by then sending 'try again' through
        Router and confirming it does not just repeat the same dead end."""
        orch = Orchestrator()
        orch.file_manager.save_brd("recoverable", "# BRD v1")
        orch.context_manager.sessions["recoverable"] = {
            "stage": "ba_clarifying", "run_count": 1, "problem_statement": "x", "segment": "y",
            "ba_output": {"markdown": "# BRD v1", "status": "success"}, "pe_output": None, "history": [],
        }
        router = Router(orch, user_id="router-test")
        router.active_project = "recoverable"

        async def failing_then_ok(self, **kwargs):
            if kwargs.get("run_count", 0) < 2:
                return {"status": "error", "error": "rate limited", "markdown": None}
            return {"status": "success", "markdown": "# BRD v2", "quality_gates": {}, "quality_gates_passed": True, "document_id": "BRD-2"}

        import copilot.agents.ba_agent as ba_agent_module
        import asyncio
        with patch.object(ba_agent_module.BAAgent, "run", new=failing_then_ok):
            first = asyncio.run(orch.handle_clarification_response("recoverable", "ba", {"feedback": "x"}))
            second = asyncio.run(router.handle_input("try again"))
        return first, second

    first, second = in_temp_projects_dir(_ba_recovers_and_can_actually_be_used_afterward)
    check("first attempt failed and recovered", first["stage"] == "ba_approval")
    check("'try again' after recovery genuinely retries, not just repeats the same dead end",
          second.kind == "document_ready" and "BRD v2" in str(second.data), second.message)

    def _pe_transient_failure():
        orch = Orchestrator()
        orch.context_manager.sessions["stuck-pe"] = {
            "stage": "pe_clarifying", "run_count": 2, "problem_statement": "x", "segment": "y",
            "ba_output": {"markdown": "# BRD"}, "pe_output": {"markdown": "# PRD v1", "status": "success"}, "history": [],
        }

        async def failing_pe_run(self, **kwargs):
            return {"status": "error", "error": "timeout", "markdown": None}

        import copilot.agents.pe_agent as pe_agent_module
        import asyncio
        with patch.object(pe_agent_module.PEAgent, "run", new=failing_pe_run):
            result = asyncio.run(orch.handle_clarification_response("stuck-pe", "pe", {"feedback": "tighten the NFRs"}))
        return result, orch.context_manager.get_session("stuck-pe")

    result, session = in_temp_projects_dir(_pe_transient_failure)
    check("PE also recovers to pe_approval, not stuck at pe_reworking",
          session["stage"] == "pe_approval", session["stage"])
    check("PE's real error is surfaced too", "timeout" in result["message"])

    check.section("[4] issue #16 regression guard -- the deep-dive and max-attempts thresholds still fire correctly")
    def _deep_dive_still_works():
        orch = Orchestrator()
        orch.context_manager.sessions["deep-dive-demo"] = {
            "stage": "ba_clarifying", "run_count": 5, "problem_statement": "x", "segment": "y",
            "ba_output": {"markdown": "# BRD"}, "pe_output": None, "history": [],
        }
        async def failing_run(self, **kwargs):
            return {"status": "error", "error": "still failing", "markdown": None}
        import copilot.agents.ba_agent as ba_agent_module
        import asyncio
        with patch.object(ba_agent_module.BAAgent, "run", new=failing_run):
            result = asyncio.run(orch.handle_clarification_response("deep-dive-demo", "ba", {"feedback": "x"}))
        return result

    result = in_temp_projects_dir(_deep_dive_still_works)
    check("attempt 6 still correctly enters deep dive, the fix didn't remove this", result["stage"] == "ba_deep_dive", result["stage"])

    def _max_attempts_still_works():
        orch = Orchestrator()
        orch.context_manager.sessions["max-attempts-demo"] = {
            "stage": "ba_clarifying", "run_count": 8, "problem_statement": "x", "segment": "y",
            "ba_output": {"markdown": "# BRD"}, "pe_output": None, "history": [],
        }
        async def failing_run(self, **kwargs):
            return {"status": "error", "error": "still failing", "markdown": None}
        import copilot.agents.ba_agent as ba_agent_module
        import asyncio
        with patch.object(ba_agent_module.BAAgent, "run", new=failing_run):
            result = asyncio.run(orch.handle_clarification_response("max-attempts-demo", "ba", {"feedback": "x"}))
        return result

    result = in_temp_projects_dir(_max_attempts_still_works)
    check("attempt 9 still correctly gives up at ba_failed, the fix didn't remove this", result["stage"] == "ba_failed", result["stage"])

    check.section("[5] issue #17 -- jump_back_to_ba lands somewhere genuinely actionable")
    def _jump_back():
        orch = Orchestrator()
        orch.context_manager.sessions["jump-demo"] = {
            "stage": "pe_approval", "run_count": 1, "problem_statement": "x", "segment": "y",
            "ba_output": {"markdown": "# BRD"}, "pe_output": {"markdown": "# PRD"}, "history": [],
        }
        import asyncio
        result = asyncio.run(orch.handle_approval("jump-demo", "pe", "jump_back_to_ba"))
        # get_session returns a reference to the live session dict, not a
        # snapshot -- capturing just the one field needed here rather than
        # the whole object, since the object itself keeps mutating as the
        # next call below runs, which would otherwise silently make this
        # look like it reflects the state right after the jump when it
        # actually reflects whatever ran last.
        stage_right_after_jump = orch.context_manager.get_session("jump-demo")["stage"]
        # Prove it's really actionable, not just a different dead end --
        # the BA rework flow must genuinely work from here.
        second_result = asyncio.run(orch.handle_approval("jump-demo", "ba", "needs_changes"))
        return result, stage_right_after_jump, second_result

    result, stage_right_after_jump, second_result = in_temp_projects_dir(_jump_back)
    check("lands at ba_approval, not the old dead pe_jump_back_to_ba state",
          stage_right_after_jump == "ba_approval", stage_right_after_jump)
    check("the message's promise ('you can modify the BRD') is actually true",
          second_result["stage"] == "ba_clarifying", second_result)

    check.section("[6] switching between two ALREADY-active old projects works, not just resuming once")
    def _switch_between_two_old_projects():
        orch = Orchestrator()
        orch.file_manager.save_brd("project-one", "# BRD 1")
        orch.file_manager.save_brd("project-two", "# BRD 2")
        orch.context_manager.sessions["project-one"] = {
            "stage": "pe_approval", "run_count": 1, "problem_statement": "a", "segment": "y",
            "ba_output": {"markdown": "# BRD 1"}, "pe_output": {"markdown": "# PRD 1"}, "history": [],
        }
        orch.context_manager.sessions["project-two"] = {
            "stage": "ba_approval", "run_count": 1, "problem_statement": "b", "segment": "y",
            "ba_output": {"markdown": "# BRD 2"}, "pe_output": None, "history": [],
        }
        router = Router(orch, user_id="router-test")
        import asyncio

        r1 = asyncio.run(router.handle_input("/switch project-one"))
        active_after_first = router.active_project
        r2 = asyncio.run(router.handle_input("/switch project-two"))
        active_after_second = router.active_project
        session_two = orch.context_manager.get_session("project-two")
        return active_after_first, active_after_second, session_two, r2

    active_1, active_2, session_two, r2 = in_temp_projects_dir(_switch_between_two_old_projects)
    check("first switch lands on project-one", active_1 == "project-one")
    check("second switch genuinely moves to project-two, not stuck on project-one", active_2 == "project-two")
    check("project-two's own real session data, not project-one's leaking in",
          session_two["stage"] == "ba_approval", session_two["stage"])
    check("resumed message reflects project-two's real stage", "ba_approval" in r2.message)

    check.section("[7] export request detection doesn't misfire on ordinary feedback that happens to mention exporting")
    orch = Orchestrator()
    router = Router(orch, user_id="router-test")
    real_feedback_mentioning_export_words = [
        "we should save this data for 90 days per regulation",
        "add a section on how we export customer records",
        "the download speed metrics are missing from the NFRs",
    ]
    for text in real_feedback_mentioning_export_words:
        check(f"NOT treated as an export request: {text[:40]}...", router._is_export_request(text) is False)

    genuine_export_requests = ["export as pdf", "pdf", "export the brd", "give me a copy", "can i get the prd as a pdf"]
    for text in genuine_export_requests:
        check(f"correctly treated as an export request: {text!r}", router._is_export_request(text) is True)

    check.section("[8] /new correctly clears the active project instead of leaving stale state")
    def _new_clears_state():
        orch = Orchestrator()
        orch.context_manager.sessions["old"] = {
            "stage": "ba_approval", "run_count": 1, "problem_statement": "x", "segment": "y",
            "ba_output": {"markdown": "# BRD"}, "pe_output": None, "history": [],
        }
        router = Router(orch, user_id="router-test")
        router.active_project = "old"
        import asyncio
        result = asyncio.run(router.handle_input("/new"))
        return result, router.active_project

    result, active_after = in_temp_projects_dir(_new_clears_state)
    check("active project cleared", active_after is None)
    check("asks for a fresh idea", result.kind == "question")


main()
sys.exit(check.report())
