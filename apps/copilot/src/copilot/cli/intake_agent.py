"""
Intake agent — a small, cheap conversational model that takes over exactly
where the rule-based EntryClassifier gives up (AMBIGUOUS_NEEDS_CLARIFICATION).

Why this exists: the rule-based classifier has no memory of its own
questions. A short reply to its own clarifying question ("1", "a new idea")
looks identical to a fresh ambiguous input, so it loops forever. A real
conversational model doesn't have that problem, since the whole exchange is
in its context. This agent is deliberately narrow, though: its only output
is a decision from the same fixed EntryPath set the rule-based classifier
uses, delivered via a forced tool call rather than free text that then has
to be re-parsed and could drift from the known set of outcomes.

Uses a separate, cheaper/faster model than the BA/PE gpt-4-turbo calls, since
this is classification, not document generation. Adjust MODEL below if your
account uses different naming.
"""

from dataclasses import dataclass
from typing import List, Optional
import json
import os

from openai import AsyncOpenAI

from .entry_classifier import EntryPath

MODEL = "gpt-4o-mini"
MAX_TURNS = 5  # hard cap: after this many exchanges, force a decision rather than loop forever

_DECIDABLE_PATHS = [p.value for p in EntryPath if p != EntryPath.AMBIGUOUS_NEEDS_CLARIFICATION]

_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "decide_entry_path",
        "description": (
            "Call this once you know which pipeline entry point the user wants. "
            "Only call it when you're reasonably confident — otherwise keep asking "
            "a short clarifying question instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "enum": _DECIDABLE_PATHS,
                    "description": "Which entry point the user wants.",
                },
                "project_name": {
                    "type": "string",
                    "description": "Existing project name if the user named one, else empty string.",
                },
                "idea_summary": {
                    "type": "string",
                    "description": (
                        "Only for new_project_from_idea: a clean, complete, "
                        "self-contained paragraph restating the user's problem "
                        "statement, including the country/market from "
                        "country_or_market if one was given. This becomes the "
                        "actual input to the BA agent, so it must stand alone "
                        "without the rest of this conversation. Empty string for "
                        "every other path."
                    ),
                },
                "country_or_market": {
                    "type": "string",
                    "description": (
                        "Only for new_project_from_idea: the country or market "
                        "this project is for. Must be a real stated or clearly "
                        "implied answer — a specific country (e.g. 'Ghana'), or "
                        "an explicit non-answer the user gave you ('internal, no "
                        "specific country' / 'multi-market'). Empty string ONLY "
                        "if you have not yet asked or the user hasn't answered "
                        "yet — never invent a country here."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "One sentence explaining the decision, shown to the user.",
                },
            },
            "required": ["path", "project_name", "idea_summary", "country_or_market", "reason"],
        },
    },
}


@dataclass
class IntakeDecision:
    path: EntryPath
    reason: str
    project_name: Optional[str] = None
    idea_summary: Optional[str] = None
    country_or_market: Optional[str] = None


@dataclass
class IntakeTurn:
    """Result of one exchange: either a follow-up question, or a final decision."""
    question: Optional[str] = None
    decision: Optional[IntakeDecision] = None

    @property
    def is_final(self) -> bool:
        return self.decision is not None


def _system_prompt(existing_projects: List[str]) -> str:
    projects_line = ", ".join(existing_projects) if existing_projects else "(none yet)"
    return f"""You are the intake step for Mono-Copilot, an enterprise MNO product-engineering assistant.

Pipeline: idea -> BRD -> PRD -> RFCs -> ADR. A user can enter at any point: a
fresh idea, a pasted existing BRD or PRD, the name of an existing project, or
just a question that doesn't need a formal document at all.

Known existing projects: {projects_line}

Your only job is to figure out which ONE entry point the user wants, then call
decide_entry_path. Ask at most one short question per turn if you're unsure.
Don't ask more than two or three questions total before deciding — if the user
gives you a real, substantive problem statement (a paragraph with a pain
point and a goal), that is already enough to decide new_project_from_idea.
Don't demand more detail than a business analyst would need to get started.

Never invent project names, document content, or business specifics the user
hasn't actually given you. If it's still unclear after a couple of exchanges,
make your best call anyway and say so plainly in the reason field — do not
keep asking indefinitely.

BEFORE deciding new_project_from_idea, check whether a country or market has
been stated or clearly implied anywhere in the conversation. If it hasn't,
your next question must ask for it directly — e.g. "Which country or market
is this for?" — before you finalize. Do not invent a country, and do not
proceed with country_or_market left empty just because you already have
enough detail for idea_summary. If the user tells you this isn't tied to a
specific country (an internal system, or explicitly multi-market), that is a
valid answer — record exactly what they said (e.g. "internal, no specific
country") and proceed. This one extra question is worth asking even though
it means one more turn — a fabricated country in a generated BRD/PRD is
worse than a slightly longer intake conversation."""


class IntakeAgent:
    """
    Stateful conversation with the intake model. Call `send()` once per user
    turn; keep looping while the result isn't final.
    """

    def __init__(self, existing_projects: Optional[List[str]] = None):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        self.client = AsyncOpenAI(api_key=api_key)
        self.existing_projects = existing_projects or []
        self.messages: List[dict] = [
            {"role": "system", "content": _system_prompt(self.existing_projects)}
        ]
        self.turns_taken = 0

    async def send(self, user_message: str) -> IntakeTurn:
        self.messages.append({"role": "user", "content": user_message})
        self.turns_taken += 1

        force_decision = self.turns_taken >= MAX_TURNS
        tool_choice = (
            {"type": "function", "function": {"name": "decide_entry_path"}}
            if force_decision
            else "auto"
        )

        response = await self.client.chat.completions.create(
            model=MODEL,
            max_tokens=400,
            messages=self.messages,
            tools=[_TOOL_SCHEMA],
            tool_choice=tool_choice,
        )

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)

        if tool_calls:
            decision = self._parse_decision(tool_calls[0])
            if decision is not None:
                return IntakeTurn(decision=decision)
            # Malformed tool call — fall through to the safety net below
            # rather than crash or silently loop.

        if not tool_calls and message.content:
            self.messages.append({"role": "assistant", "content": message.content})
            if force_decision:
                # Model answered in text instead of calling the tool, even
                # though we forced it. Don't loop further — build a
                # low-confidence fallback rather than hang indefinitely.
                return IntakeTurn(decision=self._fallback_decision())
            return IntakeTurn(question=message.content)

        # No tool call, no content — malformed response. Fail safe rather
        # than loop forever.
        return IntakeTurn(decision=self._fallback_decision())

    def _parse_decision(self, tool_call) -> Optional[IntakeDecision]:
        try:
            args = json.loads(tool_call.function.arguments)
            path = EntryPath(args["path"])
            return IntakeDecision(
                path=path,
                reason=args.get("reason", ""),
                project_name=args.get("project_name") or None,
                idea_summary=args.get("idea_summary") or None,
                country_or_market=args.get("country_or_market") or None,
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def _fallback_decision(self) -> IntakeDecision:
        """
        Safety net if the model won't commit to a structured decision after
        MAX_TURNS. Treat the conversation so far as the idea itself rather
        than hang — flagged as a fallback in the reason, not silently
        confident.
        """
        user_turns = [m["content"] for m in self.messages if m["role"] == "user"]
        combined = " ".join(user_turns).strip()
        return IntakeDecision(
            path=EntryPath.NEW_PROJECT_FROM_IDEA,
            reason=(
                "Fallback after reaching the turn limit without a confident "
                "model decision — treating the conversation so far as the idea. "
                "No country/market was confirmed either — do not assume one."
            ),
            idea_summary=combined,
            country_or_market=None,
        )
