"""
Orchestrator - Controls the BRD -> PRD -> RFC workflow (20 states across three
stages, each with its own approval/clarifying/reworking/deep-dive/failed
cycle). ADR synthesis is a later, separate stage owned outside this class --
see the "done" message below for where this orchestrator's responsibility
actually ends.

Routes: draft -> ba_pending -> ba_approval -> pe_pending -> pe_approval ->
rfc_pending -> rfc_approval -> done
Handles: approval gates, quality checks, clarification feedback, deep dives
"""

from enum import Enum
from typing import Optional, Dict, List
from datetime import datetime
import asyncio
import json
import re
from pathlib import Path

from .services.context_manager import ContextManager
from .services.file_manager import FileManager
from .agents.ba_agent import BAAgent
from .agents.pe_agent import PEAgent
from .agents.rfc_agent import RFCAgent
from .skills.rfc_skill import RFC_ROLES, ROLE_ALIASES


class OrchestratorState(Enum):
    """Every stage the workflow can be in, across BA, PE, and RFC."""
    BA_PENDING = "ba_pending"
    BA_APPROVAL = "ba_approval"
    BA_CLARIFYING = "ba_clarifying"
    BA_REWORKING = "ba_reworking"
    BA_DEEP_DIVE = "ba_deep_dive"
    BA_FAILED = "ba_failed"
    PE_PENDING = "pe_pending"
    PE_APPROVAL = "pe_approval"
    PE_CLARIFYING = "pe_clarifying"
    PE_REWORKING = "pe_reworking"
    PE_DEEP_DIVE = "pe_deep_dive"
    PE_FAILED = "pe_failed"
    # PE_JUMP_BACK_TO_BA was removed rather than kept unused. The
    # jump_back_to_ba decision now lands on BA_APPROVAL, so nothing sets or
    # reads this value, and leaving it in the enum would keep advertising a
    # state the workflow can no longer reach.
    RFC_PENDING = "rfc_pending"
    RFC_APPROVAL = "rfc_approval"
    RFC_CLARIFYING = "rfc_clarifying"
    RFC_REWORKING = "rfc_reworking"
    RFC_DEEP_DIVE = "rfc_deep_dive"
    RFC_FAILED = "rfc_failed"
    DONE = "done"


class Orchestrator:
    """Orchestrates the BA -> PE -> RFC document generation workflow."""

    def __init__(self):
        self.context_manager = ContextManager()
        self.file_manager = FileManager()
        self.ba_agent = BAAgent()
        self.pe_agent = PEAgent()
        self.rfc_agent = RFCAgent()
        self.max_reruns = 5
        self.max_attempts = 9

    async def process_input(
        self,
        project_name: str,
        user_id: str,
        problem_statement: str,
        segment: str,
        context: Optional[Dict] = None
    ) -> Dict:
        """Start BRD generation workflow."""

        try:
            existing_session = self.context_manager.get_session(project_name)
            if existing_session:
                return {
                    "status": "error",
                    "message": f"Project {project_name} already exists",
                    "stage": "error"
                }

            self.context_manager.init_session(
                project_name=project_name,
                user_id=user_id,
                problem_statement=problem_statement
            )

            self.context_manager.update_session(project_name, "stage", OrchestratorState.BA_PENDING.value)
            self.context_manager.update_session(project_name, "segment", segment)
            self.context_manager.update_session(project_name, "run_count", 1)
            self.context_manager.update_session(project_name, "context", context or {})

            ba_result = await self.ba_agent.run(
                problem_statement=problem_statement,
                segment=segment,
                context=context,
                run_count=1
            )

            if not ba_result or ba_result.get("status") == "error":
                self.context_manager.update_session(project_name, "stage", OrchestratorState.BA_FAILED.value)
                return {
                    "status": "error",
                    "message": f"BA agent failed: {ba_result.get('error', 'Unknown error')}",
                    "stage": "ba_failed"
                }

            quality_gates = ba_result.get("quality_gates", {})
            gates_passed = ba_result.get("quality_gates_passed", False)

            if not gates_passed:
                self.context_manager.update_session(project_name, "stage", OrchestratorState.BA_FAILED.value)
                return {
                    "status": "error",
                    "message": "BRD failed quality gates",
                    "stage": "ba_failed",
                    "quality_gates": quality_gates
                }

            brd_markdown = ba_result.get("markdown", "")
            brd_path = self.file_manager.save_brd(project_name, brd_markdown)
            self.file_manager.save_sources(project_name, ba_result.get("sources_metadata", {}), filename="sources.json")

            self.context_manager.update_session(project_name, "ba_output", ba_result)
            self.context_manager.update_session(project_name, "stage", OrchestratorState.BA_APPROVAL.value)

            self.context_manager.add_to_history(
                project_name=project_name,
                stage="ba",
                output=brd_markdown
            )

            return {
                "status": "success",
                "stage": "ba_approval",
                "document_id": ba_result.get("document_id"),
                "output": brd_markdown,
                "file_path": brd_path,
                "approval_required": True,
                "quality_gates": quality_gates,
                "message": "BRD generated successfully. Awaiting approval to move on to the PRD."
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Orchestrator error: {str(e)}",
                "stage": "error"
            }

    async def handle_approval(
        self,
        project_name: str,
        stage: str,
        decision: str,
        feedback: Optional[str] = None
    ) -> Dict:
        """Handle approval decisions (approve, needs_changes, jump_back)."""

        try:
            session = self.context_manager.get_session(project_name)
            if not session:
                return {
                    "status": "error",
                    "message": f"Project {project_name} not found",
                    "stage": "error"
                }

            current_stage = session.get("stage")

            if stage == "ba":
                if current_stage != OrchestratorState.BA_APPROVAL.value:
                    return {
                        "status": "error",
                        "message": f"Cannot approve BA at stage {current_stage}",
                        "stage": current_stage
                    }

                if decision == "approve":
                    self.context_manager.update_session(project_name, "stage", OrchestratorState.PE_PENDING.value)
                    self.context_manager.update_session(project_name, "run_count", 1)

                    ba_output = session.get("ba_output")

                    # Inject session context — PE skill needs segment and problem_statement
                    ba_output["segment"] = session.get("segment")
                    ba_output["problem_statement"] = session.get("problem_statement")

                    pe_result = await self.pe_agent.run(
                        brd_dict=ba_output,
                        run_count=1
                    )

                    if not pe_result or pe_result.get("status") == "error":
                        self.context_manager.update_session(project_name, "stage", OrchestratorState.PE_FAILED.value)
                        return {
                            "status": "error",
                            "message": "PE agent failed to generate PRD",
                            "stage": "pe_failed"
                        }

                    prd_markdown = pe_result.get("markdown", "")
                    prd_path = self.file_manager.save_prd(project_name, prd_markdown)
                    self.file_manager.save_sources(project_name, pe_result.get("sources_metadata", {}), filename="prd-sources.json")
                    self.context_manager.update_session(project_name, "pe_output", pe_result)
                    self.context_manager.update_session(project_name, "stage", OrchestratorState.PE_APPROVAL.value)

                    self.context_manager.add_to_history(
                        project_name=project_name,
                        stage="pe",
                        output=prd_markdown
                    )

                    return {
                        "status": "success",
                        "stage": "pe_approval",
                        "document_id": pe_result.get("document_id"),
                        "output": prd_markdown,
                        "file_path": prd_path,
                        "approval_required": True,
                        "quality_gates": pe_result.get("quality_gates", {}),
                        "message": "PRD generated. Awaiting approval to move on to the RFCs."
                    }

                elif decision in ["needs_changes", "clarification"]:
                    self.context_manager.update_session(project_name, "stage", OrchestratorState.BA_CLARIFYING.value)
                    return {
                        "status": "success",
                        "stage": "ba_clarifying",
                        "questions": self._get_clarification_questions("ba"),
                        "message": "Please provide feedback to improve the BRD."
                    }

            elif stage == "pe":
                if current_stage != OrchestratorState.PE_APPROVAL.value:
                    return {
                        "status": "error",
                        "message": f"Cannot approve PE at stage {current_stage}",
                        "stage": current_stage
                    }

                if decision == "approve":
                    self.context_manager.update_session(project_name, "stage", OrchestratorState.RFC_PENDING.value)

                    pe_output = session.get("pe_output", {})
                    rfc_run_counts = {role: 1 for role in RFC_ROLES}

                    rfc_results = await self._generate_all_rfcs(
                        project_name=project_name,
                        prd_dict=pe_output,
                    )

                    self.context_manager.update_session(project_name, "rfc_outputs", rfc_results)
                    self.context_manager.update_session(project_name, "rfc_run_counts", rfc_run_counts)

                    if not any(r.get("status") == "success" for r in rfc_results.values()):
                        self.context_manager.update_session(project_name, "stage", OrchestratorState.RFC_FAILED.value)
                        return {
                            "status": "error",
                            "stage": "rfc_failed",
                            "message": "All 5 RFC sub-agents failed to generate.",
                            "errors": {role: r.get("error") for role, r in rfc_results.items()}
                        }

                    self.context_manager.update_session(project_name, "stage", OrchestratorState.RFC_APPROVAL.value)
                    self.context_manager.add_to_history(
                        project_name=project_name,
                        stage="rfc",
                        output=str(list(rfc_results.keys()))
                    )

                    return self._build_rfc_response(
                        rfc_results,
                        "All RFCs generated. Awaiting approval to complete the workflow, or describe "
                        "what needs to change (name the role, e.g. 'security: add MFA detail')."
                    )

                elif decision == "jump_back_to_ba":
                    # Was OrchestratorState.PE_JUMP_BACK_TO_BA -- a state
                    # nothing else read, so the session could never move on
                    # from here. ba_approval is what the message already
                    # promises: a valid BRD sitting there, ready to approve
                    # again or send through the same needs_changes -> feedback
                    # rework path BA already supports.
                    self.context_manager.update_session(project_name, "stage", OrchestratorState.BA_APPROVAL.value)
                    return {
                        "status": "success",
                        "stage": "ba_approval",
                        "message": "Jumped back to BA. The BRD is available to approve again or send back for changes."
                    }

                elif decision in ["needs_changes", "clarification"]:
                    self.context_manager.update_session(project_name, "stage", OrchestratorState.PE_CLARIFYING.value)
                    return {
                        "status": "success",
                        "stage": "pe_clarifying",
                        "questions": self._get_clarification_questions("pe"),
                        "message": "Please provide feedback to improve the PRD."
                    }

            elif stage == "rfc":
                if current_stage != OrchestratorState.RFC_APPROVAL.value:
                    return {
                        "status": "error",
                        "message": f"Cannot approve RFCs at stage {current_stage}",
                        "stage": current_stage
                    }

                if decision == "approve":
                    self.context_manager.update_session(project_name, "stage", OrchestratorState.DONE.value)
                    markdown_dir = self.file_manager.get_markdown_dir(project_name)
                    return {
                        "status": "success",
                        "stage": "done",
                        "message": f"Workflow complete. BRD, PRD, and all 5 RFCs approved. "
                                   f"Files are in {markdown_dir}/."
                    }

                elif decision in ["needs_changes", "clarification"]:
                    self.context_manager.update_session(project_name, "stage", OrchestratorState.RFC_CLARIFYING.value)
                    return {
                        "status": "success",
                        "stage": "rfc_clarifying",
                        "questions": self._get_clarification_questions("rfc"),
                        "message": "Please specify which RFC(s) need changes and what should change."
                    }

            return {
                "status": "error",
                "message": "Invalid stage or decision",
                "stage": current_stage
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Approval error: {str(e)}",
                "stage": "error"
            }

    async def handle_clarification_response(
        self,
        project_name: str,
        stage: str,
        responses: Dict
    ) -> Dict:
        """Handle clarification feedback and regenerate document."""

        try:
            session = self.context_manager.get_session(project_name)
            if not session:
                return {
                    "status": "error",
                    "message": f"Project {project_name} not found",
                    "stage": "error"
                }

            current_stage = session.get("stage")
            current_run = session.get("run_count", 1)
            problem_statement = session.get("problem_statement")
            segment = session.get("segment")
            context = session.get("context", {})

            feedback = "\n".join([f"{k}: {v}" for k, v in responses.items()])

            # Deep dive is accepted here alongside clarifying. Both mean "the
            # user is answering a request for feedback"; the only difference
            # is that deep dive asks for more detail. Accepting only
            # clarifying left ba_deep_dive as a state nothing could act on,
            # which is the same dead end this change fixes for reworking.
            if stage == "ba" and current_stage in (
                OrchestratorState.BA_CLARIFYING.value,
                OrchestratorState.BA_DEEP_DIVE.value,
            ):
                self.context_manager.update_session(project_name, "stage", OrchestratorState.BA_REWORKING.value)
                current_run += 1
                self.context_manager.update_session(project_name, "run_count", current_run)

                ba_result = await self.ba_agent.run(
                    problem_statement=problem_statement,
                    segment=segment,
                    context=context,
                    clarification_feedback=feedback,
                    run_count=current_run
                )

                if not ba_result or ba_result.get("status") == "error":
                    if current_run >= self.max_attempts:
                        self.context_manager.update_session(project_name, "stage", OrchestratorState.BA_FAILED.value)
                        return {
                            "status": "error",
                            "message": "BRD generation failed after max attempts",
                            "stage": "ba_failed"
                        }
                    elif current_run == self.max_reruns + 1:
                        self.context_manager.update_session(project_name, "stage", OrchestratorState.BA_DEEP_DIVE.value)
                        return {
                            "status": "success",
                            "stage": "ba_deep_dive",
                            "message": "Entering deep dive mode. Provide detailed feedback."
                        }
                    else:
                        # A transient failure (rate limit, timeout, etc.) below
                        # both thresholds above previously fell through into
                        # the success path with ba_result as None/error-shaped,
                        # crashing on save_brd and leaving the stage stuck at
                        # ba_reworking with no way out. The BRD on disk was
                        # never touched (the crash happened before save_brd),
                        # so ba_approval is a real, valid state to return to.
                        self.context_manager.update_session(project_name, "stage", OrchestratorState.BA_APPROVAL.value)
                        error_detail = (ba_result or {}).get("error") or "no response from the agent"
                        return {
                            "status": "error",
                            "message": f"BRD rework attempt {current_run} failed ({error_detail}). "
                                       "The previous BRD is unchanged -- try again, or give different feedback.",
                            "stage": "ba_approval"
                        }

                brd_markdown = ba_result.get("markdown", "")
                brd_path = self.file_manager.save_brd(project_name, brd_markdown)
                self.file_manager.save_sources(project_name, ba_result.get("sources_metadata", {}), filename="sources.json")
                self.context_manager.update_session(project_name, "ba_output", ba_result)
                self.context_manager.update_session(project_name, "stage", OrchestratorState.BA_APPROVAL.value)
                self.context_manager.add_to_history(project_name, "ba_rework", brd_markdown, feedback)

                return {
                    "status": "success",
                    "stage": "ba_approval",
                    "document_id": ba_result.get("document_id"),
                    "output": brd_markdown,
                    "file_path": brd_path,
                    "quality_gates": ba_result.get("quality_gates", {}),
                    "quality_gates_passed": ba_result.get("quality_gates_passed", False),
                    "run_number": current_run,
                    "message": f"BRD updated (attempt {current_run}). Review and approve or provide more feedback."
                }

            elif stage == "pe" and current_stage == OrchestratorState.PE_CLARIFYING.value:
                self.context_manager.update_session(project_name, "stage", OrchestratorState.PE_REWORKING.value)
                current_run += 1
                self.context_manager.update_session(project_name, "run_count", current_run)

                ba_output = session.get("ba_output")

                # Inject session context — same fix as handle_approval
                ba_output["segment"] = session.get("segment")
                ba_output["problem_statement"] = session.get("problem_statement")

                pe_result = await self.pe_agent.run(
                    brd_dict=ba_output,
                    clarification_feedback=feedback,
                    run_count=current_run
                )

                if not pe_result or pe_result.get("status") == "error":
                    if current_run >= self.max_attempts:
                        self.context_manager.update_session(project_name, "stage", OrchestratorState.PE_FAILED.value)
                        return {
                            "status": "error",
                            "message": "PRD generation failed after max attempts",
                            "stage": "pe_failed"
                        }
                    else:
                        # Same shape as the BA fix above: a transient failure
                        # below max_attempts previously fell through into the
                        # success path with pe_result as None/error-shaped,
                        # crashing on save_prd and leaving the stage stuck at
                        # pe_reworking. PE has no deep-dive tier of its own --
                        # left that way here rather than adding one as a side
                        # effect of this fix; whether PE should get one too is
                        # a separate decision.
                        self.context_manager.update_session(project_name, "stage", OrchestratorState.PE_APPROVAL.value)
                        error_detail = (pe_result or {}).get("error") or "no response from the agent"
                        return {
                            "status": "error",
                            "message": f"PRD rework attempt {current_run} failed ({error_detail}). "
                                       "The previous PRD is unchanged -- try again, or give different feedback.",
                            "stage": "pe_approval"
                        }

                prd_markdown = pe_result.get("markdown", "")
                prd_path = self.file_manager.save_prd(project_name, prd_markdown)
                self.file_manager.save_sources(project_name, pe_result.get("sources_metadata", {}), filename="prd-sources.json")
                self.context_manager.update_session(project_name, "pe_output", pe_result)
                self.context_manager.update_session(project_name, "stage", OrchestratorState.PE_APPROVAL.value)
                self.context_manager.add_to_history(project_name, "pe_rework", prd_markdown, feedback)

                return {
                    "status": "success",
                    "stage": "pe_approval",
                    "document_id": pe_result.get("document_id"),
                    "output": prd_markdown,
                    "file_path": prd_path,
                    "quality_gates": pe_result.get("quality_gates", {}),
                    "quality_gates_passed": pe_result.get("quality_gates_passed", False),
                    "run_number": current_run,
                    "message": f"PRD updated (attempt {current_run}). Review and approve or provide more feedback."
                }

            elif stage == "rfc" and current_stage == OrchestratorState.RFC_CLARIFYING.value:
                target_roles = self._match_roles_in_feedback(feedback)

                if not target_roles:
                    # Ambiguous feedback that can't be attributed to a role is
                    # a reason to ask, not to guess and rework the wrong RFC.
                    self.context_manager.update_session(project_name, "stage", OrchestratorState.RFC_APPROVAL.value)
                    return {
                        "status": "error",
                        "message": "Could not tell which RFC(s) your feedback targets. "
                                   "Please name the role explicitly, e.g. "
                                   "'security: add key rotation detail' or 'ui/ux: missing empty states'.",
                        "stage": OrchestratorState.RFC_APPROVAL.value
                    }

                self.context_manager.update_session(project_name, "stage", OrchestratorState.RFC_REWORKING.value)

                rfc_run_counts = session.get("rfc_run_counts") or {role: 1 for role in RFC_ROLES}
                rfc_outputs = session.get("rfc_outputs", {})

                failed_roles = []
                deep_dive_roles = []
                feedback_by_role = {}
                reworkable_roles = []

                for role in target_roles:
                    new_count = rfc_run_counts.get(role, 1) + 1
                    if new_count > self.max_attempts:
                        failed_roles.append(role)
                        continue
                    rfc_run_counts[role] = new_count
                    feedback_by_role[role] = feedback
                    reworkable_roles.append(role)
                    if new_count == self.max_reruns + 1:
                        deep_dive_roles.append(role)

                self.context_manager.update_session(project_name, "rfc_run_counts", rfc_run_counts)

                if reworkable_roles:
                    prd_dict = session.get("pe_output", {})
                    new_results = await self._generate_all_rfcs(
                        project_name=project_name,
                        prd_dict=prd_dict,
                        roles=reworkable_roles,
                        run_counts=rfc_run_counts,
                        feedback_by_role=feedback_by_role,
                    )
                    rfc_outputs.update(new_results)

                self.context_manager.update_session(project_name, "rfc_outputs", rfc_outputs)
                self.context_manager.update_session(project_name, "stage", OrchestratorState.RFC_APPROVAL.value)
                self.context_manager.add_to_history(project_name, "rfc_rework", str(reworkable_roles), feedback)

                message_parts = []
                if reworkable_roles:
                    message_parts.append(f"Reworked: {', '.join(reworkable_roles)}")
                if "software_architect" in reworkable_roles:
                    message_parts.append(
                        "Note: system-design changed — the other RFCs may now reference "
                        "outdated component names. Consider reworking them too if this was significant."
                    )
                if deep_dive_roles:
                    message_parts.append(
                        f"Entering deep dive for: {', '.join(deep_dive_roles)} — "
                        "provide more detailed feedback next time."
                    )
                if failed_roles:
                    message_parts.append(
                        f"FAILED after {self.max_attempts} attempts, needs manual attention: "
                        f"{', '.join(failed_roles)}"
                    )

                response = self._build_rfc_response(rfc_outputs, " | ".join(message_parts) or "RFCs updated.")
                response["run_counts"] = rfc_run_counts
                return response

            return {
                "status": "error",
                "message": "Invalid state for clarification",
                "stage": current_stage
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Clarification error: {str(e)}",
                "stage": "error"
            }

    def _get_clarification_questions(self, stage: str) -> list:
        """Get clarification questions based on stage."""
        if stage == "ba":
            return [
                "Are there specific regulatory requirements we missed?",
                "What's the expected timeline for implementation?",
                "Who are the key stakeholders involved?"
            ]
        elif stage == "pe":
            return [
                "What are the critical performance requirements?",
                "Any constraints on technology choices?",
                "What disaster recovery strategy should we use?"
            ]
        elif stage == "rfc":
            return [
                "Which RFC(s) need changes? Name the role explicitly "
                "(ui/ux, software architect / system design, security, qa, devops).",
                "What specifically should change in that RFC?"
            ]
        return []

    def _contains_keyword(self, text: str, keyword: str) -> bool:
        """Word-boundary match, same discipline as research_service.py's
        _contains_keyword — short role aliases like "qa" or "ux" need a word
        boundary or they'd match inside unrelated words."""
        return re.search(r"\b" + re.escape(keyword) + r"\b", text) is not None

    def _match_roles_in_feedback(self, feedback: str) -> List[str]:
        """Which RFC role(s) a piece of free-text feedback is targeting, by
        alias match. Returns an empty list rather than guessing when nothing
        matches — ambiguous feedback should be asked about again, not
        silently applied to the wrong (or every) role."""
        feedback_lower = feedback.lower()
        matched = []
        for role in RFC_ROLES:
            for alias in ROLE_ALIASES.get(role, ()):
                if self._contains_keyword(feedback_lower, alias):
                    matched.append(role)
                    break
        return matched

    async def _generate_all_rfcs(
        self,
        project_name: str,
        prd_dict: Dict,
        roles: Optional[List[str]] = None,
        run_counts: Optional[Dict[str, int]] = None,
        feedback_by_role: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Dict]:
        """
        Generate RFCs for the given roles (default: all 5). software_architect
        always runs first, not concurrently with the rest — the other 4
        roles' prompts reference "the system-design RFC's real component
        names", and that reference is only real if system-design has already
        been generated. True 5-way concurrency would mean Security/QA/DevOps
        claim to reference a document that doesn't exist yet. See
        rfc_skill.py's module docstring for the full reasoning.

        Persists every successful result to disk (projects/{name}/adr/) and
        adds "file_path" to each result dict before returning.
        """
        target_roles = roles if roles is not None else list(RFC_ROLES)
        run_counts = run_counts or {}
        feedback_by_role = feedback_by_role or {}

        results: Dict[str, Dict] = {}
        system_design_context: Optional[str] = None

        if "software_architect" in target_roles:
            sa_result = await self.rfc_agent.run(
                role="software_architect",
                prd_dict=prd_dict,
                clarification_feedback=feedback_by_role.get("software_architect"),
                run_count=run_counts.get("software_architect", 1),
            )
            results["software_architect"] = sa_result
            if sa_result.get("status") == "success":
                system_design_context = sa_result.get("markdown")
        else:
            # Not being (re)generated this round — reuse whatever's already
            # on disk as cross-reference context for the roles that are.
            system_design_context = self.file_manager.load_rfc(project_name, "software_architect")

        remaining_roles = [r for r in target_roles if r != "software_architect"]

        async def _run_role(role: str) -> Dict:
            return await self.rfc_agent.run(
                role=role,
                prd_dict=prd_dict,
                system_design_context=system_design_context,
                clarification_feedback=feedback_by_role.get(role),
                run_count=run_counts.get(role, 1),
            )

        if remaining_roles:
            gathered = await asyncio.gather(*(_run_role(r) for r in remaining_roles))
            for role, result in zip(remaining_roles, gathered):
                results[role] = result

        for role, result in results.items():
            if result.get("status") == "success":
                path = self.file_manager.save_rfc(project_name, role, result["markdown"])
                self.file_manager.save_rfc_sources(project_name, role, result.get("sources_metadata", {}))
                result["file_path"] = path

        return results

    def _build_rfc_response(self, rfc_results: Dict[str, Dict], message: str) -> Dict:
        """Combined view of all RFCs currently in play, for the single
        rfc_approval review — one gate for all 5 rather than five separate
        approval loops (see the private planning notes for why)."""
        quality_gates_by_role = {role: r.get("quality_gates", {}) for role, r in rfc_results.items()}
        gates_passed_by_role = {role: r.get("quality_gates_passed", False) for role, r in rfc_results.items()}
        file_paths = {role: r.get("file_path") for role, r in rfc_results.items() if r.get("file_path")}
        errors = {role: r.get("error") for role, r in rfc_results.items() if r.get("status") == "error"}
        outputs = {role: r.get("markdown") for role, r in rfc_results.items() if r.get("status") == "success"}

        return {
            "status": "success" if not errors else "partial_success",
            "stage": "rfc_approval",
            "rfc_outputs": outputs,
            "file_paths": file_paths,
            "quality_gates_by_role": quality_gates_by_role,
            "quality_gates_passed_by_role": gates_passed_by_role,
            "quality_gates_passed": bool(gates_passed_by_role) and all(gates_passed_by_role.values()) and not errors,
            "errors": errors,
            "approval_required": True,
            "message": message,
        }
