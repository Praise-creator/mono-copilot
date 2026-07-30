"""Product Engineer Agent orchestrates the PE workflow."""

from typing import Optional, Dict
from ..skills.pe_skill import generate_prd


class PEAgent:
    """
    Product Engineer Agent.
    
    Takes approved BRD from BA and generates PRD with:
    - Architectural impact analysis
    - Design considerations
    - Integration architecture
    - Technical architecture
    - Exception management
    - Non-functional requirements
    - Rollback strategy
    - Mermaid diagrams (architecture, integrations, exceptions)
    
    Uses web search to validate technology choices and integration patterns.
    Integrates ResearchService for verifying architectural decisions.
    """
    
    def __init__(self):
        """Initialize PE Agent."""
        pass
    
    async def run(
        self,
        brd_dict: Dict,
        clarification_feedback: Optional[str] = None,
        run_count: int = 1
    ) -> Dict:
        """
        Execute PE workflow to generate PRD.
        
        Args:
            brd_dict: Approved BRD from BA agent
                {
                    "document_id": "BRD-...",
                    "markdown": "# BRD\n...",
                    "structured": {...},
                    "sources_metadata": {...},
                    "quality_gates_passed": True
                }
            clarification_feedback: User feedback from previous run
            run_count: Attempt number (1=first, 2-5=rework, 6+=deep dive)
        
        Returns:
            {
                "status": "success" or "error",
                "document_id": "PRD-2026-0722-001",
                "brd_reference": "BRD-2026-0722-001",
                "markdown": "# PRD\n...",
                "structured": {...},
                "sources_metadata": {...},
                "quality_gates": {...},
                "quality_gates_passed": bool,
                "approval_required": True,
                "generated_at": timestamp,
                "run_count": run_count,
                "file_path": "/path/to/prd.md"
            }
        
        Raises:
            Exception: If PRD generation fails
        """
        try:
            # Validate BRD input
            if not brd_dict:
                return {
                    "status": "error",
                    "document_id": None,
                    "error": "BRD input required",
                    "markdown": None,
                    "quality_gates_passed": False
                }
            
            if not brd_dict.get("quality_gates_passed"):
                return {
                    "status": "error",
                    "document_id": None,
                    "error": "BRD must be approved before PRD generation",
                    "markdown": None,
                    "quality_gates_passed": False
                }
            
            # Call PE skill to generate PRD
            result = await generate_prd(
                brd_dict=brd_dict,
                clarification_feedback=clarification_feedback,
                run_count=run_count
            )
            
            return result
        
        except Exception as e:
            return {
                "status": "error",
                "document_id": None,
                "error": str(e),
                "markdown": None,
                "quality_gates_passed": False
            }
