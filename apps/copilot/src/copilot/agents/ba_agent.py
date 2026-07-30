"""Business Analyst Agent orchestrates the BA workflow."""

from typing import Optional, Dict
from ..skills.ba_skill import generate_brd


class BAAgent:
    """
    Business Analyst Agent.
    
    Simulates a BA analyst that understands business problems,
    identifies benefits, defines scope, and creates user stories.
    """
    
    def __init__(self):
        """Initialize BA Agent."""
        pass
    
    async def run(
        self,
        problem_statement: str,
        segment: str,
        context: Optional[Dict] = None,
        clarification_feedback: Optional[str] = None,
        run_count: int = 1
    ) -> Dict:
        """
        Execute BA workflow to generate BRD.
        
        Args:
            problem_statement: Business problem description
            segment: Target segment (e.g., "postpaid_consumer", "enterprise")
            context: Additional context dictionary
            clarification_feedback: User feedback from previous run
            run_count: Attempt number (1=first, 2-5=rework, 6+=deep dive)
        
        Returns:
            {
                "status": "success" or "error",
                "document_id": "BRD-2026-0722-001",
                "markdown": "# BRD\n...",
                "structured": {...},
                "sources_metadata": {...},
                "quality_gates": {...},
                "quality_gates_passed": bool,
                "approval_required": True,
                "generated_at": timestamp,
                "run_count": run_count
            }
        
        Raises:
            Exception: If BRD generation fails
        """
        try:
            # Call BA skill to generate BRD
            result = await generate_brd(
                problem_statement=problem_statement,
                segment=segment,
                context=context,
                clarification_feedback=clarification_feedback,
                run_count=run_count
            )
            
            return result
        
        except Exception as e:
            return {
                "status": "error",
                "document_id": None,
                "error": str(e),
                "markdown": None
            }
