"""
Shared setup for the offline tests.

Every other test file in this directory (test_full_run, test_guided_start,
test_rfc_run, test_interactive_session) is a live demo: it needs a real
OPENAI_API_KEY, spends money, and takes a minute per stage. Useful for
checking answer quality, useless as a regression net, because nobody runs
something that costs a few dollars before pushing a small change.

The tests that import this module are the opposite. They stub the model call
and assert on behaviour, so they run in about a second, need no key, and can
be run by anyone on the team on day one.

Not named test_*.py on purpose, so it is never mistaken for a test itself.
"""

import os
import sys
import types
from pathlib import Path


def bootstrap() -> None:
    """
    Make the copilot package importable and remove the two things that
    otherwise stop these tests running on a clean machine.

    Call this before importing anything from copilot.
    """
    src = Path(__file__).parent.parent / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    # Router builds a ChatSkill, which refuses to construct without a key.
    # The tests never reach a real API call, so a placeholder is enough.
    os.environ.setdefault("OPENAI_API_KEY", "sk-offline-tests-not-real")

    _stub_weasyprint_if_unavailable()


def _stub_weasyprint_if_unavailable() -> None:
    """
    router.py imports export_document, which imports weasyprint at module
    level, which loads native pango and gobject libraries. On a machine
    without those installed (brew install pango), importing the router fails
    outright and every test here dies on an unrelated system dependency.

    The real module is used whenever it loads. This only fills the gap so a
    teammate who has not installed pango can still run the suite.
    """
    try:
        import weasyprint  # noqa: F401
    except Exception:
        stub = types.ModuleType("weasyprint")
        stub.HTML = stub.CSS = object
        sys.modules["weasyprint"] = stub


def fake_completion(text: str):
    """
    Minimal stand-in for an OpenAI chat completion response.

    Only shaped deeply enough for the attribute path the skills actually
    read, response.choices[0].message.content, which is what ba_skill's
    _extract_markdown_from_response and ChatSkill.answer both use.
    """
    message = type("Message", (), {"content": text})()
    choice = type("Choice", (), {"message": message})()
    return type("Response", (), {"choices": [choice]})()


class Checks:
    """
    Tiny assertion recorder.

    Deliberately not pytest: pytest is not a dependency of this workspace,
    and adding one so a handful of files can run would be a heavier change
    than the tests are worth. Each file stays directly runnable with
    plain python, matching how every other script in this directory works.
    """

    def __init__(self):
        self.passed = []
        self.failed = []

    def __call__(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.passed.append(name)
            print(f"  PASS  {name}")
        else:
            self.failed.append(name)
            print(f"  FAIL  {name}" + (f"  <- {detail}" if detail else ""))
        return bool(condition)

    def section(self, title: str) -> None:
        print(f"\n{title}")

    def report(self) -> int:
        """Print the tally and return an exit code for sys.exit()."""
        print("\n" + "=" * 60)
        print(f"{len(self.passed)} passed, {len(self.failed)} failed")
        if self.failed:
            print("failed: " + ", ".join(self.failed))
        return 1 if self.failed else 0
