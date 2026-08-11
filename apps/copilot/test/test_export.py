#!/usr/bin/env python3
"""
Tests for PDF export routing and failure handling in cli/router.py.

Run from the repo root:

    uv run --package copilot python3 apps/copilot/test/test_export.py

No API key needed, no network, no spend. export_document is stubbed, so no
PDFs are written.

WHAT THESE COVER
----------------
Two bugs found while walking through a real session, both of which cost the
user work rather than just looking untidy:

  1. Exporting seven documents in a loop with no error handling. One failure
     escaped through handle_input and killed the interactive session, taking
     the already-written files with it and reporting nothing about them.
     Hit for real when a disk filled partway through.

  2. Matching "export", "pdf", "download" and "save this" anywhere in the
     input. These are ordinary words in telecom requirements writing, and
     the check runs before approval feedback, so a review comment like "we
     should save this data for 90 days" was answered with a PDF and never
     reached the document.
"""

import asyncio
import sys
from unittest.mock import AsyncMock, patch

from _offline import bootstrap, fake_completion, Checks

bootstrap()

from copilot.cli import router as router_module
from copilot.cli.router import Router
from copilot.orchestrator import Orchestrator

check = Checks()


def build_finished_router():
    """A router with a completed project: BRD, PRD and two RFCs."""
    router = Router(Orchestrator(), user_id="export-test")
    router.active_project = "demo"
    router.orchestrator.context_manager.sessions["demo"] = {
        "stage": "done",
        "run_count": 1,
        "problem_statement": "p",
        "segment": "s",
        "ba_output": {"markdown": "# BRD"},
        "pe_output": {"markdown": "# PRD"},
        "rfc_outputs": {
            "security": {"status": "success", "markdown": "# SEC"},
            "qa": {"status": "success", "markdown": "# QA"},
        },
        "history": [],
    }
    return router


async def main():
    check.section("[1] every document exports cleanly")
    router = build_finished_router()
    with patch.object(router_module, "export_document", lambda p, d, m: f"/tmp/{d}.pdf"):
        res = await router.handle_input("export everything as pdf")
    check("result kind is export_ready", res.kind == "export_ready", res.kind)
    check("all four documents written", len(res.data["paths"]) == 4, str(res.data["paths"]))
    check("nothing recorded as failed", res.data["failed"] == [])

    check.section("[2] one document fails partway through")

    def fails_on_prd(project, doc_name, markdown):
        if doc_name == "prd":
            raise OSError("[Errno 28] No space left on device")
        return f"/tmp/{doc_name}.pdf"

    router = build_finished_router()
    with patch.object(router_module, "export_document", fails_on_prd):
        # The assertion here is partly that this line returns at all. Before
        # the fix it raised, and the caller's session loop died with it.
        res = await router.handle_input("export everything as pdf")
    check("session survived the failure", True)
    check("still reports export_ready", res.kind == "export_ready", res.kind)
    check("three documents written", len(res.data["paths"]) == 3, str(res.data["paths"]))
    check("one failure recorded", len(res.data["failed"]) == 1, str(res.data["failed"]))
    check("failure names the document", "prd" in res.data["failed"][0])
    check("failure explains the cause", "No space left" in res.data["failed"][0])
    check("successes listed in the message", "brd -> /tmp/brd.pdf" in res.message)
    check("failure count shown", "Failed (1 of 4)" in res.message, res.message)

    check.section("[3] every document fails")

    def always_fails(project, doc_name, markdown):
        raise OSError("[Errno 28] No space left on device")

    router = build_finished_router()
    with patch.object(router_module, "export_document", always_fails):
        res = await router.handle_input("export everything as pdf")
    check("still no exception", True)
    check("result kind is error", res.kind == "error", res.kind)
    check("all four failures listed", len(res.data["failed"]) == 4)
    check("no paths claimed", res.data["paths"] == [])

    check.section("[4] the router still works after an export failure")
    with patch.object(router.chat_skill.client.chat.completions, "create",
                      new=AsyncMock(return_value=fake_completion("Still answering."))):
        res = await router.handle_input("/ask are you still alive?")
    check("Q&A still routes correctly", res.kind == "answer", res.kind)

    check.section("[5] genuine export requests are recognised")
    router = build_finished_router()
    for text in ("export everything as pdf", "export", "pdf", "as pdf", "download it",
                 "save this", "give me a copy", "export the brd",
                 "export the security rfc as pdf", "can i get the prd as a pdf",
                 "EXPORT ALL", "send me the prd", "save a copy of the brd"):
        check(f"exports: {text!r}", router._is_export_request(text))

    check.section("[6] review feedback is not mistaken for an export request")
    for text in ("we should save this data for 90 days per regulation",
                 "add a section on how we export customer records",
                 "the download speed metrics are missing",
                 "the exception handling is thin",
                 "we need to document the data export process for auditors",
                 "add retry limits and make sure agents can download the report"):
        check(f"stays feedback: {text!r}", not router._is_export_request(text))


asyncio.run(main())
sys.exit(check.report())
