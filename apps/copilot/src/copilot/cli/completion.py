"""
Tab completion for the interactive session.

WHY THIS EXISTS
---------------
Resuming a project requires typing its name exactly. entry_classifier.py
matches on equality:

    exact_match = next((p for p in self.existing_projects if p.lower() == text_lower), None)

There is no fuzzy match and no "did you mean". So "upsell-assit" does not
near-miss "upsell-assist" — it fails to match anything, falls through to the
length checks, lands on AMBIGUOUS_NEEDS_CLARIFICATION, and starts an
IntakeAgent conversation. That is a real API call, spent asking the user what
they meant about a project sitting on disk the whole time.

Tab completion removes that path entirely: a name you complete is a name you
cannot typo.

Importing readline also upgrades input() for free — arrow-key line editing
and in-session history (up-arrow to recall a previous input), neither of
which the plain input() loop had.

THE TWO HALVES OF THIS FILE, AND WHY THEY ARE SEPARATE
------------------------------------------------------
`completion_candidates()` is a pure function: given the router and the text
typed so far, it returns what could come next. No readline, no I/O, no
terminal. It is directly testable and directly reusable.

`setup_completion()` is the readline plumbing, and is the throwaway half.
When the Textual TUI arrives it will have its own input widget with its own
completion mechanism, and none of the readline code below will apply to it.
The candidate logic will, unchanged — which is the whole reason the two are
not written as one function.

PLATFORM NOTES
--------------
readline is Unix-only in CPython. Windows has no stdlib equivalent (it needs
third-party pyreadline3), and the README lists Windows as supported, so the
import is guarded and completion simply stays off there rather than crashing
the app on startup.

On macOS, Python links against libedit rather than GNU readline, and the two
take different binding syntax. The widely-copied `parse_and_bind("tab:
complete")` silently does nothing under libedit — no error, no completion,
which is a genuinely confusing way to fail. Both bindings are applied below.
"""

from typing import List, Optional

try:
    import readline
except ImportError:
    # Windows, or any build without the module. Completion is a convenience,
    # never a requirement — the session must run exactly as before without it.
    readline = None


# Commands worth suggesting. Deliberately excludes "/rfc", which
# entry_classifier.py recognises but router.py still reports as not wired —
# offering it would advertise a dead end.
SLASH_COMMANDS = ("/ask", "/new", "/switch", "/resume", "/quit", "/exit")

# Commands that take a project name as their argument.
_PROJECT_ARG_COMMANDS = ("/switch", "/resume")

# Offered while a document is waiting at an approval gate. Short, common
# phrasings only — this is a nudge toward what is possible at this moment,
# not an attempt to write the user's feedback for them.
_APPROVAL_SUGGESTIONS = ("approve", "looks good", "export as pdf")

# Offered once a project is finished, where exporting is the main thing left.
_DONE_SUGGESTIONS = ("export everything as pdf", "export the brd as pdf", "export the prd as pdf")


def _project_names(router) -> List[str]:
    """
    Projects that will genuinely resume.

    Uses list_resumable_projects() (backed by .session.json) rather than
    every folder under projects/. A folder without a session file resolves to
    RESUME_FROM_DISK_NO_SESSION, which then fails to load and reports "Could
    not load session state" — completing to a name that cannot actually be
    opened would be worse than offering nothing.

    Read fresh on each Tab rather than cached at startup, so a project created
    earlier in this same session is immediately completable. The cost is a
    directory scan per keypress, which is a few stat calls.
    """
    try:
        return router.list_resumable_projects()
    except Exception:
        # Completion must never be the reason the prompt breaks.
        return []


def _stage_for_active_project(router) -> Optional[str]:
    """Current stage of the open project, or None if nothing is open."""
    if router.active_project is None:
        return None
    try:
        session = router.orchestrator.context_manager.get_session(router.active_project)
    except Exception:
        return None
    return session.get("stage") if session else None


def completion_candidates(router, line: str, word: str) -> List[str]:
    """
    Everything that could sensibly follow, given where the session is.

    Args:
        router: the live Router — read for active project and stage.
        line: the full input line typed so far.
        word: the whitespace-delimited token currently being completed.

    Returns:
        Candidates already filtered to those starting with `word`, sorted.

    Pure and side-effect free, so it can be unit tested without a terminal
    and reused by any future front end.
    """
    stripped = line.lstrip()
    lowered = stripped.lower()

    # "/switch upse<TAB>" — the argument to these is always a project name,
    # so nothing else belongs in the list.
    for command in _PROJECT_ARG_COMMANDS:
        if lowered.startswith(command + " "):
            return _filter(_project_names(router), word)

    # A leading slash means a command is being typed, not free text.
    if word.startswith("/"):
        return _filter(list(SLASH_COMMANDS), word)

    candidates: List[str] = list(SLASH_COMMANDS)
    stage = _stage_for_active_project(router)

    if stage is None:
        # No project open: the likeliest input by far is the name of one to
        # resume, which is the case this whole module exists for.
        candidates += _project_names(router)
    elif stage.endswith("_approval"):
        candidates += list(_APPROVAL_SUGGESTIONS)
    elif stage == "done":
        candidates += list(_DONE_SUGGESTIONS)

    return _filter(candidates, word)


def _filter(candidates: List[str], word: str) -> List[str]:
    """Prefix match, case-insensitive, deduplicated and ordered."""
    if not word:
        return sorted(set(candidates))
    lowered = word.lower()
    return sorted({c for c in candidates if c.lower().startswith(lowered)})


class _Completer:
    """
    Adapter between readline's callback protocol and completion_candidates().

    readline asks for one match at a time: call with state=0 for the first,
    1 for the second, and so on until the callback returns None. The full list
    is therefore computed once at state 0 and served from there, rather than
    recomputed per index.
    """

    def __init__(self, router):
        self.router = router
        self._matches: List[str] = []

    def __call__(self, word: str, state: int) -> Optional[str]:
        try:
            if state == 0:
                line = readline.get_line_buffer() if readline else word
                self._matches = completion_candidates(self.router, line, word)
            return self._matches[state]
        except IndexError:
            return None
        except Exception:
            # An exception raised inside a readline callback is swallowed by
            # the C layer and shows up as completion mysteriously doing
            # nothing. Returning None keeps that failure quiet but harmless
            # rather than leaving the prompt in a broken state.
            return None


def setup_completion(router) -> bool:
    """
    Turn on tab completion for input(). Safe to call unconditionally.

    Returns True if completion was activated, False if it could not be — no
    readline module, or a terminal that rejected the binding. Callers may use
    the result to mention completion in a startup hint, but nothing depends
    on it.
    """
    if readline is None:
        return False

    try:
        # Default delimiters include "/" and "-", which would split "/switch"
        # and "upsell-assist" into fragments and make both uncompletable.
        # Whitespace-only delimiters keep each token whole.
        readline.set_completer_delims(" \t\n")
        readline.set_completer(_Completer(router))

        # libedit (macOS) and GNU readline take different syntax and ignore
        # each other's. Applying both is what makes this work on either.
        readline.parse_and_bind("bind ^I rl_complete")
        readline.parse_and_bind("tab: complete")
        return True
    except Exception:
        return False
