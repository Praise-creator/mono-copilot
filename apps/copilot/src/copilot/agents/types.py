from pydantic import BaseModel 
from typing import Optional


class AgentRequest(BaseModel):
    """Request to run BA or PE agent"""
    problem_statement: str
    user_id: str
    project_name: Optional[str] = None
    feedback: Optional[str] = None
    previous_output: Optional[str] = None


class AgentResponse(BaseModel):
    """Response from BA or PE agent"""
    status: str  # "success" | "error"
    output: str  # BRD or PRD markdown
    project_name: str
    stage: str  # "ba" | "pe" | "done" | "error"
    approval_required: bool


class ApprovalRequest(BaseModel):
    """User approval/rejection of agent output"""
    project_name: str
    stage: str  # "ba" | "pe"
    decision: str  # "approve" | "reject" | "needs_clarification"
    feedback: Optional[str] = None