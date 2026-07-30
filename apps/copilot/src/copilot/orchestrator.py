"""
Orchestrator - Controls the 13-state workflow for BRD → PRD → ADR generation.

Routes: draft → ba_pending → ba_approval → pe_pending → pe_approval → adr_pending → done
Handles: approval gates, quality checks, clarification feedback, deep dives
"""

from enum import Enum
from typing import Optional, Dict
from datetime import datetime
import json
from pathlib import Path

from .services.context_manager import ContextManager
from .services.file_manager import FileManager
from .agents.ba_agent import BAAgent
from .agents.pe_agent import PEAgent


class OrchestratorState(Enum):
    """13-state workflow per Master Prompt."""
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
    PE_JUMP_BACK_TO_BA = "pe_jump_back_to_ba"
    DONE = "done"


class Orchestrator:
    """Orchestrates 13-state workflow for document generation."""

    def __init__(self):
        self.context_manager = ContextManager()
        self.file_manager = FileManager()
        self.ba_agent = BAAgent()
        self.pe_agent = PEAgent()
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
            self.file_manager.save_brd(project_name, brd_markdown)

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
                "approval_required": True,
                "quality_gates": quality_gates,
                "message": "BRD generated successfully. Awaiting approval."
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
                    self.file_manager.save_prd(project_name, prd_markdown)
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
                        "approval_required": True,
                        "message": "PRD generated. Awaiting approval."
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
                    self.context_manager.update_session(project_name, "stage", OrchestratorState.DONE.value)
                    return {
                        "status": "success",
                        "stage": "done",
                        "message": "Workflow complete. BRD and PRD approved."
                    }

                elif decision == "jump_back_to_ba":
                    self.context_manager.update_session(project_name, "stage", OrchestratorState.PE_JUMP_BACK_TO_BA.value)
                    return {
                        "status": "success",
                        "stage": "pe_jump_back_to_ba",
                        "message": "Jumped back to BA. You can now modify the BRD."
                    }

                elif decision in ["needs_changes", "clarification"]:
                    self.context_manager.update_session(project_name, "stage", OrchestratorState.PE_CLARIFYING.value)
                    return {
                        "status": "success",
                        "stage": "pe_clarifying",
                        "questions": self._get_clarification_questions("pe"),
                        "message": "Please provide feedback to improve the PRD."
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

            if stage == "ba" and current_stage == OrchestratorState.BA_CLARIFYING.value:
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

                brd_markdown = ba_result.get("markdown", "")
                self.file_manager.save_brd(project_name, brd_markdown)
                self.context_manager.update_session(project_name, "ba_output", ba_result)
                self.context_manager.update_session(project_name, "stage", OrchestratorState.BA_APPROVAL.value)
                self.context_manager.add_to_history(project_name, "ba_rework", brd_markdown, feedback)

                return {
                    "status": "success",
                    "stage": "ba_approval",
                    "document_id": ba_result.get("document_id"),
                    "output": brd_markdown,
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

                prd_markdown = pe_result.get("markdown", "")
                self.file_manager.save_prd(project_name, prd_markdown)
                self.context_manager.update_session(project_name, "pe_output", pe_result)
                self.context_manager.update_session(project_name, "stage", OrchestratorState.PE_APPROVAL.value)
                self.context_manager.add_to_history(project_name, "pe_rework", prd_markdown, feedback)

                return {
                    "status": "success",
                    "stage": "pe_approval",
                    "document_id": pe_result.get("document_id"),
                    "output": prd_markdown,
                    "run_number": current_run,
                    "message": f"PRD updated (attempt {current_run}). Review and approve or provide more feedback."
                }

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
        return []
