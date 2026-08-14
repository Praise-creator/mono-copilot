#!/usr/bin/env python3
"""
What happens when a Mermaid diagram can't be rendered into a PDF.

Run from the repo root:

    uv run --package copilot python3 apps/copilot/test/test_pdf_fallback.py

No API key needed, no network, no mmdc needed. Everything is stubbed.

Covers #29. Falling back to plain text when mmdc fails is the right
behaviour, but it used to happen silently, and every cause looked identical
in the finished PDF: a missing browser, a corrupted npx cache, a diagram
mmdc could not parse. The README blamed a missing toolchain, which sent you
looking in the wrong place when the toolchain was fine.

The awkward part is picking which line of mmdc's output to show. npm prints
its own notices after the real error, so the last line is usually
"npm notice" and says nothing useful. That is what most of this file checks.
"""

import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from _offline import bootstrap, Checks

bootstrap()

from copilot.services import pdf_export
from copilot.services.pdf_export import _explain_mmdc_failure, render_mermaid_blocks

check = Checks()

DIAGRAM = "```mermaid\ngraph TD\n  A[Customer] --> B[AI Engine]\n```"


class CapturedLogs:
    """Collects warnings from pdf_export for the duration of a block."""

    def __enter__(self):
        self.records = []
        self.handler = logging.Handler()
        self.handler.emit = lambda record: self.records.append(record.getMessage())
        self.logger = logging.getLogger("copilot.services.pdf_export")
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.WARNING)
        return self

    def __exit__(self, *exc):
        self.logger.removeHandler(self.handler)

    @property
    def text(self):
        return "\n".join(self.records)


def failure(stderr: bytes) -> subprocess.CalledProcessError:
    exc = subprocess.CalledProcessError(1, "mmdc")
    exc.stderr = stderr
    return exc


check.section("[1] the reason picked is the one that names the problem")
# The real case: npm prints notices after the error, so the last line is
# useless. This is what made the first version of the fix report "npm notice".
exc = failure(
    b"npm warn exec The following package was not found\n"
    b"Error: Cannot find package '@puppeteer/browsers' imported from ChromeLauncher.js\n"
    b"npm notice\n"
    b"npm notice New major version of npm available!"
)
check("picks the Error line, not the trailing npm notice",
      "Cannot find package" in _explain_mmdc_failure(exc), _explain_mmdc_failure(exc))

check("does not return an npm notice",
      not _explain_mmdc_failure(exc).lower().startswith("npm notice"))

exc = failure(b"Could not find Chrome (ver. 130). Try running npx puppeteer browsers install")
check("recognises a missing browser",
      "Could not find Chrome" in _explain_mmdc_failure(exc), _explain_mmdc_failure(exc))

exc = failure(b"Parse error on line 3:\n  A --> \n  ^\nExpecting 'NODE_STRING'")
check("recognises a bad diagram", "Parse error" in _explain_mmdc_failure(exc),
      _explain_mmdc_failure(exc))

check.section("[2] it copes with output that has no obvious error line")
check("empty stderr falls back to the exception type",
      _explain_mmdc_failure(failure(b"")) == "CalledProcessError",
      _explain_mmdc_failure(failure(b"")))
check("no stderr attribute at all is handled",
      _explain_mmdc_failure(RuntimeError("boom")) == "RuntimeError")
check("only npm notices falls back to the last real line",
      _explain_mmdc_failure(failure(b"something happened\nnpm notice\nnpm notice x"))
      == "something happened")
check("bytes are decoded",
      "Cannot find" in _explain_mmdc_failure(failure(b"Error: Cannot find thing")))

check.section("[3] a failing mmdc leaves the diagram as text, and says why")
with tempfile.TemporaryDirectory() as tmp:
    with patch.object(pdf_export, "_find_mmdc_command", return_value=["mmdc"]), \
         patch.object(pdf_export.subprocess, "run",
                      side_effect=failure(b"Error: Cannot find package '@puppeteer/browsers'")), \
         CapturedLogs() as logs:
        out = render_mermaid_blocks(DIAGRAM, Path(tmp))
check("diagram left as text", out == DIAGRAM)
check("a warning was emitted", "left as text" in logs.text, logs.text)
check("the warning names the real cause", "Cannot find package" in logs.text, logs.text)

check.section("[4] no mmdc at all is reported too")
with tempfile.TemporaryDirectory() as tmp:
    with patch.object(pdf_export, "_find_mmdc_command", return_value=None), \
         CapturedLogs() as logs:
        out = render_mermaid_blocks(DIAGRAM, Path(tmp))
check("diagram left as text", out == DIAGRAM)
check("says the toolchain is missing", "no mmdc" in logs.text.lower(), logs.text)

check.section("[5] mmdc claiming success but writing nothing is reported")
with tempfile.TemporaryDirectory() as tmp:
    with patch.object(pdf_export, "_find_mmdc_command", return_value=["mmdc"]), \
         patch.object(pdf_export.subprocess, "run", return_value=None), \
         CapturedLogs() as logs:
        out = render_mermaid_blocks(DIAGRAM, Path(tmp))
check("diagram left as text", out == DIAGRAM)
check("says no image was written", "no image" in logs.text.lower(), logs.text)

check.section("[6] a working mmdc still produces an image and stays quiet")
with tempfile.TemporaryDirectory() as tmp:
    work = Path(tmp)

    def pretend_render(cmd, **kwargs):
        # mmdc writes its output file; -o is the argument after it.
        out_path = Path(cmd[cmd.index("-o") + 1])
        out_path.write_bytes(b"\x89PNG\r\n\x1a\n fake image")
        return None

    with patch.object(pdf_export, "_find_mmdc_command", return_value=["mmdc"]), \
         patch.object(pdf_export.subprocess, "run", side_effect=pretend_render), \
         CapturedLogs() as logs:
        out = render_mermaid_blocks(DIAGRAM, work)
check("diagram became an image tag", "<img" in out and "mermaid-diagram" in out, out[:80])
check("no mermaid source left behind", "```mermaid" not in out)
check("nothing warned on success", logs.text == "", logs.text)

check.section("[7] text with no diagrams is untouched")
plain = "# Heading\n\nJust prose, no diagrams here.\n"
with tempfile.TemporaryDirectory() as tmp:
    with patch.object(pdf_export, "_find_mmdc_command", return_value=["mmdc"]), \
         CapturedLogs() as logs:
        out = render_mermaid_blocks(plain, Path(tmp))
check("returned unchanged", out == plain)
check("nothing warned", logs.text == "", logs.text)

sys.exit(check.report())
