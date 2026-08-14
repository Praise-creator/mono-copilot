#!/usr/bin/env python3
"""
Every workflow state has a way out.

Run from the repo root:

    uv run --package copilot python3 apps/copilot/test/test_workflow_recovery.py

No API key needed, no network, no spend. The agents are stubbed.

WHY THIS FILE EXISTS
--------------------
Three separate ways a project could end up in a stage nothing could act on,
all found within a day of each other:

  1. A rework failing on any attempt other than 6 or 9 fell through the error
     guard into the success path, crashed on save, and left the session at
     ba_reworking or pe_reworking. See #16.
  2. jump_back_to_ba set pe_jump_back_to_ba, which no other code read. See #17.
  3. A rework failing on attempt 6 correctly reached ba_deep_dive, but the
     router always asked for a needs_changes transition first, and
     handle_approval rejects that unless the stage is ba_approval. So
     answering the deep dive prompt failed and the session stayed there.

They share a shape rather than a cause: a stage gets set and nothing can move
it on. The failure is quiet in every case, since the document survives and
only the stage is wrong, so nothing surfaces until someone tries to carry on
working and finds they cannot.

The last assertion is the general one. It walks the enum and checks that
every stage either has an explicit handler or is genuinely transient, so a
new state added later cannot quietly become a fourth dead end.
"""

import asyncio
import sys
from unittest.mock import patch

from _offline import bootstrap, Checks

bootstrap()

from copilot.orchestrator import Orchestrator, OrchestratorState
from copilot.cli.router import Router

check = Checks()


def session(stage: str, run_count: int) -> dict:
    """A project parked at `stage`, with both documents already generated."""
    return {
        "stage": stage,
        "run_count": run_count,
        "problem_statement": "Slow outbound upsell.",
        "segment": "postpaid_consumer",
        "context": {},
        "ba_output": {"status": "success", "markdown": "# BRD", "quality_gates_passed": True},
        "pe_output": {"status": "success", "markdown": "# PRD", "quality_gates_passed": True},
        "history": [],
    }


async def agent_fails(**kwargs):
    """What a rate limit, timeout or dropped connection looks like here."""
    return {"status": "error", "error": "rate limited", "markdown": None,
            "quality_gates_passed": False}


async def agent_succeeds(**kwargs):
    return {"status": "success", "document_id": "BRD-x", "markdown": "# BRD v2",
            "structured": {}, "sources_metadata": {"sources_used": []},
            "quality_gates": {"process_flow_analysis": True}, "quality_gates_passed": True}


async def main():
    check.section("[1] a failed BA rework returns to the approval gate (#16)")
    orch = Orchestrator()
    orch.context_manager.sessions["a"] = session("ba_clarifying", 1)
    with patch.object(orch.ba_agent, "run", new=agent_fails):
        result = await orch.handle_clarification_response("a", "ba", {"feedback": "more detail"})
    check("stage recovers to ba_approval",
          orch.context_manager.sessions["a"]["stage"] == "ba_approval",
          orch.context_manager.sessions["a"]["stage"])
    check("reported as an error, not a success", result.get("status") == "error")
    check("says the document was left alone", "unchanged" in result.get("message", ""),
          result.get("message", ""))
    check("existing BRD untouched",
          orch.context_manager.sessions["a"]["ba_output"]["markdown"] == "# BRD")

    check.section("[2] a failed PE rework does the same (#16)")
    orch.context_manager.sessions["b"] = session("pe_clarifying", 1)
    with patch.object(orch.pe_agent, "run", new=agent_fails):
        result = await orch.handle_clarification_response("b", "pe", {"feedback": "more detail"})
    check("stage recovers to pe_approval",
          orch.context_manager.sessions["b"]["stage"] == "pe_approval",
          orch.context_manager.sessions["b"]["stage"])
    check("reported as an error", result.get("status") == "error")
    check("existing PRD untouched",
          orch.context_manager.sessions["b"]["pe_output"]["markdown"] == "# PRD")

    check.section("[3] jump_back_to_ba lands somewhere usable (#17)")
    orch.context_manager.sessions["c"] = session("pe_approval", 1)
    result = await orch.handle_approval("c", "pe", "jump_back_to_ba")
    check("stage is ba_approval", orch.context_manager.sessions["c"]["stage"] == "ba_approval",
          orch.context_manager.sessions["c"]["stage"])
    check("no longer reports the old dead-end stage", result.get("stage") != "pe_jump_back_to_ba")

    check.section("[4] the deep dive prompt can actually be answered")
    orch.context_manager.sessions["d"] = session("ba_clarifying", 5)   # next attempt is 6
    with patch.object(orch.ba_agent, "run", new=agent_fails):
        await orch.handle_clarification_response("d", "ba", {"feedback": "more detail"})
    check("failure at attempt 6 reaches deep dive",
          orch.context_manager.sessions["d"]["stage"] == "ba_deep_dive",
          orch.context_manager.sessions["d"]["stage"])
    router = Router(orch)
    router.active_project = "d"
    with patch.object(orch.ba_agent, "run", new=agent_succeeds):
        result = await router.handle_input("here is much more detail on the exception handling")
    check("answering it regenerates the document", result.kind == "document_ready", result.kind)
    check("stage returns to ba_approval",
          orch.context_manager.sessions["d"]["stage"] == "ba_approval",
          orch.context_manager.sessions["d"]["stage"])

    check.section("[5] no stage is a dead end")
    # A stage is fine if the router handles it explicitly, or if it is
    # transient: only ever set and left within a single synchronous call, so a
    # user can never be sitting at it between turns.
    router_handles = lambda s: (
        s.endswith("_approval") or s.endswith("_clarifying")
        or s.endswith("_deep_dive") or s.endswith("_failed") or s == "done"
    )
    transient = {"ba_pending", "pe_pending", "rfc_pending",
                 "ba_reworking", "pe_reworking", "rfc_reworking"}
    stranded = [s.value for s in OrchestratorState
                if not router_handles(s.value) and s.value not in transient]
    check("every state is handled or transient", stranded == [], f"stranded: {stranded}")


asyncio.run(main())
sys.exit(check.report())
