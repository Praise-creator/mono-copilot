#!/usr/bin/env python3
"""
Tests for ad-hoc Q&A: skills/chat_skill.py and the routing that reaches it.

Run from the repo root:

    uv run --package copilot python3 apps/copilot/test/test_chat_routing.py

No API key needed, no network, no spend. The model call is stubbed.

THE ONE TEST THAT MATTERS MOST
------------------------------
Section 8. At an approval gate, plain text is review feedback and must stay
review feedback. "the exception handling is thin" reads like conversation,
and answering it as a question would silently swallow a rework request: the
user believes they asked for a change, the document never changes, and
nothing reports a problem. If a future refactor breaks one assertion in this
file, that is the one to care about.
"""

import asyncio
import sys
from unittest.mock import AsyncMock, patch

from _offline import bootstrap, fake_completion, Checks

bootstrap()

from copilot.cli.router import Router, _parse_ask_command
from copilot.orchestrator import Orchestrator
from copilot.skills.chat_skill import ChatSkill

check = Checks()


def build_router_at_ba_approval():
    """A router with one project parked at the BRD approval gate."""
    router = Router(Orchestrator(), user_id="chat-routing-test")
    router.active_project = "demo"
    # Written straight into the in-memory dict rather than through
    # update_session, which would persist a fake project to disk.
    router.orchestrator.context_manager.sessions["demo"] = {
        "stage": "ba_approval",
        "run_count": 1,
        "problem_statement": "Slow outbound upsell process.",
        "segment": "postpaid_consumer",
        "ba_output": {"markdown": "# BRD\nline two"},
        "pe_output": None,
        "history": [],
    }
    return router


async def main():
    check.section("[1] /ask parsing")
    check("bare /ask returns empty string", _parse_ask_command("/ask") == "")
    check("question is extracted", _parse_ask_command("/ask what is ARPU?") == "what is ARPU?")
    check("case insensitive", _parse_ask_command("/ASK hello") == "hello")
    check("ordinary text returns None", _parse_ask_command("approve") is None)
    check("'/asking' is not an /ask command", _parse_ask_command("/asking something") is None)
    # Empty string is falsy but meaningful, so callers must test "is not None".
    check("empty string is distinguishable from None", _parse_ask_command("/ask") is not None)

    check.section("[2] ChatSkill returns a structured answer with sources")
    skill = ChatSkill()
    check("model matches the rest of the pipeline", skill.model == "gpt-4-turbo", skill.model)
    with patch.object(skill.client.chat.completions, "create",
                      new=AsyncMock(return_value=fake_completion("Churn is customer attrition."))):
        result = await skill.answer("what drives churn and regulation in Nigeria?")
    check("status is success", result["status"] == "success", str(result)[:160])
    check("answer text returned", result["markdown"] == "Churn is customer attrition.")
    check("field is related_sources, not verified_sources", "related_sources" in result)
    check("whitelist matched the topic", len(result["related_sources"]) > 0)
    urls = {s["source_url"] for s in result["related_sources"]}
    check("sources deduplicated by url", len(urls) == len(result["related_sources"]))

    check.section("[3] a failed model call never raises")
    with patch.object(skill.client.chat.completions, "create",
                      new=AsyncMock(side_effect=RuntimeError("api down"))):
        result = await skill.answer("anything")
    check("returns an error result instead", result["status"] == "error")
    check("the cause is carried through", "api down" in result["error"])

    check.section("[4] an empty question is rejected before any call")
    result = await skill.answer("   ")
    check("empty question is an error", result["status"] == "error")

    check.section("[5] Router sends /ask to chat, not the workflow")
    router = Router(Orchestrator(), user_id="chat-routing-test")
    with patch.object(router.chat_skill.client.chat.completions, "create",
                      new=AsyncMock(return_value=fake_completion("An answer."))):
        res = await router.handle_input("/ask what does ARPU mean?")
    check("result kind is 'answer'", res.kind == "answer", res.kind)
    check("answer text is in the message", "An answer." in res.message)
    check("turn recorded in history", len(router._chat_history) == 1)

    check.section("[6] bare /ask guides instead of calling the model")
    called = AsyncMock(return_value=fake_completion("should not happen"))
    with patch.object(router.chat_skill.client.chat.completions, "create", new=called):
        res = await router.handle_input("/ask")
    check("result kind is 'message'", res.kind == "message", res.kind)
    check("model was not called", called.await_count == 0)

    check.section("[7] /ask works mid-setup and restores the pending question")
    mid_setup = Router(Orchestrator(), user_id="chat-routing-test")
    mid_setup._pending_idea = type("Pending", (), {
        "segment": None, "country_or_market": None,
        "project_name": None, "problem_statement": "x",
    })()
    mid_setup._last_pending_question = "Which segment is this for?"
    with patch.object(mid_setup.chat_skill.client.chat.completions, "create",
                      new=AsyncMock(return_value=fake_completion("A segment is a customer grouping."))):
        res = await mid_setup.handle_input("/ask what is a segment?")
    check("question was answered", res.kind == "answer", res.kind)
    check("pending question re-surfaced",
          "Still waiting on: Which segment is this for?" in res.message, res.message[-120:])
    check("setup state untouched", mid_setup._pending_idea is not None)
    check("pending question still tracked",
          mid_setup._last_pending_question == "Which segment is this for?")

    check.section("[8] plain text at an approval gate is still feedback")
    router = build_router_at_ba_approval()
    approval = AsyncMock(return_value={"status": "success", "stage": "ba_clarifying"})
    clarification = AsyncMock(return_value={
        "status": "success", "stage": "ba_approval",
        "output": "# BRD v2", "file_path": "p.md", "quality_gates": {},
    })
    chat_called = AsyncMock(return_value=fake_completion("should not happen"))
    with patch.object(router.orchestrator, "handle_approval", new=approval), \
         patch.object(router.orchestrator, "handle_clarification_response", new=clarification), \
         patch.object(router.chat_skill.client.chat.completions, "create", new=chat_called):
        await router.handle_input("the exception handling is thin")
    check("routed to rework", clarification.await_count == 1)
    check("chat skill was NOT invoked", chat_called.await_count == 0)
    check("needs_changes sent first", approval.await_args.kwargs.get("decision") == "needs_changes")

    check.section("[9] /ask inside a project sees the live document")
    captured = {}

    async def capture(**kwargs):
        captured.update(kwargs)
        return fake_completion("Contextual answer.")

    with patch.object(router.chat_skill.client.chat.completions, "create", new=capture), \
         patch.object(router.orchestrator, "handle_approval", new=AsyncMock()) as approve, \
         patch.object(router.orchestrator, "handle_clarification_response", new=AsyncMock()) as clarify:
        await router.handle_input("/ask what does the BRD say?")
    prompt = captured["messages"][-1]["content"]
    check("BRD text reached the prompt", "line two" in prompt)
    check("stage reached the prompt", "ba_approval" in prompt)
    check("orchestrator was not touched", approve.await_count == 0 and clarify.await_count == 0)
    check("project stage unchanged",
          router.orchestrator.context_manager.sessions["demo"]["stage"] == "ba_approval")

    check.section("[10] source wording does not overstate what was checked")
    footer = router._format_related_sources([
        {"source_url": "https://ncc.gov.ng", "authority_level": "high",
         "search_queries_used": ["regulation"]},
    ])
    check("says matches are not per-claim verification", "not verified per claim" in footer, footer)
    check("avoids claiming sources are verified", "Verified" not in footer)
    check("no sources gives no footer", router._format_related_sources([]) is None)

    check.section("[11] chat history stays bounded")
    router._chat_history = [{"question": f"q{i}", "answer": f"a{i}"} for i in range(20)]
    with patch.object(router.chat_skill.client.chat.completions, "create",
                      new=AsyncMock(return_value=fake_completion("x"))):
        await router.handle_input("/ask one more")
    check("trimmed to the cap", len(router._chat_history) == 6, str(len(router._chat_history)))
    check("most recent turn kept", router._chat_history[-1]["question"] == "one more")


asyncio.run(main())
sys.exit(check.report())
