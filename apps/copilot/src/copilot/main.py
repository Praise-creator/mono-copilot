"""
Mono-Copilot API - REST endpoints for BRD/PRD generation workflow.

Endpoints:
- POST /projects/create - Create new project
- POST /agent/start - Start BA agent to generate BRD
- POST /approve - Approve or request changes
- POST /clarification - Send clarification feedback
- GET /projects/{name}/brd - Get BRD
- GET /projects/{name}/prd - Get PRD
- GET /projects/{name}/status - Get project status
"""

import os
from typing import Optional
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import uvicorn

from .orchestrator import Orchestrator

load_dotenv()

app = FastAPI(
    title="Mono-Copilot",
    description="Enterprise MNO product development assistant",
    version="1.0.0"
)

orchestrator = Orchestrator()


class CreateProjectRequest(BaseModel):
    """Request to create a new project."""
    name: str
    segment: str = "postpaid_consumer"
    context: Optional[dict] = None


class StartAgentRequest(BaseModel):
    """Request to start BA agent."""
    project_name: str
    problem_statement: str
    segment: str = "postpaid_consumer"
    context: Optional[dict] = None


class ApprovalRequest(BaseModel):
    """Request to approve or provide feedback."""
    project_name: str
    stage: str
    decision: str
    feedback: Optional[str] = None


class ClarificationRequest(BaseModel):
    """Request to send clarification feedback."""
    project_name: str
    stage: str
    responses: dict


@app.get("/health")
async def health_check():
    """Service health check."""
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "service": "mono-copilot"
    }


@app.post("/projects/create")
async def create_project(request: CreateProjectRequest):
    """Create a new project."""
    try:
        if not request.name:
            raise ValueError("Project name required")
        
        return {
            "status": "success",
            "project_name": request.name,
            "segment": request.segment,
            "message": "Project created. Ready to generate BRD.",
            "next_action": "/agent/start"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/agent/start")
async def start_agent(request: StartAgentRequest):
    """Start BA agent to generate BRD."""
    try:
        if not request.project_name or not request.problem_statement:
            raise ValueError("project_name and problem_statement required")
        
        result = await orchestrator.process_input(
            project_name=request.project_name,
            user_id="user_1",
            problem_statement=request.problem_statement,
            segment=request.segment,
            context=request.context
        )
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/approve")
async def approve_artifact(request: ApprovalRequest):
    """Approve or request changes to BRD/PRD."""
    try:
        if not request.project_name or not request.stage or not request.decision:
            raise ValueError("project_name, stage, and decision required")
        
        result = await orchestrator.handle_approval(
            project_name=request.project_name,
            stage=request.stage,
            decision=request.decision,
            feedback=request.feedback
        )
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/clarification")
async def send_clarification(request: ClarificationRequest):
    """Send clarification feedback and regenerate document."""
    try:
        if not request.project_name or not request.stage or not request.responses:
            raise ValueError("project_name, stage, and responses required")
        
        result = await orchestrator.handle_clarification_response(
            project_name=request.project_name,
            stage=request.stage,
            responses=request.responses
        )
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/projects/{project_name}/brd")
async def get_brd(project_name: str):
    """Get BRD for a project."""
    try:
        from .services.file_manager import FileManager
        fm = FileManager()
        content = fm.load_brd(project_name)
        
        if not content:
            raise HTTPException(status_code=404, detail="BRD not found")
        
        return {
            "status": "success",
            "project_name": project_name,
            "content": content,
            "content_type": "text/markdown"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/projects/{project_name}/prd")
async def get_prd(project_name: str):
    """Get PRD for a project."""
    try:
        from .services.file_manager import FileManager
        fm = FileManager()
        content = fm.load_prd(project_name)
        
        if not content:
            raise HTTPException(status_code=404, detail="PRD not found")
        
        return {
            "status": "success",
            "project_name": project_name,
            "content": content,
            "content_type": "text/markdown"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/projects/{project_name}/status")
async def get_project_status(project_name: str):
    """Get project status and stage."""
    try:
        session = orchestrator.context_manager.get_session(project_name)
        
        if not session:
            raise HTTPException(status_code=404, detail="Project not found")
        
        return {
            "status": "success",
            "project_name": project_name,
            "stage": session.get("stage"),
            "run_count": session.get("run_count", 1),
            "problem_statement": session.get("problem_statement"),
            "segment": session.get("segment"),
            "created_at": session.get("created_at")
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/projects/{project_name}/files")
async def list_project_files(project_name: str):
    """List all files in project directory."""
    try:
        from pathlib import Path
        project_path = Path("projects") / project_name
        
        if not project_path.exists():
            raise HTTPException(status_code=404, detail="Project not found")
        
        files = []
        for file in project_path.glob("*"):
            if file.is_file():
                files.append({
                    "name": file.name,
                    "size": file.stat().st_size,
                    "modified": datetime.fromtimestamp(file.stat().st_mtime).isoformat()
                })
        
        return {
            "status": "success",
            "project_name": project_name,
            "files": files
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    from pathlib import Path
    Path("projects").mkdir(exist_ok=True)
    print("✅ Mono-Copilot started")


def run() -> None:
    """Run the server."""
    environment = os.getenv("APP_ENV", "development").lower()
    
    if environment == "development":
        print("Running in development mode with hot reload")
        uvicorn.run("copilot.main:app", host="127.0.0.1", port=8000, reload=True)
    else:
        print("Running in production mode")
        uvicorn.run("copilot.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
