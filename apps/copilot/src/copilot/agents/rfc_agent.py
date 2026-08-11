"""RFC Agent orchestrates RFC generation for any of the 5 sub-agent roles.

One class instead of five (UIUXAgent, SecurityAgent, ...) for the same reason
rfc_skill.py is one module instead of five — the roles differ in data
(prompt, gates, sourcing), not in how they're invoked or validated.
"""

from typing import Optional, Dict
from ..skills.rfc_skill import generate_rfc, ROLE_CONFIGS


class RFCAgent:
    """
    RFC Sub-Agent (role-parameterized).

    Takes an approved PRD from the PE agent and generates one role's RFC:
    UI/UX, Software Architect (system-design), Security, QA, or DevOps.

    Does not synthesize an ADR and does not know anything about ADR quality
    gates — that stays out of scope here (see rfc_skill.py's module
    docstring for the full explanation).
    """

    def __init__(self):
        """Initialize RFC Agent."""
        pass

    async def run(
        self,
        role: str,
        prd_dict: Dict,
        system_design_context: Optional[str] = None,
        clarification_feedback: Optional[str] = None,
        run_count: int = 1,
    ) -> Dict:
        """
        Execute RFC workflow for one role.

        Args:
            role: One of "ui_ux", "software_architect", "security", "qa", "devops"
            prd_dict: Approved PRD from PE agent
                {
                    "document_id": "PRD-...",
                    "markdown": "# PRD\\n...",
                    "quality_gates_passed": True
                }
            system_design_context: The Software Architect RFC's markdown, if
                already generated this run — passed to the other 4 roles so
                they can reference real component names instead of inventing
                their own. None for the software_architect role itself, and
                None on the first call in a run before it's been generated.
            clarification_feedback: User feedback from a previous run, if this
                specific role is being reworked.
            run_count: Attempt number for this role (independent per role —
                reworking Security doesn't advance QA's counter).

        Returns:
            {
                "status": "success" or "error",
                "role": role,
                "document_id": "RFC-SECURITY-...",
                "markdown": "# Security RFC\\n...",
                "structured": {...},
                "sources_metadata": {...},
                "quality_gates": {...},
                "quality_gates_passed": bool,
                "approval_required": True,
                "generated_at": timestamp,
                "run_count": run_count
            }
        """
        try:
            if role not in ROLE_CONFIGS:
                return {
                    "status": "error",
                    "role": role,
                    "error": f"Unknown RFC role: {role}. Valid roles: {list(ROLE_CONFIGS.keys())}",
                    "markdown": None,
                    "quality_gates_passed": False,
                }

            if not prd_dict:
                return {
                    "status": "error",
                    "role": role,
                    "error": "PRD input required",
                    "markdown": None,
                    "quality_gates_passed": False,
                }

            # Deliberately NOT checking prd_dict.get("quality_gates_passed") here.
            # This used to hard-block RFC generation whenever any PE gate failed --
            # but the orchestrator's whole approval model is "the human is the
            # real gate": handle_approval already lets a person approve a PRD
            # despite a failed automated gate (same as BA), and _generate_all_rfcs
            # is only ever called from inside that already-approved path. This
            # check was contradicting that human decision rather than enforcing
            # anything the orchestrator hadn't already decided -- confirmed live
            # when a real PE gate failure + a legitimate human approval caused
            # all 5 RFC roles to fail identically with "PRD must be approved
            # before RFC generation", even though a human had, in fact, approved it.

            result = await generate_rfc(
                role=role,
                prd_dict=prd_dict,
                system_design_context=system_design_context,
                clarification_feedback=clarification_feedback,
                run_count=run_count,
            )

            return result

        except Exception as e:
            return {
                "status": "error",
                "role": role,
                "error": str(e),
                "markdown": None,
                "quality_gates_passed": False,
            }
