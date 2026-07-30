import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional


class FileManager:
    """Manage BRD/PRD file I/O to projects directory"""

    def __init__(self, projects_dir: str = "projects"):
        self.projects_dir = Path(projects_dir)
        self.projects_dir.mkdir(exist_ok=True)

    def get_project_dir(self, project_name: str) -> Path:
        """Get or create project directory"""
        project_path = self.projects_dir / project_name
        project_path.mkdir(exist_ok=True)
        return project_path

    def _archive_existing(self, project_dir: Path, current_path: Path) -> None:
        """Keep the previous version before a rework overwrites it"""
        if not current_path.exists():
            return
        history_dir = project_dir / "history"
        history_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        archived_name = f"{current_path.stem}-{timestamp}{current_path.suffix}"
        shutil.copy2(current_path, history_dir / archived_name)

    def save_brd(self, project_name: str, content: str) -> str:
        """Save BRD to projects/{project_name}/ba-output.md, archiving the previous version"""
        project_dir = self.get_project_dir(project_name)
        brd_path = project_dir / "ba-output.md"
        self._archive_existing(project_dir, brd_path)
        brd_path.write_text(content)
        return str(brd_path)

    def load_brd(self, project_name: str) -> Optional[str]:
        """Load BRD from projects/{project_name}/ba-output.md"""
        brd_path = self.projects_dir / project_name / "ba-output.md"
        if brd_path.exists():
            return brd_path.read_text()
        return None

    def save_prd(self, project_name: str, content: str) -> str:
        """Save PRD to projects/{project_name}/pe-output.md, archiving the previous version"""
        project_dir = self.get_project_dir(project_name)
        prd_path = project_dir / "pe-output.md"
        self._archive_existing(project_dir, prd_path)
        prd_path.write_text(content)
        return str(prd_path)

    def load_prd(self, project_name: str) -> Optional[str]:
        """Load PRD from projects/{project_name}/pe-output.md"""
        prd_path = self.projects_dir / project_name / "pe-output.md"
        if prd_path.exists():
            return prd_path.read_text()
        return None