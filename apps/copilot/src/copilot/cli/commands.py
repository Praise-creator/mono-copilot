"""CLI commands """

import asyncio
from typing import Any, Optional

from copilot.orchestrator import Orchestrator
from copilot.services.context_manager import ContextManager
from copilot.services.file_manager import FileManager
from copilot.services.session_store import SessionStore


def list_projects() -> list[str]:
    return SessionStore().list_persisted_projects()


def show_brd(project: str) -> Optional[str]:
    return FileManager().load_brd(project)


def show_prd(project: str) -> Optional[str]:
    return FileManager().load_prd(project)


def show_sources(project: str) -> Optional[str]:
    fm = FileManager()
    proj = fm.get_project_dir(project)
    for fname in ("sources.json", "prd-sources.json"):
        p = proj / fname
        if p.exists():
            return p.read_text()
    return None


async def _start_async(project: str, problem: str, segment: str, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        cm = ContextManager()
        cm.init_session(project_name=project, user_id="cli", problem_statement=problem)
        cm.update_session(project, "stage", "ba")
        cm.update_session(project, "segment", segment)
        fm = FileManager()
        fm.save_brd(project, f"# Placeholder BRD for {project}\n\n{problem}\n")
        return {"status": "success", "message": "dry-run session created"}
    orch = Orchestrator()
    return await orch.process_input(project_name=project, user_id="cli", problem_statement=problem, segment=segment)


def start_headless(project: str, problem: str, segment: str = "", dry_run: bool = False) -> dict[str, Any]:
    return asyncio.run(_start_async(project, problem, segment, dry_run=dry_run))


def approve(project: str, stage: str, decision: str) -> dict[str, Any]:
    return asyncio.run(Orchestrator().handle_approval(project_name=project, stage=stage, decision=decision))


def feedback(project: str, stage: str, message: str) -> dict[str, Any]:
    orch = Orchestrator()
    # first signal needs_changes, then pass clarification feedback
    res1 = asyncio.run(orch.handle_approval(project_name=project, stage=stage, decision="needs_changes"))
    res2 = asyncio.run(orch.handle_clarification_response(project_name=project, stage=stage, responses={"feedback": message}))
    return {"approval_step": res1, "clarification_step": res2}