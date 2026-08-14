#!/usr/bin/env python3
"""
Tests for services/context_manager.py: the disk-persistence round trip that
lets a project survive quitting the terminal or restarting the TUI.

Run from the repo root:

    uv run --package copilot python3 apps/copilot/test/test_context_manager.py

No API key needed, no network, no spend. This is pure file I/O.

THE ONE TEST THAT MATTERS MOST
------------------------------
Section 2. A session created this run and a session reloaded after a
simulated restart (a brand new ContextManager instance, same project name)
must be identical -- not just "close enough", byte-for-byte the same shape.
CopilotHeader, the status bar, and every resume path in router.py all read
straight from whatever get_session() returns; if a reloaded session ever
came back shaped differently from a fresh one, every one of those would
silently start showing wrong or missing data only after a restart, which is
exactly the kind of bug that never shows up in a single continuous test run.
"""

import shutil
import sys
import tempfile
from pathlib import Path

from _offline import bootstrap, Checks

bootstrap()

from copilot.services.context_manager import ContextManager

check = Checks()


def in_temp_projects_dir(fn):
    """Run fn() inside a throwaway projects/ directory, then clean up --
    these tests write real files and must not touch the real projects/
    folder or leave anything behind."""
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
    check.section("[1] a fresh session has the expected shape")
    def _fresh_session():
        cm = ContextManager()
        cm.init_session("demo", "test-user", "reduce churn in Nigeria")
        return cm.get_session("demo")

    session = in_temp_projects_dir(_fresh_session)
    check("session exists", session is not None)
    check("stage starts at ba", session["stage"] == "ba")
    check("problem statement stored", session["problem_statement"] == "reduce churn in Nigeria")
    check("history starts empty", session["history"] == [])
    check("created_at is a plain string, not a datetime object",
          isinstance(session["created_at"], str), type(session["created_at"]))

    check.section("[2] disk round-trip: a brand new ContextManager sees exactly what the first one wrote")
    def _round_trip():
        cm1 = ContextManager()
        cm1.init_session("demo", "test-user", "reduce churn in Nigeria")
        cm1.update_session("demo", "segment", "postpaid_consumer")
        cm1.update_session("demo", "stage", "pe_approval")
        cm1.update_session("demo", "run_count", 3)
        cm1.add_to_history("demo", "ba_rework", "# BRD v2", "tighten the exception handling")

        original = cm1.get_session("demo")

        # The actual test: a completely fresh instance, simulating the app
        # being closed and reopened -- not the same object, not a cache hit.
        cm2 = ContextManager()
        reloaded = cm2.get_session("demo")
        return original, reloaded

    original, reloaded = in_temp_projects_dir(_round_trip)
    check("reloaded session exists at all", reloaded is not None)
    check("stage survived the restart", reloaded["stage"] == "pe_approval", reloaded.get("stage"))
    check("segment survived the restart", reloaded["segment"] == "postpaid_consumer")
    check("run_count survived the restart", reloaded["run_count"] == 3)
    check("history survived the restart", len(reloaded["history"]) == 1)
    check("history entry content survived", reloaded["history"][0]["feedback"] == "tighten the exception handling")
    check("reloaded session is byte-for-byte identical to the original", reloaded == original,
          f"original={original}\nreloaded={reloaded}")

    check.section("[3] session_exists is true from disk alone, before anything is hydrated into memory")
    def _exists_from_disk_only():
        cm1 = ContextManager()
        cm1.init_session("demo", "test-user", "an idea")
        cm2 = ContextManager()  # fresh instance, "demo" not yet in cm2.sessions
        exists_before_touch = "demo" in cm2.sessions
        exists_via_check = cm2.session_exists("demo")
        return exists_before_touch, exists_via_check

    not_yet_in_memory, reports_exists = in_temp_projects_dir(_exists_from_disk_only)
    check("not silently pre-loaded into memory", not_yet_in_memory is False)
    check("session_exists still correctly finds it on disk", reports_exists is True)

    check.section("[4] a nonexistent project returns None, not an exception")
    def _missing_project():
        cm = ContextManager()
        return cm.get_session("this-was-never-created"), cm.session_exists("this-was-never-created")

    missing_session, missing_exists = in_temp_projects_dir(_missing_project)
    check("get_session returns None for an unknown project", missing_session is None)
    check("session_exists is False for an unknown project", missing_exists is False)

    check.section("[5] a corrupt session file fails safe instead of crashing")
    def _corrupt_file():
        cm = ContextManager()
        cm.init_session("demo", "test-user", "an idea")
        session_path = Path("projects/demo/.session.json")
        session_path.write_text("{ this is not valid json ]]]")

        cm2 = ContextManager()
        return cm2.get_session("demo")

    result = in_temp_projects_dir(_corrupt_file)
    check("corrupt file returns None rather than raising", result is None)

    check.section("[6] update_session on an unhydrated-but-real project loads it first, rather than silently dropping the update")
    def _update_before_hydrate():
        cm1 = ContextManager()
        cm1.init_session("demo", "test-user", "an idea")

        cm2 = ContextManager()  # fresh -- "demo" is on disk but not in cm2.sessions yet
        cm2.update_session("demo", "stage", "pe_approval")

        cm3 = ContextManager()  # a third instance, to prove this was really persisted
        return cm3.get_session("demo")

    final = in_temp_projects_dir(_update_before_hydrate)
    check("the update reached disk even though the session wasn't pre-hydrated",
          final is not None and final["stage"] == "pe_approval", final)

    check.section("[7] two different projects never bleed into each other's state")
    def _two_projects():
        cm = ContextManager()
        cm.init_session("project-a", "user", "idea a")
        cm.init_session("project-b", "user", "idea b")
        cm.update_session("project-a", "stage", "pe_approval")
        cm.update_session("project-b", "stage", "ba_approval")

        cm2 = ContextManager()
        return cm2.get_session("project-a"), cm2.get_session("project-b")

    proj_a, proj_b = in_temp_projects_dir(_two_projects)
    check("project A kept its own stage", proj_a["stage"] == "pe_approval")
    check("project B kept its own stage", proj_b["stage"] == "ba_approval")
    check("project A's problem statement is its own, not project B's", proj_a["problem_statement"] == "idea a")


main()
sys.exit(check.report())
