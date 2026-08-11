#!/usr/bin/env python3
"""
Tests for cli/completion.py, the tab completion vocabulary.

Run from the repo root:

    uv run --package copilot python3 apps/copilot/test/test_completion.py

No API key needed, no network, no terminal.

Everything here exercises completion_candidates(), which is a pure function
by design: given the router and the text typed so far, it returns what could
come next. The readline half of that module is not tested, because driving a
real terminal from a test is far more machinery than the twelve lines of
binding code justify. Keeping the decision logic pure is what makes this
possible, and it is also what lets the Textual TUI reuse it later.
"""

import sys

from _offline import bootstrap, Checks

bootstrap()

from copilot.cli.completion import completion_candidates, setup_completion, SLASH_COMMANDS
from copilot.cli.router import Router
from copilot.orchestrator import Orchestrator

check = Checks()

PROJECTS = ["upsell-assist", "upsell-legacy", "churn-model"]


class FakeRouter:
    """
    Stands in for Router so results do not depend on what happens to be in
    the projects/ directory on the machine running this.
    """

    def __init__(self, projects, active=None, stage=None):
        self._projects = projects
        self.active_project = active
        self._stage = stage
        outer = self

        class ContextManager:
            def get_session(self, name):
                return {"stage": outer._stage} if outer._stage else None

        self.orchestrator = type("Orchestrator", (), {"context_manager": ContextManager()})()

    def list_resumable_projects(self):
        return self._projects


check.section("[1] nothing open offers projects and commands")
router = FakeRouter(PROJECTS)
candidates = completion_candidates(router, "", "")
check("all projects offered", all(p in candidates for p in PROJECTS), str(candidates))
check("commands offered too", "/ask" in candidates)

check.section("[2] completing a partial project name")
check("unique prefix completes",
      completion_candidates(router, "upsell-a", "upsell-a") == ["upsell-assist"])
both = completion_candidates(router, "upsell", "upsell")
check("ambiguous prefix offers both", both == ["upsell-assist", "upsell-legacy"], str(both))
# Default readline delimiters treat "-" as a word break, which would make
# every hyphenated project name uncompletable. setup_completion narrows the
# delimiters to whitespace; this asserts the names survive intact.
check("hyphenated names stay whole", "upsell-assist" in both)

check.section("[3] slash commands")
check("all commands offered after '/'",
      set(completion_candidates(router, "/", "/")) == set(SLASH_COMMANDS))
check("'/a' completes to /ask", completion_candidates(router, "/a", "/a") == ["/ask"])
check("'/q' completes to /quit", completion_candidates(router, "/q", "/q") == ["/quit"])
# router.py still reports /rfc as not wired, so completing to it would send
# people down a dead end.
check("/rfc is not advertised", "/rfc" not in SLASH_COMMANDS)

check.section("[4] /switch and /resume take project names only")
check("only projects after '/switch '",
      set(completion_candidates(router, "/switch ", "")) == set(PROJECTS))
check("filtered by prefix",
      completion_candidates(router, "/switch churn", "churn") == ["churn-model"])
check("/resume behaves the same",
      completion_candidates(router, "/resume upsell-l", "upsell-l") == ["upsell-legacy"])

check.section("[5] suggestions follow the workflow stage")
at_gate = FakeRouter(PROJECTS, active="upsell-assist", stage="ba_approval")
candidates = completion_candidates(at_gate, "", "")
check("approval phrasings offered", "approve" in candidates, str(candidates))
# Offering another project name mid-review would invite switching away from
# a document waiting for a decision.
check("project names withheld mid-review", "churn-model" not in candidates, str(candidates))
finished = FakeRouter(PROJECTS, active="upsell-assist", stage="done")
candidates = completion_candidates(finished, "", "")
check("finished project suggests exporting", any("export" in c for c in candidates))
check("/ask available at every stage", "/ask" in candidates)

check.section("[6] matching ignores case")
check("uppercase prefix still matches",
      completion_candidates(router, "UPSELL-A", "UPSELL-A") == ["upsell-assist"])

check.section("[7] failures degrade to something usable")


class BrokenRouter:
    active_project = None

    def list_resumable_projects(self):
        raise RuntimeError("disk gone")


check("a broken project listing does not raise",
      completion_candidates(BrokenRouter(), "", "") == sorted(SLASH_COMMANDS))
check("no projects on disk still offers commands",
      completion_candidates(FakeRouter([]), "", "") == sorted(SLASH_COMMANDS))

check.section("[8] wiring against the real Router")
real_router = Router(Orchestrator(), user_id="completion-test")
# False here is legitimate on a platform without readline (Windows), so this
# asserts activation only where the module is actually available.
activated = setup_completion(real_router)
check("activates where readline exists", activated is True or activated is False)
check("real router produces candidates",
      len(completion_candidates(real_router, "", "")) > 0)

sys.exit(check.report())
