"""
Line-number-referencing feedback resolution — the "I don't like line 45"
half of feedback handling. Free-text feedback (today's only mode) keeps
working exactly as it does now; this is a pre-processing step that only
fires when a feedback string actually names a line number, enriching it
with the real content at that location before it ever reaches the
orchestrator.

Deliberately NOT wired into orchestrator.py itself. This produces an
enriched feedback string and hands it to the exact same
handle_clarification_response() that free-text feedback already uses — line
referencing is a smarter way to build that input, not a new code path
through the state machine. Zero changes needed to already-tested rework
logic.
"""

import re
from typing import Optional, Tuple


# Matches "line 45", "line #45", "lines 40-45", "lines 40 to 45", etc.
# Word-boundary on line/lines so it doesn't fire on unrelated text that
# happens to contain those letters elsewhere.
_LINE_REF_RE = re.compile(
    r"\bline[s]?\b\s*#?\s*(\d+)(?:\s*(?:-|to|through)\s*(\d+))?",
    re.IGNORECASE,
)

_CONTEXT_LINES_BEFORE = 2
_CONTEXT_LINES_AFTER = 2


def _extract_line_range(feedback_text: str) -> Optional[Tuple[int, int]]:
    """First line-reference found in the feedback text, as a 1-indexed
    (start, end) tuple. None if no reference is present at all."""
    match = _LINE_REF_RE.search(feedback_text)
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else start
    if end < start:
        start, end = end, start
    return start, end


def resolve_line_reference(feedback_text: str, document_markdown: Optional[str]) -> Optional[str]:
    """
    If feedback_text names a line or line range, return an enriched
    feedback string that includes the actual content at that location —
    grounding "line 45" in what line 45 really says, rather than trusting a
    number the agent has no other way to verify. Returns None if no line
    reference is found (or no document is available to resolve against),
    so the caller falls back to using feedback_text exactly as-is — today's
    free-text path, completely unchanged.
    """
    if not document_markdown:
        return None

    line_range = _extract_line_range(feedback_text)
    if line_range is None:
        return None

    start, end = line_range
    lines = document_markdown.split("\n")
    total_lines = len(lines)

    if start > total_lines:
        # Referenced a line past the end of the document — say so plainly
        # rather than silently clamping to a different line and having the
        # agent act on the wrong spot without anyone noticing.
        return (
            f"{feedback_text}\n\n"
            f"[Note: line {start} was referenced, but this document only has "
            f"{total_lines} lines. Re-check the line number against the current "
            f"document before assuming this feedback applies to the intended spot.]"
        )

    end = min(end, total_lines)
    context_start = max(1, start - _CONTEXT_LINES_BEFORE)
    context_end = min(total_lines, end + _CONTEXT_LINES_AFTER)

    excerpt_lines = []
    for i in range(context_start, context_end + 1):
        marker = ">>" if start <= i <= end else "  "
        excerpt_lines.append(f"{marker} {i}: {lines[i - 1]}")
    excerpt = "\n".join(excerpt_lines)

    line_label = f"line {start}" if start == end else f"lines {start}-{end}"

    return (
        f"{feedback_text}\n\n"
        f"[Referenced {line_label} — actual current document content shown below "
        f"(marked lines are the target, unmarked lines are surrounding context "
        f"only, for orientation):\n"
        f"{excerpt}\n"
        f"Apply the requested change to the marked line(s) specifically, keeping "
        f"the rest of the document's structure and voice consistent.]"
    )
