"""
Entry classifier — decides where a fresh chat input should enter the pipeline.

Rule-based first, deliberately. The pipeline is: idea -> BRD -> PRD -> RFCs -> ADR,
and a user can walk in at any point (a raw idea, a pasted PRD, an existing project
name). Guessing wrong here burns a real 30-60s OpenAI call on the wrong stage, so
every check below is either a cheap string/structure match or an explicit question
back to the user — never a silent best-guess.

The one deliberately unfinished piece is `_classify_with_model`: a fallback for
input that isn't resolved by any rule-based check. It's stubbed to return
AMBIGUOUS_NEEDS_CLARIFICATION rather than guessing, so behavior stays honest even
before that fallback is wired to a real (cheap, non-BA/PE) classification call.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional


class EntryPath(Enum):
    """Every place a fresh input can land."""
    RESUME_LIVE_SESSION = "resume_live_session"
    RESUME_FROM_DISK_NO_SESSION = "resume_from_disk_no_session"
    NEW_PROJECT_FROM_IDEA = "new_project_from_idea"
    STANDALONE_FROM_PRD = "standalone_from_prd"
    STANDALONE_FROM_BRD_PE_NOT_WIRED = "standalone_from_brd_pe_not_wired"
    STANDALONE_RFC_REQUEST = "standalone_rfc_request"
    AD_HOC_QUESTION = "ad_hoc_question"
    AMBIGUOUS_NEEDS_CLARIFICATION = "ambiguous_needs_clarification"


@dataclass
class ClarificationQuestion:
    """A structured question to ask back, never an open-ended re-prompt."""
    question: str
    options: List[str]


@dataclass
class ClassificationResult:
    """What the classifier decided, and why — reason is shown to the user."""
    path: EntryPath
    reason: str
    project_name: Optional[str] = None
    confidence: str = "high"  # "high" | "medium" | "low"
    clarification: Optional[ClarificationQuestion] = None
    extracted_document: Optional[str] = None


# Section headers that identify a pasted BRD/PRD even without frontmatter.
# Matching any 2+ of these is enough signal — real BRDs/PRDs from this system
# always carry several of them together.
_BRD_SECTION_MARKERS = [
    "overview", "benefits", "scope", "process flows", "use cases",
    "user stories", "business rules", "regulatory",
]
_PRD_SECTION_MARKERS = [
    "architectural impact", "design considerations", "integration architecture",
    "technical architecture", "exception management", "non functional requirements",
    "non-functional requirements", "rollback strategy",
]

_EXPLICIT_COMMANDS = {
    "/new": EntryPath.NEW_PROJECT_FROM_IDEA,
    "/rfc": EntryPath.STANDALONE_RFC_REQUEST,
}

_QUESTION_STARTERS = (
    "what", "how", "why", "when", "where", "which", "who", "should", "can", "does", "is",
)

# Below this length with no document markers, treat as ad-hoc/ambiguous rather
# than a real problem statement — a genuine BRD-worthy idea reads like a
# paragraph, not a sentence.
_MIN_IDEA_LENGTH = 120


def _normalize(text: str) -> str:
    return text.strip().lower()


def _count_markers(text_lower: str, markers: List[str]) -> int:
    return sum(1 for m in markers if m in text_lower)


def _looks_like_question(text: str, text_lower: str) -> bool:
    if text.strip().endswith("?"):
        return True
    first_word = text_lower.split(" ", 1)[0] if text_lower else ""
    return first_word in _QUESTION_STARTERS


class EntryClassifier:
    """
    Classifies a fresh chat input into an EntryPath.

    Needs read access to what's live (context_manager) and what's on disk
    (existing_projects, computed by the caller from the projects/ directory)
    so it can tell "resume a live session" apart from "found on disk, but no
    session survived a restart" — the latter is the honest state of the
    system today, since ContextManager is in-memory only.
    """

    def __init__(self, context_manager, existing_projects: Optional[List[str]] = None):
        self.context_manager = context_manager
        self.existing_projects = existing_projects or []

    def classify(self, user_input: str) -> ClassificationResult:
        text = user_input.strip()
        text_lower = _normalize(text)

        # 1. Explicit commands short-circuit everything else.
        if text_lower in _EXPLICIT_COMMANDS:
            return ClassificationResult(
                path=_EXPLICIT_COMMANDS[text_lower],
                reason=f"Explicit command: {text_lower}",
                confidence="high",
            )

        if text_lower.startswith("/resume "):
            name = text[len("/resume "):].strip()
            return self._resolve_project_name(name, explicit=True)

        # 2. Does this name an existing project?
        exact_match = next(
            (p for p in self.existing_projects if p.lower() == text_lower), None
        )
        if exact_match:
            return self._resolve_project_name(exact_match, explicit=False)

        # 3. Structural document detection — pasted BRD or PRD.
        prd_hits = _count_markers(text_lower, _PRD_SECTION_MARKERS)
        brd_hits = _count_markers(text_lower, _BRD_SECTION_MARKERS)

        if prd_hits >= 2:
            return ClassificationResult(
                path=EntryPath.STANDALONE_FROM_PRD,
                reason=(
                    f"Pasted text matches {prd_hits} PRD section markers — "
                    "treating this as an existing PRD, entering at the RFC stage."
                ),
                confidence="high" if prd_hits >= 3 else "medium",
                extracted_document=text,
            )

        if brd_hits >= 2 and prd_hits < 2:
            return ClassificationResult(
                path=EntryPath.STANDALONE_FROM_BRD_PE_NOT_WIRED,
                reason=(
                    f"Pasted text matches {brd_hits} BRD section markers — this looks "
                    "like an existing BRD without a PRD."
                ),
                confidence="high" if brd_hits >= 3 else "medium",
                extracted_document=text,
            )

        # 4. Short, question-shaped input with no document markers — likely
        #    ad-hoc, not a real problem statement.
        if len(text) < _MIN_IDEA_LENGTH:
            if _looks_like_question(text, text_lower):
                return ClassificationResult(
                    path=EntryPath.AD_HOC_QUESTION,
                    reason="Short, question-shaped input with no document markers.",
                    confidence="medium",
                )
            return ClassificationResult(
                path=EntryPath.AMBIGUOUS_NEEDS_CLARIFICATION,
                reason="Input is short and doesn't clearly read as a problem statement.",
                confidence="low",
                clarification=ClarificationQuestion(
                    question="What would you like to do?",
                    options=[
                        "Start a new idea from scratch (I'll draft a BRD)",
                        "I already have a BRD or PRD to paste in",
                        "I just have a question, not a formal document request",
                    ],
                ),
            )

        # 5. Long enough to plausibly be a real problem statement, and no
        #    document markers fired above — treat as a fresh idea.
        return ClassificationResult(
            path=EntryPath.NEW_PROJECT_FROM_IDEA,
            reason="Long-form input with no BRD/PRD structural markers — treating as a new idea.",
            confidence="high" if len(text) > 300 else "medium",
        )

    def _resolve_project_name(self, name: str, explicit: bool) -> ClassificationResult:
        if self.context_manager.session_exists(name):
            return ClassificationResult(
                path=EntryPath.RESUME_LIVE_SESSION,
                project_name=name,
                reason=f"'{name}' has a live session — resuming where it left off.",
                confidence="high",
            )

        if name in self.existing_projects:
            return ClassificationResult(
                path=EntryPath.RESUME_FROM_DISK_NO_SESSION,
                project_name=name,
                reason=(
                    f"'{name}' exists on disk (projects/{name}/) but has no active "
                    "session — sessions don't survive a restart yet."
                ),
                confidence="high",
            )

        if explicit:
            return ClassificationResult(
                path=EntryPath.AMBIGUOUS_NEEDS_CLARIFICATION,
                reason=f"No project named '{name}' found, on disk or live.",
                confidence="high",
                clarification=ClarificationQuestion(
                    question=f"No project called '{name}' exists. What next?",
                    options=["Start it as a new project", "Show existing project names"],
                ),
            )

        # Shouldn't reach here in normal flow (caller only invokes this on a
        # confirmed exact_match), kept as a safe fallback.
        return ClassificationResult(
            path=EntryPath.AMBIGUOUS_NEEDS_CLARIFICATION,
            reason="Unresolved project reference.",
            confidence="low",
        )

    def _classify_with_model(self, user_input: str) -> ClassificationResult:
        """
        Placeholder for a cheap, non-BA/PE model call to break ties on input
        that no rule above resolves confidently. Deliberately not wired yet —
        returning AMBIGUOUS here (via the caller's rule 4/5 fallback) is the
        honest behavior until this is built and tested on its own.
        """
        raise NotImplementedError(
            "Model-assisted classification isn't wired yet — rule-based "
            "fallback (ambiguous-with-options) is used instead."
        )


def list_projects_on_disk(projects_dir: Path) -> List[str]:
    """
    Project names on disk, excluding non-project entries (dotfiles, the
    known legacy stray-output directory).
    """
    if not projects_dir.exists():
        return []
    names = []
    for entry in sorted(projects_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name.startswith("_"):
            continue
        names.append(entry.name)
    return names
