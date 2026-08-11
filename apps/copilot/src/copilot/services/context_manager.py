from datetime import datetime
from typing import Optional

from .session_store import SessionStore

from .session_store import SessionStore


class ContextManager:
    """
    Manage session state — in-memory, transparently backed by disk via
    SessionStore. Every method keeps its exact original signature and
    return shape; persistence is a side effect, not a new interface callers
    need to know about. orchestrator.py, main.py, and every agent/skill
    keep working completely unchanged.

    Timestamps are stored as ISO strings (not raw datetime objects) at
    creation time, not just when serialized — so a session freshly created
    this run and a session reloaded from disk after a restart are
    byte-for-byte the same shape, not two different representations
    depending on whether persistence happened to kick in.
    """

    def __init__(self):
        self.sessions: Dict[str, dict] = {}
        self.session_store = SessionStore()

    def init_session(
        self,
        project_name: str,
        user_id: str,
        problem_statement: str
    ) -> None:
        """Initialize new session"""
        self.sessions[project_name] = {
            "user_id": user_id,
            "problem_statement": problem_statement,
            "stage": "ba",
            "ba_output": None,
            "pe_output": None,
            "feedback": None,
            "created_at": datetime.now().isoformat(),
            "history": []
        }
        self._persist(project_name)

    def get_session(self, project_name: str) -> Optional[dict]:
        """Retrieve session by project name. Transparently hydrates from
        disk on first access if the project isn't already in memory (e.g.
        after a restart) — callers never need to know or care which
        happened."""
        if project_name in self.sessions:
            return self.sessions[project_name]

        loaded = self.session_store.load_session(project_name)
        if loaded is not None:
            self.sessions[project_name] = loaded

        return self.sessions.get(project_name)

    def update_session(self, project_name: str, key: str, value) -> None:
        """Update session value"""
        if project_name not in self.sessions:
            # Might exist on disk but not yet hydrated this run — normal
            # flow always calls get_session/init_session first, but this is
            # a safe fallback rather than silently dropping the update.
            self.get_session(project_name)
        if project_name in self.sessions:
            self.sessions[project_name][key] = value
            self._persist(project_name)

    def add_to_history(
        self,
        project_name: str,
        stage: str,
        output: str,
        feedback: Optional[str] = None
    ) -> None:
        """Track feedback/output history"""
        if project_name in self.sessions:
            self.sessions[project_name]["history"].append({
                "stage": stage,
                "output": output,
                "feedback": feedback,
                "timestamp": datetime.now().isoformat(),
            })
            self._persist(project_name)

    def session_exists(self, project_name: str) -> bool:
        """Check if session exists — in memory, or persisted on disk from a
        prior run. This is what upgrades EntryClassifier's
        RESUME_FROM_DISK_NO_SESSION path to genuinely resumable: that path
        existed specifically because sessions never survived a restart
        before; now that they do, a project last touched in an earlier
        session correctly reports as existing here too, no changes needed
        in entry_classifier.py itself."""
        if project_name in self.sessions:
            return True
        return self.session_store.exists(project_name)

    def _persist(self, project_name: str) -> None:
        session = self.sessions.get(project_name)
        if session is not None:
            self.session_store.save_session(project_name, session)
