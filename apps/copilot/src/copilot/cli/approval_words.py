"""
Shared approval-word matching for the BA/PE approval gates.

Single source of truth so test_full_run.py and test_guided_start.py (and
the interactive-session router) can't silently drift apart on what counts
as approval — that's exactly how the earlier "finish" bug happened, where
one place recognized it and another didn't.
"""

import re

APPROVAL_WORDS = {
    "approve", "approved", "a", "yes", "y", "yeah", "yep", "sure",
    "ok", "okay", "good", "great", "fine", "done", "finish", "finished",
    "complete", "completed", "ship it", "lgtm", "looks good", "good to go",
    "no changes", "no changes needed", "that's fine", "thats fine", "all good"
}

# Presence of any of these means the person is qualifying their response
# with a change request, not giving pure approval, even if an approval word
# also appears -- "yes, but change X" must not count as approval.
_NEGATION_MARKERS = (
    "but", "except", "however", "although", "though", "unless", "instead",
    "change", "fix", "add", "remove", "update", "modify", "revise",
    "don't", "dont", "not ",
)

# Above this many words, a response reads as a real sentence of feedback
# rather than a short acknowledgment -- even if it happens to contain an
# approval word somewhere in it.
_MAX_APPROVAL_WORD_COUNT = 6


def is_approval(text: str) -> bool:
    """
    Real conversational approval rarely matches a canonical phrase exactly
    -- "yes approved", "yeah looks good to me", "ok approve it" are all
    genuine approvals that a strict exact-match against APPROVAL_WORDS
    would miss (and silently misroute as feedback instead, which is worse
    than a false positive here: it burns a real rework cycle on an
    approval the person already gave). Exact match is checked first as the
    cheap common case; short phrases containing an approval word AND no
    negation/change marker are treated as approval too.
    """
    normalized = text.strip().lower()

    if normalized in APPROVAL_WORDS:
        return True

    if any(neg in normalized for neg in _NEGATION_MARKERS):
        return False

    if len(normalized.split()) > _MAX_APPROVAL_WORD_COUNT:
        return False

    return any(
        re.search(r"\b" + re.escape(word) + r"\b", normalized)
        for word in APPROVAL_WORDS
    )
