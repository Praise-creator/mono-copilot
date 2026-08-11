import os
import shutil
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


def sanitize_project_name(name: str) -> str:
    """
    Normalize a project name into a safe directory name: no whitespace, no
    filesystem-unsafe characters. Leaves case and existing separators
    (hyphens, underscores) alone so it doesn't rename or collide with
    already-existing project directories — it only prevents new bad names
    (e.g. a name typed with a space) from creating a mess going forward.
    """
    slug = name.strip()
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"[^A-Za-z0-9_-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-_")
    return slug or "untitled-project"


# RFC role key -> on-disk filename stem, per projects/{name}/markdown/{filename}.md.
# Kept here (not in rfc_skill.py) since file naming is FileManager's concern;
# role identity/config lives in rfc_skill.py's ROLE_CONFIGS.
RFC_ROLE_FILENAMES = {
    "ui_ux": "ui-ux",
    "software_architect": "system-design",
    "security": "security",
    "qa": "qa",
    "devops": "devops",
}


class FileManager:
    """
    Manage BRD/PRD/RFC file I/O to projects directory.

    Layout per project: projects/{name}/markdown/ holds every generated
    document (ba-output.md, pe-output.md, and all 5 RFCs) as flat .md
    files; projects/{name}/exports/ holds every PDF generated from any of
    them. Everything else (sources.json audit trails, .session.json,
    history/) stays at the project root as internal bookkeeping rather
    than being one of the two content folders — a human opens markdown/ or
    exports/, not sources.json.

    This used to split BA/PE (project root) from RFCs (an "adr" subfolder)
    with no consistent home for either kind of document and no folder at
    all for exports until one got created ad hoc — reorganized into this
    two-folder shape on request, once real usage showed how confusing the
    split was in practice.
    """

    def __init__(self, projects_dir: str = "projects"):
        self.projects_dir = Path(projects_dir)
        self.projects_dir.mkdir(exist_ok=True)

    def get_project_dir(self, project_name: str) -> Path:
        """Get or create project directory. project_name is sanitized here so
        every caller — orchestrator, CLI, a future API — is protected the
        same way, rather than relying on each one to validate upstream."""
        safe_name = sanitize_project_name(project_name)
        project_path = self.projects_dir / safe_name
        project_path.mkdir(exist_ok=True)
        return project_path

    def get_markdown_dir(self, project_name: str) -> Path:
        """Get or create projects/{project_name}/markdown/ — every generated
        document (BRD, PRD, all 5 RFCs) lives here as a flat .md file."""
        project_dir = self.get_project_dir(project_name)
        markdown_dir = project_dir / "markdown"
        markdown_dir.mkdir(exist_ok=True)
        return markdown_dir

    def _archive_existing(self, project_dir: Path, current_path: Path) -> None:
        """Keep the previous version before a rework overwrites it. Always
        anchored at the project ROOT (not whichever subfolder the file
        currently lives in), so there's exactly one history/ per project
        regardless of whether a BRD, PRD, RFC, or sources file changed."""
        if not current_path.exists():
            return
        history_dir = project_dir / "history"
        history_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        archived_name = f"{current_path.stem}-{timestamp}{current_path.suffix}"
        shutil.copy2(current_path, history_dir / archived_name)

    def save_brd(self, project_name: str, content: str) -> str:
        """Save BRD to projects/{project_name}/markdown/ba-output.md, archiving
        the previous version"""
        project_dir = self.get_project_dir(project_name)
        markdown_dir = self.get_markdown_dir(project_name)
        brd_path = markdown_dir / "ba-output.md"
        self._archive_existing(project_dir, brd_path)
        brd_path.write_text(content)
        return str(brd_path)

    def load_brd(self, project_name: str) -> Optional[str]:
        """Load BRD from projects/{project_name}/markdown/ba-output.md"""
        safe_name = sanitize_project_name(project_name)
        brd_path = self.projects_dir / safe_name / "markdown" / "ba-output.md"
        if brd_path.exists():
            return brd_path.read_text()
        return None

    def save_prd(self, project_name: str, content: str) -> str:
        """Save PRD to projects/{project_name}/markdown/pe-output.md, archiving
        the previous version"""
        project_dir = self.get_project_dir(project_name)
        markdown_dir = self.get_markdown_dir(project_name)
        prd_path = markdown_dir / "pe-output.md"
        self._archive_existing(project_dir, prd_path)
        prd_path.write_text(content)
        return str(prd_path)

    def load_prd(self, project_name: str) -> Optional[str]:
        """Load PRD from projects/{project_name}/markdown/pe-output.md"""
        safe_name = sanitize_project_name(project_name)
        prd_path = self.projects_dir / safe_name / "markdown" / "pe-output.md"
        if prd_path.exists():
            return prd_path.read_text()
        return None

    def save_sources(self, project_name: str, content: dict, filename: str) -> str:
        """Save source verification metadata (the audit trail behind a BRD/PRD's
        claims) to projects/{project_name}/{filename} — project root, not
        markdown/ or exports/, since this is bookkeeping a human doesn't open
        the way they'd open a generated document. Archives the previous
        version first. filename is caller-specified (e.g. "sources.json" for
        BA, "prd-sources.json" for PE) so BA and PE audit trails don't collide.
        """
        project_dir = self.get_project_dir(project_name)
        sources_path = project_dir / filename
        self._archive_existing(project_dir, sources_path)
        sources_path.write_text(json.dumps(content, indent=2, default=str))
        return str(sources_path)

    def _rfc_filename(self, role: str) -> str:
        return RFC_ROLE_FILENAMES.get(role, role.replace("_", "-"))

    def save_rfc(self, project_name: str, role: str, content: str) -> str:
        """Save one role's RFC to projects/{project_name}/markdown/{role-filename}.md,
        archiving the previous version first (same _archive_existing helper
        BA/PE use, one shared history/ at project root)."""
        project_dir = self.get_project_dir(project_name)
        markdown_dir = self.get_markdown_dir(project_name)
        rfc_path = markdown_dir / f"{self._rfc_filename(role)}.md"
        self._archive_existing(project_dir, rfc_path)
        rfc_path.write_text(content)
        return str(rfc_path)

    def load_rfc(self, project_name: str, role: str) -> Optional[str]:
        """Load a previously saved RFC, or None if that role hasn't been
        generated for this project yet."""
        safe_name = sanitize_project_name(project_name)
        rfc_path = self.projects_dir / safe_name / "markdown" / f"{self._rfc_filename(role)}.md"
        if rfc_path.exists():
            return rfc_path.read_text()
        return None

    def save_rfc_sources(self, project_name: str, role: str, content: dict) -> str:
        """Save one role's RFC source-verification audit trail to
        projects/{project_name}/{role-filename}-sources.json — project root,
        alongside BA/PE's sources.json/prd-sources.json, not inside markdown/
        or exports/."""
        project_dir = self.get_project_dir(project_name)
        sources_path = project_dir / f"{self._rfc_filename(role)}-sources.json"
        self._archive_existing(project_dir, sources_path)
        sources_path.write_text(json.dumps(content, indent=2, default=str))
        return str(sources_path)

    def list_rfc_roles_present(self, project_name: str) -> list[str]:
        """Which of the 5 RFC roles already have a saved file on disk for
        this project — used by the export/view feature to know what's
        available without the caller having to probe each path itself."""
        safe_name = sanitize_project_name(project_name)
        markdown_dir = self.projects_dir / safe_name / "markdown"
        if not markdown_dir.exists():
            return []
        return [
            role for role, filename in RFC_ROLE_FILENAMES.items()
            if (markdown_dir / f"{filename}.md").exists()
        ]
