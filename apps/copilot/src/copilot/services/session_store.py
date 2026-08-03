"""
Disk persistence for orchestrator session state — the piece that lets a
project survive quitting the terminal. ContextManager is the only intended
caller; every other file keeps talking to ContextManager exactly as before,
unaware persistence exists underneath it.

Stored at projects/{name}/.session.json — dot-prefixed so it reads clearly
as internal state (not a document a human should open or that the export
step should ever list alongside ba-output.md/pe-output.md/adr/*.md).

json.dumps(..., default=str) is a defensive backstop, not a load-bearing
conversion: ContextManager is responsible for keeping session dicts
JSON-plain (timestamps as ISO strings, not raw datetime objects) so a
reloaded session is identical to a freshly-created one, not a different
shape depending on whether persistence happened to kick in.
"""

import json
from pathlib import Path
from typing import Optional, Dict, List

from .file_manager import sanitize_project_name


class SessionStore:
    """Reads/writes projects/{name}/.session.json. Pure I/O — no business
    logic about what a session dict should contain lives here; that's
    ContextManager's job."""

    def __init__(self, projects_dir: str = "projects"):
        self.projects_dir = Path(projects_dir)

    def _session_path(self, project_name: str) -> Path:
        # Reuses FileManager's sanitize_project_name so a project's session
        # file always lands in the exact same folder as its other
        # artifacts (ba-output.md, adr/, exports/) — one canonical name
        # resolution, not a second copy of the sanitization rule.
        safe_name = sanitize_project_name(project_name)
        return self.projects_dir / safe_name / ".session.json"

    def save_session(self, project_name: str, session: Dict) -> str:
        path = self._session_path(project_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(session, indent=2, default=str))
        return str(path)

    def load_session(self, project_name: str) -> Optional[Dict]:
        path = self._session_path(project_name)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            # Corrupt or partially-written file (e.g. process killed
            # mid-write) — fail safe to "no session" rather than crash the
            # whole app on a bad file. Whoever calls this then treats it as
            # a fresh start, which is the honest fallback: we genuinely
            # don't know what state it was in.
            return None

    def exists(self, project_name: str) -> bool:
        return self._session_path(project_name).exists()

    def delete_session(self, project_name: str) -> None:
        """Not currently called anywhere — kept for completeness (e.g. a
        future '/forget this project' command) rather than leaving no way
        to clear persisted state at all."""
        path = self._session_path(project_name)
        if path.exists():
            path.unlink()

    def list_persisted_projects(self) -> List[str]:
        """Project names that have a real, resumable session on disk —
        stronger signal than 'a folder exists' (list_projects_on_disk in
        entry_classifier.py), since a project could have a folder from an
        RFC-tool-only invocation with no orchestrator session ever created."""
        if not self.projects_dir.exists():
            return []
        return sorted(
            p.name for p in self.projects_dir.iterdir()
            if p.is_dir() and (p / ".session.json").exists()
        )
