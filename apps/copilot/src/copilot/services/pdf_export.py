"""
PDF export for BRD/PRD/RFC markdown documents — the "view the files, export
as PDF, respond with the link" test-run feature.

Pipeline: markdown -> mermaid blocks rendered to SVG locally via mermaid-cli
(mmdc) -> markdown-to-HTML -> PDF via weasyprint.

Deliberately NOT a hosted markdown/mermaid rendering API (e.g. mermaid.ink).
This content can include confidential MNO business and technical detail —
threat models, architecture, capacity numbers — and shouldn't leave the
machine just to get a diagram rendered.

New dependencies this module needs (added to apps/copilot/pyproject.toml):
- weasyprint (pure-Python HTML/CSS -> PDF, no headless-browser dependency)
- markdown (CommonMark-ish markdown -> HTML converter)
- Node + @mermaid-js/mermaid-cli (`mmdc`) reachable on PATH for diagram
  rendering. apps/copilot/Dockerfile.sandbox already installs bun, so
  `bunx @mermaid-js/mermaid-cli` works there without a new image layer;
  locally, `npx @mermaid-js/mermaid-cli` (fetches on first use) or a global
  `npm install -g @mermaid-js/mermaid-cli` both work the same way.

IMPORTANT — verified during development, worth checking on your machine:
mmdc itself needs a headless Chrome/Chromium reachable via Puppeteer to
actually rasterize a diagram (it shells out to a real browser under the
hood). If Puppeteer can't find one, mmdc exits non-zero with "Could not
find Chrome" — this module catches that and falls back gracefully (see
render_mermaid_blocks below), so the PDF still gets produced, just with
that diagram left as a visible code block instead of a rendered image. This
was actually hit and confirmed during testing in a network-restricted
sandbox. On your Mac this should work if you have Chrome installed, or run
`npx puppeteer browsers install chrome-headless-shell` once to fetch a
headless copy — worth doing that check before assuming diagrams are
rendering rather than silently falling back.

Failure mode, by design: if mmdc isn't available or a specific diagram fails
to render, that one mermaid block is left as its original fenced code block
in the output — visible as text, not silently dropped — rather than failing
the whole export. A PDF with one diagram shown as source code beats no PDF.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List
from datetime import datetime

import markdown as markdown_lib
from weasyprint import HTML, CSS

from .file_manager import sanitize_project_name


MERMAID_BLOCK_RE = re.compile(r"```mermaid\n(.*?)\n```", re.DOTALL)


def _find_mmdc_command() -> Optional[List[str]]:
    """Argv prefix to invoke mermaid-cli, or None if nothing on this machine
    can run it. Checked in priority order: a real `mmdc` binary on PATH
    first (fastest, nothing to fetch), then npx/bunx as fallbacks that pull
    it on demand."""
    if shutil.which("mmdc"):
        return ["mmdc"]
    if shutil.which("npx"):
        return ["npx", "--yes", "@mermaid-js/mermaid-cli"]
    if shutil.which("bunx"):
        return ["bunx", "@mermaid-js/mermaid-cli"]
    return None


def render_mermaid_blocks(markdown_text: str, work_dir: Path) -> str:
    """
    Replace every ```mermaid fenced block with an inline <img> tag pointing
    at a locally rendered PNG. A block that fails to render (bad syntax,
    mmdc timeout, mmdc unavailable, or Puppeteer unable to find a browser —
    see module docstring) is left as its original fenced code block rather
    than silently disappearing from the document.

    Rendered to PNG, not SVG. Mermaid.js commonly renders node-label text via
    <foreignObject>-wrapped HTML (needed for text wrapping inside shapes),
    and WeasyPrint's SVG engine does not support foreignObject — it draws
    the shape outlines fine but silently drops that content, producing
    diagrams with empty boxes and no visible labels. This was confirmed
    happening (not just theorized) on a real generated PDF. PNG sidesteps
    the problem entirely: mmdc's PNG output is a real screenshot taken by
    the actual headless browser during generation, so there's no second,
    less-capable renderer re-interpreting the SVG afterward — whatever
    Mermaid actually drew is exactly what ends up in the pixels. Traded off
    against SVG: raster rather than infinitely-scalable vector, so a higher
    render resolution is requested below to stay crisp at normal PDF zoom.
    """
    mmdc_cmd = _find_mmdc_command()
    if mmdc_cmd is None:
        return markdown_text

    counter = {"n": 0}

    def _replace(match: "re.Match") -> str:
        diagram_source = match.group(1)
        counter["n"] += 1
        input_path = work_dir / f"diagram_{counter['n']}.mmd"
        output_path = work_dir / f"diagram_{counter['n']}.png"
        input_path.write_text(diagram_source)

        try:
            subprocess.run(
                mmdc_cmd + [
                    "-i", str(input_path),
                    "-o", str(output_path),
                    "-b", "white",
                    "-w", "1400",
                    "-H", "1000",
                    "--scale", "2",
                ],
                capture_output=True,
                timeout=30,
                check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return match.group(0)

        if not output_path.exists():
            return match.group(0)

        return f'<img src="file://{output_path.resolve()}" class="mermaid-diagram" alt="diagram" />'

    return MERMAID_BLOCK_RE.sub(_replace, markdown_text)


_PDF_CSS = """
@page { size: A4; margin: 2cm; @bottom-center { content: counter(page) " / " counter(pages); font-size: 9px; color: #888; } }
body { font-family: Georgia, 'Times New Roman', serif; line-height: 1.5; color: #1a1a1a; font-size: 11px; }
h1, h2, h3 { font-family: Helvetica, Arial, sans-serif; color: #0d1b2a; }
h1 { border-bottom: 2px solid #0d1b2a; padding-bottom: 6px; font-size: 20px; }
h2 { border-bottom: 1px solid #ccc; padding-bottom: 4px; margin-top: 24px; font-size: 15px; }
h3 { font-size: 12px; margin-top: 16px; }
code, pre { font-family: 'Courier New', monospace; background: #f4f4f4; }
pre { padding: 8px; border-radius: 4px; overflow-x: auto; font-size: 9px; white-space: pre-wrap; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 10px; }
th, td { border: 1px solid #ccc; padding: 5px 8px; text-align: left; }
th { background: #f0f0f0; }
.mermaid-diagram { max-width: 100%; margin: 14px 0; display: block; }
a { color: #0d1b2a; }
"""


def markdown_to_pdf(markdown_text: str, output_path: Path, title: Optional[str] = None) -> Path:
    """
    Full pipeline: render mermaid diagrams locally -> convert markdown to
    HTML -> render HTML to PDF with a print-oriented stylesheet. Writes to
    output_path (creating parent directories as needed) and returns it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        rendered = render_mermaid_blocks(markdown_text, work_dir)

        html_body = markdown_lib.markdown(
            rendered, extensions=["extra", "tables", "fenced_code", "sane_lists"]
        )

        html_doc = (
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
            f"<title>{title or 'Document'}</title></head>"
            f"<body>{html_body}</body></html>"
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        HTML(string=html_doc, base_url=str(work_dir)).write_pdf(
            str(output_path), stylesheets=[CSS(string=_PDF_CSS)]
        )

    return output_path


def export_document(
    project_name: str,
    doc_name: str,
    markdown_text: str,
    projects_dir: str = "projects",
) -> str:
    """
    Export one document (BRD/PRD/RFC) to
    projects/{project_name}/exports/{doc_name}-{timestamp}.pdf and return
    the path as a string — this is the "link" the CLI/chat responds with,
    per the storm.md interaction sketch (export as PDF -> here's your document).

    project_name is sanitized before use (same sanitize_project_name every
    other save/load path already goes through) — this used to be skipped
    here specifically, which meant a project name like "software org" (a
    literal space, exactly as typed) produced a second, wrong sibling folder
    for exports only, while every other file for that same project lived
    under the correctly-sanitized "software-org". Confirmed this actually
    happened on a real run before this fix.
    """
    safe_name = sanitize_project_name(project_name)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = Path(projects_dir) / safe_name / "exports" / f"{doc_name}-{timestamp}.pdf"
    markdown_to_pdf(markdown_text, output_path, title=f"{project_name} — {doc_name}")
    return str(output_path)
