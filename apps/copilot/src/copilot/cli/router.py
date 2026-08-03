"""
Router — the reusable engine behind "agents invoked on their own." This is
the file a frontend/TUI builds on top of: one entry point,
`Router.handle_input(text) -> RouterResult`, that a caller keeps feeding raw
user text into, turn after turn, without needing to know which stage the
underlying pipeline is in or which agent should run next. That decision is
this file's whole job.

Explicitly NOT a UI. No input()/print() anywhere below — a caller (this
repo's test_interactive_session.py, or eventually a real TUI) owns
rendering RouterResult however it likes; this file only decides and
executes.

Scope, stated plainly rather than silently overreached: this wires together
BA -> PE -> RFC -> export as one continuous, resumable session, using the
already-existing EntryClassifier and IntakeAgent for "what does this input
mean" and Orchestrator for "make it happen." It does NOT build entry points
entry_classifier.py itself already marks unfinished or out of scope —
AD_HOC_QUESTION (no chat_skill.py exists), STANDALONE_FROM_PRD,
STANDALONE_FROM_BRD_PE_NOT_WIRED, STANDALONE_RFC_REQUEST (all explicitly
named "not wired" by the classifier's own design), or model-assisted
classification (_classify_with_model is a deliberate NotImplementedError
stub). Router surfaces all of these honestly as "not wired yet" rather than
faking a result.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, List

from .entry_classifier import EntryClassifier, EntryPath, list_projects_on_disk
from .intake_agent import IntakeAgent, IntakeDecision
from .approval_words import is_approval
from .line_reference import resolve_line_reference
from ..orchestrator import Orchestrator
from ..skills.rfc_skill import RFC_ROLES, ROLE_DISPLAY_NAMES, ROLE_ALIASES
from ..services.pdf_export import export_document


_EXPORT_KEYWORDS = ("export", "pdf", "download", "save a copy", "save this", "give me a copy", "give me the file")

# Non-answer country/market phrasing that should still count as "resolved"
# (not left blank, not invented) — same set the guided-start intake flow
# already treats as valid.
_NON_COUNTRY_ANSWERS = ("internal", "multi-market", "n/a", "none", "no specific country")


@dataclass
class RouterResult:
    """Normalized shape every Router call returns, regardless of what stage
    or agent actually ran underneath. `kind` tells the caller how to render
    it; `data` carries whatever payload is relevant for that kind."""
    kind: str  # "message" | "question" | "document_ready" | "resumed" | "export_ready" | "error"
    message: str
    data: Optional[Dict] = None
    active_project: Optional[str] = None


@dataclass
class _PendingNewIdea:
    """Router's own tiny multi-turn state for collecting segment/country/
    project name after a new idea is recognized — deliberately NOT routed
    through IntakeAgent for the rule-based-confident case, since a plain
    follow-up question is cheaper and just as correct as an LLM call for
    something this structured (same 'cheap check before expensive call'
    philosophy entry_classifier.py already follows)."""
    problem_statement: str
    segment: Optional[str] = None
    country_or_market: Optional[str] = None
    project_name: Optional[str] = None


def _match_roles_in_text(text: str) -> List[str]:
    """Same word-boundary role-alias matching orchestrator.py's
    _match_roles_in_feedback uses internally, reused here for a genuine
    decision (which RFC's content to resolve a line-reference or export
    request against) rather than just a cosmetic choice."""
    text_lower = text.lower()
    matched = []
    for role, aliases in ROLE_ALIASES.items():
        for alias in aliases:
            if re.search(r"\b" + re.escape(alias) + r"\b", text_lower):
                matched.append(role)
                break
    return matched


class Router:
    """
    One Router instance per session. Owns which project is currently active
    and any in-flight multi-turn collection (intake conversation, or the
    segment/country/name follow-ups after a new idea) — a caller never
    tracks that itself, it just keeps calling handle_input().
    """

    def __init__(self, orchestrator: Orchestrator, user_id: str = "cli-user", projects_dir: str = "projects"):
        self.orchestrator = orchestrator
        self.user_id = user_id
        self.projects_dir = Path(projects_dir)
        self.classifier = EntryClassifier(orchestrator.context_manager, list_projects_on_disk(self.projects_dir))
        self.active_project: Optional[str] = None
        self._active_intake: Optional[IntakeAgent] = None
        self._pending_idea: Optional[_PendingNewIdea] = None

    def list_resumable_projects(self) -> List[str]:
        """Projects with real persisted session state — for a caller to
        show 'here's what you can resume' at startup."""
        return self.orchestrator.context_manager.session_store.list_persisted_projects()

    # ------------------------------------------------------------------
    # Top-level dispatch
    # ------------------------------------------------------------------

    async def handle_input(self, raw_input: str) -> RouterResult:
        text = raw_input.strip()
        if not text:
            return RouterResult(kind="message", message="(nothing to do with empty input)", active_project=self.active_project)

        # Mid multi-turn collection takes priority over everything else —
        # these are direct answers to Router's own last question, not fresh
        # input to reclassify.
        if self._active_intake is not None:
            return await self._continue_intake(text)
        if self._pending_idea is not None:
            return await self._continue_pending_idea(text)

        text_lower = text.lower()
        if text_lower.startswith("/switch "):
            self.active_project = None
            return await self._start_classification(text[len("/switch "):].strip())
        if text_lower == "/new":
            self.active_project = None
            return RouterResult(kind="question", message="Describe the business problem or idea you want to explore.")

        if self.active_project is None:
            return await self._start_classification(text)

        return await self._handle_within_project(text)

    # ------------------------------------------------------------------
    # Entry classification (no active project yet)
    # ------------------------------------------------------------------

    async def _start_classification(self, text: str) -> RouterResult:
        self.classifier.existing_projects = list_projects_on_disk(self.projects_dir)
        result = self.classifier.classify(text)

        if result.path in (EntryPath.RESUME_LIVE_SESSION, EntryPath.RESUME_FROM_DISK_NO_SESSION) and result.project_name:
            self.active_project = result.project_name
            session = self.orchestrator.context_manager.get_session(result.project_name)
            return self._describe_resumed_state(result.project_name, session, result.reason)

        if result.path == EntryPath.NEW_PROJECT_FROM_IDEA:
            self._pending_idea = _PendingNewIdea(problem_statement=text)
            return RouterResult(
                kind="question",
                message="Which segment is this for? (e.g. postpaid_consumer, enterprise, wholesale)",
            )

        if result.path == EntryPath.AMBIGUOUS_NEEDS_CLARIFICATION:
            self._active_intake = IntakeAgent(existing_projects=self.classifier.existing_projects)
            turn = await self._active_intake.send(text)
            if turn.is_final:
                return await self._resolve_intake_decision(turn.decision)
            question = turn.question or (result.clarification.question if result.clarification else "Can you say more?")
            return RouterResult(kind="question", message=question)

        if result.path == EntryPath.AD_HOC_QUESTION:
            return RouterResult(
                kind="message",
                message=(
                    "Ad-hoc Q&A isn't wired up in this build — it only covers the "
                    "idea -> BRD -> PRD -> RFC -> export pipeline. Describe a "
                    "business problem to start a new project, or name an existing "
                    "one to resume it."
                ),
            )

        if result.path in (
            EntryPath.STANDALONE_FROM_PRD,
            EntryPath.STANDALONE_FROM_BRD_PE_NOT_WIRED,
            EntryPath.STANDALONE_RFC_REQUEST,
        ):
            return RouterResult(
                kind="message",
                message=(
                    f"Recognized this as '{result.path.value}' ({result.reason}), but "
                    "that entry point isn't wired up in this build yet. Start from a "
                    "fresh idea instead, or name an existing project to resume it."
                ),
            )

        return RouterResult(kind="error", message=f"Unhandled entry path: {result.path}")

    async def _continue_intake(self, text: str) -> RouterResult:
        assert self._active_intake is not None
        turn = await self._active_intake.send(text)
        if turn.is_final:
            return await self._resolve_intake_decision(turn.decision)
        return RouterResult(kind="question", message=turn.question or "Can you say more?")

    async def _resolve_intake_decision(self, decision: IntakeDecision) -> RouterResult:
        self._active_intake = None

        if decision.path == EntryPath.NEW_PROJECT_FROM_IDEA:
            problem_statement = decision.idea_summary or ""
            country = decision.country_or_market or "internal, no specific country"
            problem_statement += f"\n\nMarket/Country: {country}."
            pending = _PendingNewIdea(problem_statement=problem_statement)
            pending.country_or_market = country  # already resolved via intake, skip re-asking
            self._pending_idea = pending
            return RouterResult(
                kind="question",
                message="Which segment is this for? (e.g. postpaid_consumer, enterprise, wholesale)",
            )

        if decision.path in (EntryPath.RESUME_LIVE_SESSION, EntryPath.RESUME_FROM_DISK_NO_SESSION) and decision.project_name:
            self.active_project = decision.project_name
            session = self.orchestrator.context_manager.get_session(decision.project_name)
            return self._describe_resumed_state(decision.project_name, session, decision.reason)

        return RouterResult(
            kind="message",
            message=f"Intake resolved to '{decision.path.value}' ({decision.reason}), but that entry point isn't wired up in this build yet.",
        )

    async def _continue_pending_idea(self, text: str) -> RouterResult:
        pending = self._pending_idea
        assert pending is not None
        text = text.strip()

        if pending.segment is None:
            pending.segment = text or "general"
            if pending.country_or_market is None:
                return RouterResult(
                    kind="question",
                    message="Which country or market is this for? (say 'internal' or 'multi-market' if there isn't one specific country)",
                )
            return RouterResult(kind="question", message="Project name (used for the projects/ folder)?")

        if pending.country_or_market is None:
            country = text or "internal, no specific country"
            pending.country_or_market = country
            non_answer = any(na in country.lower() for na in _NON_COUNTRY_ANSWERS)
            suffix = f"{country} (no specific country)" if non_answer else country
            pending.problem_statement += f"\n\nMarket/Country: {suffix}."
            return RouterResult(kind="question", message="Project name (used for the projects/ folder)?")

        pending.project_name = text or "untitled-project"
        self._pending_idea = None
        self.active_project = pending.project_name

        ba_result = await self.orchestrator.process_input(
            project_name=pending.project_name,
            user_id=self.user_id,
            problem_statement=pending.problem_statement,
            segment=pending.segment,
        )
        return self._render_stage_result(ba_result)

    def _describe_resumed_state(self, project_name: str, session: Optional[Dict], reason: str) -> RouterResult:
        if session is None:
            return RouterResult(kind="error", message=f"Could not load session state for '{project_name}'.")

        stage = session.get("stage", "unknown")
        lines = [f"Resumed '{project_name}' — {reason}", f"Current stage: {stage}"]

        if stage in ("ba_approval", "ba_clarifying", "ba_deep_dive"):
            ba_output = session.get("ba_output") or {}
            lines.append(f"Waiting on your review of the BRD (attempt {session.get('run_count', 1)}).")
            return RouterResult(kind="resumed", message="\n".join(lines), data={"document": ba_output.get("markdown")}, active_project=project_name)

        if stage in ("pe_approval", "pe_clarifying", "pe_deep_dive"):
            pe_output = session.get("pe_output") or {}
            lines.append(f"Waiting on your review of the PRD (attempt {session.get('run_count', 1)}).")
            return RouterResult(kind="resumed", message="\n".join(lines), data={"document": pe_output.get("markdown")}, active_project=project_name)

        if stage in ("rfc_approval", "rfc_clarifying"):
            rfc_outputs = session.get("rfc_outputs") or {}
            lines.append("Waiting on your review of the RFCs.")
            return RouterResult(kind="resumed", message="\n".join(lines), data={"rfc_outputs": rfc_outputs}, active_project=project_name)

        if stage == "done":
            lines.append("This project is already fully approved (BRD, PRD, and RFCs). Nothing pending.")
            return RouterResult(kind="resumed", message="\n".join(lines), active_project=project_name)

        if stage.endswith("_failed"):
            lines.append("This project hit the max-attempts limit and is stalled. Describe a revised approach to continue, or '/new' to start fresh instead.")
            return RouterResult(kind="resumed", message="\n".join(lines), active_project=project_name)

        lines.append("(No pending human decision at this stage — it may be mid-generation from an interrupted run. Describe what you'd like if this seems stuck.)")
        return RouterResult(kind="resumed", message="\n".join(lines), active_project=project_name)

    # ------------------------------------------------------------------
    # Within an active project
    # ------------------------------------------------------------------

    async def _handle_within_project(self, text: str) -> RouterResult:
        session = self.orchestrator.context_manager.get_session(self.active_project)
        if session is None:
            project = self.active_project
            return RouterResult(kind="error", message=f"Lost track of session state for '{project}'. Try '/switch {project}' to resume it.")

        stage = session.get("stage", "")

        if self._is_export_request(text):
            return await self._handle_export(text, session)

        if stage.endswith("_approval"):
            return await self._handle_approval_stage(text, stage, session)

        if stage.endswith("_clarifying") or stage.endswith("_deep_dive"):
            return await self._submit_feedback(text, stage.split("_")[0], session)

        if stage.endswith("_failed"):
            return RouterResult(
                kind="message",
                message=(
                    f"'{self.active_project}' hit the max-attempts limit at the "
                    f"{stage.split('_')[0].upper()} stage. Describe a revised "
                    "approach to try again, or '/new' to start fresh instead."
                ),
                active_project=self.active_project,
            )

        if stage == "done":
            return RouterResult(
                kind="message",
                message="This project is fully approved. Say '/new' for a different idea, or '/switch <name>' to work on another project.",
                active_project=self.active_project,
            )

        return RouterResult(
            kind="message",
            message=f"Project is mid-generation (stage: {stage}) — try again in a moment, or describe what you'd like if this seems stuck.",
            active_project=self.active_project,
        )

    async def _handle_approval_stage(self, text: str, stage: str, session: Dict) -> RouterResult:
        base_stage = stage.split("_")[0]  # "ba" | "pe" | "rfc"

        if is_approval(text):
            result = await self.orchestrator.handle_approval(project_name=self.active_project, stage=base_stage, decision="approve")
            return self._render_stage_result(result)

        return await self._submit_feedback(text, base_stage, session)

    async def _submit_feedback(self, text: str, base_stage: str, session: Dict) -> RouterResult:
        """Shared by both the approval-stage 'not an approval word, so it
        must be feedback' path and the direct clarifying/deep-dive answer
        path — both ultimately do the same thing: enrich with a line
        reference if one's present, then rework."""
        document = self._current_document_for_stage(session, base_stage, text)
        enriched = resolve_line_reference(text, document)
        feedback = enriched or text

        if base_stage in ("ba", "pe"):
            # BA/PE need the explicit needs_changes transition first (moves
            # ba_approval -> ba_clarifying) before a clarification response
            # is valid — same two-step orchestrator.py already requires.
            clarify = await self.orchestrator.handle_approval(project_name=self.active_project, stage=base_stage, decision="needs_changes")
            if clarify.get("status") != "success":
                return RouterResult(kind="error", message=clarify.get("message", "Could not start a rework."), active_project=self.active_project)
        elif session.get("stage", "").endswith("_approval"):
            # RFC approval -> clarifying needs the same transition; RFC
            # clarifying/deep_dive (reached via _handle_within_project
            # directly) is already past it.
            clarify = await self.orchestrator.handle_approval(project_name=self.active_project, stage=base_stage, decision="needs_changes")
            if clarify.get("status") != "success":
                return RouterResult(kind="error", message=clarify.get("message", "Could not start a rework."), active_project=self.active_project)

        result = await self.orchestrator.handle_clarification_response(
            project_name=self.active_project, stage=base_stage, responses={"feedback": feedback}
        )
        return self._render_stage_result(result)

    def _current_document_for_stage(self, session: Dict, base_stage: str, feedback_text: str) -> Optional[str]:
        if base_stage == "ba":
            return (session.get("ba_output") or {}).get("markdown")
        if base_stage == "pe":
            return (session.get("pe_output") or {}).get("markdown")
        if base_stage == "rfc":
            rfc_outputs = session.get("rfc_outputs") or {}
            matched = _match_roles_in_text(feedback_text)
            if len(matched) == 1:
                return (rfc_outputs.get(matched[0]) or {}).get("markdown")
            # Ambiguous or no role named — can't safely resolve a line
            # reference against one specific RFC, falls back to free text.
            return None
        return None

    def _render_stage_result(self, result: Dict) -> RouterResult:
        status = result.get("status")
        stage = result.get("stage", "")

        if status == "error":
            message = result.get("message", "Something went wrong.")
            errors = result.get("errors")
            if errors:
                detail_lines = [f"  {role}: {err}" for role, err in errors.items() if err]
                if detail_lines:
                    message += "\n" + "\n".join(detail_lines)
            return RouterResult(kind="message", message=message, active_project=self.active_project)

        if stage in ("ba_approval", "pe_approval"):
            doc_label = "BRD" if stage == "ba_approval" else "PRD"
            message = (
                f"{doc_label} ready -> {result.get('file_path')}\n"
                f"Quality gates: {result.get('quality_gates')}\n"
                f"{result.get('message', '')}\n"
                f"(Say 'export as pdf' anytime if you'd like a copy of this.)"
            )
            return RouterResult(
                kind="document_ready",
                message=message,
                data={"document": result.get("output"), "file_path": result.get("file_path"), "quality_gates": result.get("quality_gates")},
                active_project=self.active_project,
            )

        if stage == "rfc_approval" or status == "partial_success":
            summary = self._summarize_rfc_result(result)
            summary += "\n(Say 'export as pdf' anytime, or name a specific RFC, e.g. 'export the security RFC as pdf'.)"
            return RouterResult(kind="document_ready", message=summary, data=result, active_project=self.active_project)

        if stage in ("ba_clarifying", "pe_clarifying", "rfc_clarifying", "ba_deep_dive", "pe_deep_dive"):
            return RouterResult(kind="question", message=result.get("message", "Please provide more detail."), active_project=self.active_project)

        if stage == "done":
            message = result.get("message", "Workflow complete.") + "\n\nWould you like to export any of these as PDF? Just say so, e.g. 'export everything as pdf'."
            return RouterResult(kind="message", message=message, active_project=self.active_project)

        return RouterResult(kind="message", message=result.get("message", str(result)), active_project=self.active_project)

    def _summarize_rfc_result(self, result: Dict) -> str:
        lines = ["RFCs:"]
        for role in RFC_ROLES:
            gates = result.get("quality_gates_by_role", {}).get(role, {})
            passed = result.get("quality_gates_passed_by_role", {}).get(role)
            error = result.get("errors", {}).get(role)
            display = ROLE_DISPLAY_NAMES.get(role, role)
            if error:
                lines.append(f"  [{role}] {display}: FAILED — {error}")
            elif gates:
                overall = "PASS" if passed else "FAIL"
                lines.append(f"  [{role}] {display}: {overall} ({sum(gates.values())}/{len(gates)})")
        lines.append(result.get("message", ""))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _is_export_request(self, text: str) -> bool:
        text_lower = text.lower()
        return any(kw in text_lower for kw in _EXPORT_KEYWORDS)

    async def _handle_export(self, text: str, session: Dict) -> RouterResult:
        text_lower = text.lower()
        ba_output = session.get("ba_output") or {}
        pe_output = session.get("pe_output") or {}
        rfc_outputs = session.get("rfc_outputs") or {}

        targets: List[tuple] = []
        if "brd" in text_lower and ba_output.get("markdown"):
            targets.append(("brd", ba_output["markdown"]))
        if "prd" in text_lower and pe_output.get("markdown"):
            targets.append(("prd", pe_output["markdown"]))
        for role in _match_roles_in_text(text):
            role_result = rfc_outputs.get(role)
            if role_result and role_result.get("status") == "success":
                targets.append((role, role_result["markdown"]))

        if not targets:
            # Nothing named specifically -- export whatever's currently at
            # the approval gate, since that's almost certainly what a bare
            # "export this as pdf" means mid-review.
            stage = session.get("stage", "")
            if stage == "ba_approval" and ba_output.get("markdown"):
                targets.append(("brd", ba_output["markdown"]))
            elif stage == "pe_approval" and pe_output.get("markdown"):
                targets.append(("prd", pe_output["markdown"]))
            elif stage == "rfc_approval":
                for role, role_result in rfc_outputs.items():
                    if role_result.get("status") == "success":
                        targets.append((role, role_result["markdown"]))
            else:
                # No specific gate pending (stage is "done", or mid-generation) --
                # "export this"/"export everything" most reasonably means every
                # approved document that exists, not nothing. This is also what
                # makes a bare "export" work correctly once a project is fully done.
                if ba_output.get("markdown"):
                    targets.append(("brd", ba_output["markdown"]))
                if pe_output.get("markdown"):
                    targets.append(("prd", pe_output["markdown"]))
                for role, role_result in rfc_outputs.items():
                    if role_result.get("status") == "success":
                        targets.append((role, role_result["markdown"]))

        if not targets:
            return RouterResult(kind="message", message="Nothing to export yet — no approved document exists for this project.", active_project=self.active_project)

        paths = []
        for doc_name, markdown in targets:
            path = export_document(self.active_project, doc_name, markdown)
            paths.append(f"{doc_name} -> {path}")

        return RouterResult(kind="export_ready", message="\n".join(paths), data={"paths": paths}, active_project=self.active_project)
