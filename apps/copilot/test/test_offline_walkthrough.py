#!/usr/bin/env python3
"""
The whole pipeline, start to finish, without an API key.

Run from the repo root:

    uv run --package copilot python3 apps/copilot/test/test_offline_walkthrough.py

WHAT THIS IS FOR
----------------
Two things at once.

As a learning tool, it is the fastest way to understand how the system fits
together. It prints each user turn, the reply, and the project stage after
every step, so the state machine is visible rather than inferred. A real run
costs a few dollars and takes several minutes; this takes a second.

As a test, it is the only check that exercises Router, EntryClassifier,
Orchestrator, FileManager and SessionStore together against real disk. The
other offline tests stub at the router boundary and would not catch a break
in how those pieces hand off to each other.

WHAT IS FAKED
-------------
Only the three document-generating agents (BA, PE, RFC) and the chat model.
Everything else is the real code path. The agents are patched at the .run()
boundary rather than deeper, because BAAgent.run is a thin pass-through, so
patching there keeps the Orchestrator's own logic (quality gates, stage
transitions, retry counting) genuinely under test.

Projects are written to a temporary directory that is deleted afterwards, so
running this never touches the real projects/ folder.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from _offline import bootstrap, fake_completion, Checks

bootstrap()

from copilot.cli.router import Router
from copilot.orchestrator import Orchestrator
from copilot.skills.rfc_skill import RFC_ROLES

check = Checks()
WIDTH = 74


def banner(text):
    print(f"\n{'=' * WIDTH}\n{text}\n{'=' * WIDTH}")


def step(number, text):
    print(f"\n--- STEP {number}: {text} " + "-" * max(0, WIDTH - 14 - len(text)))


BRD = """# BRD: Agent Assist for Outbound Upsell

## Current Process Flow
Customers wait 45 seconds on average for an agent. 15% abandon before connection.

## Proposed Process Flow
AI pre-analysis surfaces a recommendation before the agent picks up.

## Integration Architecture
CRM to AI Engine: REST API, under 2 second latency.

## Exception Management
AI Engine timeout over 3s: show cached recommendation, retry 3x, alert ops.

## Business Rules
Agents may not offer upsells to accounts in arrears.
"""

PRD = """# PRD: Agent Assist

## Technical Architecture
Python service behind the CRM, Redis cache, 3 replicas.

## Non Functional Requirements
p95 latency under 2s. Availability 99.9%. RTO 15 min, RPO 5 min.

## Rollback Strategy
Feature flag, instant disable, no schema migration required.
"""


def agent_result(document_id, markdown):
    """Shaped like a real agent return value so the Orchestrator treats it as one."""
    return {
        "status": "success",
        "document_id": document_id,
        "markdown": markdown,
        "structured": {},
        "sources_metadata": {"sources_used": []},
        "quality_gates": {
            "process_flow_analysis": True,
            "integration_architecture": True,
            "exception_management": True,
            "business_rules": True,
        },
        "quality_gates_passed": True,
        "approval_required": True,
    }


async def fake_ba(**kwargs):
    run = kwargs.get("run_count", 1)
    markdown = BRD if run == 1 else BRD + f"\n## Revision {run}\nUpdated after feedback.\n"
    return agent_result(f"BRD-demo-{run}", markdown)


async def fake_pe(**kwargs):
    return agent_result("PRD-demo-1", PRD)


async def fake_rfc(**kwargs):
    role = kwargs.get("role", "unknown")
    return agent_result(f"RFC-{role}", f"# RFC: {role}\n\nDecisions for {role}.\n")


async def main(workdir: Path):
    orchestrator = Orchestrator()
    router = Router(orchestrator, user_id="walkthrough", projects_dir=str(workdir / "projects"))

    def stage_of(name):
        session = orchestrator.context_manager.get_session(name)
        return session.get("stage") if session else None

    async def send(text, answer="A short, grounded answer."):
        print(f"\n  > {text}")
        with patch.object(router.chat_skill.client.chat.completions, "create",
                          new=AsyncMock(return_value=fake_completion(answer))):
            result = await router.handle_input(text)
        print(f"  [kind={result.kind}]")
        print("\n".join("    " + line for line in result.message.splitlines()))
        stage = stage_of(router.active_project) if router.active_project else "(no project)"
        mid_setup = "yes" if (router._active_intake or router._pending_idea) else "no"
        print(f"    [state] project={router.active_project or '-'} | stage={stage} "
              f"| mid-setup={mid_setup} | chat turns={len(router._chat_history)}")
        return result

    with patch.object(orchestrator.ba_agent, "run", new=fake_ba), \
         patch.object(orchestrator.pe_agent, "run", new=fake_pe), \
         patch.object(orchestrator.rfc_agent, "run", new=fake_rfc):

        banner("PART 1: starting a project from an idea")
        step(1, "describe a business problem")
        res = await send(
            "Our outbound upsell process is slow. Customers call in, wait about 45 "
            "seconds for an agent, and roughly 15% abandon before anyone picks up. "
            "We want AI to pre-analyse the account so the agent sees a recommendation "
            "the moment the call connects."
        )
        check("long-form input starts intake", res.kind == "question", res.kind)

        step(2, "ask a question mid-setup instead of answering")
        res = await send("/ask what is a segment?",
                         "A segment is a customer grouping, such as postpaid_consumer.")
        check("question answered mid-setup", res.kind == "answer", res.kind)
        check("original question re-surfaced", "Still waiting on:" in res.message)
        check("setup not derailed", router._pending_idea is not None)

        step(3, "answer segment, country, then name the project")
        await send("postpaid_consumer")
        await send("Nigeria")
        res = await send("agent-assist-demo")
        check("BRD generated", res.kind == "document_ready", res.kind)
        check("parked at ba_approval", stage_of("agent-assist-demo") == "ba_approval")

        banner("PART 2: reviewing the BRD")
        step(4, "ask about the document under review")
        res = await send("/ask what does the BRD say about abandonment?",
                         "The BRD states roughly 15% abandon before connection.")
        check("answered without touching the workflow", res.kind == "answer", res.kind)
        check("stage unchanged by the question",
              stage_of("agent-assist-demo") == "ba_approval")

        step(5, "give real feedback, which must rework rather than answer")
        res = await send("the exception handling section is too thin")
        check("feedback triggered a rework", "attempt 2" in res.message, res.message[:120])
        check("returned to the approval gate",
              stage_of("agent-assist-demo") == "ba_approval")

        step(6, "approve the BRD")
        res = await send("looks good")
        check("PRD generated", stage_of("agent-assist-demo") == "pe_approval", res.message[:120])

        banner("PART 3: PRD, RFCs and completion")
        step(7, "approve the PRD, which generates all five RFCs")
        await send("approve")
        check("parked at rfc_approval", stage_of("agent-assist-demo") == "rfc_approval")
        print(f"\n    roles generated: {', '.join(RFC_ROLES)}")

        step(8, "approve the RFCs")
        await send("yes")
        check("workflow complete", stage_of("agent-assist-demo") == "done")

        step(9, "ask a question after completion")
        res = await send("/ask what happens next?",
                         "The pipeline is complete; ADR synthesis is out of scope in this build.")
        check("Q&A still available when done", res.kind == "answer", res.kind)

        banner("PART 4: what was written to disk")
        project_dir = workdir / "projects" / "agent-assist-demo"
        written = sorted(p.relative_to(project_dir) for p in project_dir.rglob("*") if p.is_file())
        for path in written:
            print(f"    {path}")
        names = {str(p) for p in written}
        check("BRD saved", "markdown/ba-output.md" in names)
        check("PRD saved", "markdown/pe-output.md" in names)
        check("all five RFCs saved",
              sum(1 for n in names if n.startswith("markdown/")) == 7, str(len(names)))
        check("session persisted", ".session.json" in names)

        banner("PART 5: resuming after a restart")
        print("Building a fresh Router, as if the app had been quit and reopened.")
        resumed = Router(Orchestrator(), user_id="walkthrough-2",
                         projects_dir=str(workdir / "projects"))
        check("project listed as resumable",
              "agent-assist-demo" in resumed.list_resumable_projects())
        result = await resumed.handle_input("agent-assist-demo")
        print(f"\n  > agent-assist-demo\n  [kind={result.kind}]")
        print("\n".join("    " + line for line in result.message.splitlines()))
        check("resumed from disk", result.kind == "resumed", result.kind)
        check("resumed at the right stage", "done" in result.message)


with tempfile.TemporaryDirectory() as tmp:
    workdir = Path(tmp)
    # SessionStore and FileManager both resolve "projects" relative to the
    # working directory, so this keeps the run entirely inside the temp dir.
    original_cwd = Path.cwd()
    os.chdir(workdir)
    try:
        asyncio.run(main(workdir))
    finally:
        os.chdir(original_cwd)

sys.exit(check.report())
