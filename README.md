# mono-copilot

Monorepo for a Python FastAPI app powered by OpenAI Agents, managed with uv workspaces.

Takes a business idea through a Business Requirements Document (BRD), then a
Product Requirements Document (PRD), then five role-specific RFCs (UI/UX,
Software Architect, Security, QA, DevOps) -- pausing for your review and
feedback at every stage. Every generated document can be exported to a real,
formatted PDF with rendered Mermaid diagrams and sourced citations.

## Requirements

- macOS, Linux, or Windows
- Python 3.13+
- uv 0.11+
- Node.js (only needed for PDF export -- see step 4 below)

Install uv if needed:

```bash
brew install uv
```

## Project Layout

```text
mono-copilot/
	apps/
		copilot/          # FastAPI app + agent integration
	packages/
		runtime/          # Shared workspace package
```

## 1. Clone And Enter The Repo

```bash
git clone <your-repo-url>
cd mono-copilot
```

## 2. Create Environment Variables

Create a local .env file at the repository root:

```bash
cat > .env << 'EOF'
OPENAI_API_KEY=your_openai_api_key_here
EOF
```

Important:

- Do not commit .env files.
- If you use OpenAI-compatible providers, set the provider-specific variables required by your integration.

## 3. Install Workspace Dependencies

From repo root:

```bash
uv sync
```

This installs dependencies for all workspace members defined in pyproject.toml.

## 4. Set Up PDF Export (one-time, do this before you try exporting anything)

Every generated document can be exported to PDF. That pipeline has two real,
native dependencies beyond what `uv sync` installs, and both fail silently
back to a degraded (but not broken) experience if skipped -- worth doing
now rather than debugging a confusing error later.

### WeasyPrint (renders the PDF itself)

WeasyPrint needs real system libraries (Pango, GObject), not just the Python
package. If these aren't set up, chat and every other part of the workflow
still work completely normally -- only an actual export attempt fails, with
a clear message telling you this section is what to read.

**macOS:**

```bash
brew install pango
echo 'export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_FALLBACK_LIBRARY_PATH"' >> ~/.zshrc
source ~/.zshrc
```

Open a **new** terminal window afterward -- `source`ing in the same window
you ran the `echo` in is not enough on its own if you already have a shell
running, and .zshrc only gets re-read by shells that start after the change.

**Linux (Debian/Ubuntu):**

```bash
sudo apt-get install -y libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info
```

(Not verified against this exact repo the way the macOS steps above were --
these are WeasyPrint's own documented Linux dependencies. If something's
missing, https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation
is the authoritative source.)

**Verify it worked, on any OS:**

```bash
uv run --package copilot python3 -c "import weasyprint; print('weasyprint OK')"
```

### Mermaid diagrams as real images (optional, recommended)

Diagrams in generated documents render as actual images in the exported PDF
via a local, offline call to mermaid-cli -- nothing about your document ever
gets sent to a hosted rendering API. If mermaid-cli or its browser aren't
available, PDF export still works; that one diagram is left as visible
source-code text instead of a rendered image, which is a real degrade but
never a failure.

```bash
# mermaid-cli itself doesn't need a separate install step -- npx/bunx fetch
# it on first use. It does need a real headless browser to actually draw
# anything, which is the part worth doing explicitly:
npx puppeteer browsers install chrome-headless-shell
```

If you don't have Node.js at all and don't want to install it, skip this --
everything else works, diagrams just show as text in the PDF.

## 5. Run The Interactive Terminal UI (the main way to use this)

```bash
uv run --package copilot python3 -m copilot.cli chat
```

Opens a full-screen terminal app: type a business idea to start a new
project, or an existing project's name to resume it. Say `export as pdf` at
any point once a document exists to get a real file under
`projects/{name}/exports/`.

To resume a specific project directly without being asked for its name:

```bash
uv run --package copilot python3 -m copilot.cli chat --project my-project-name
```

**Use `python3 -m copilot.cli chat`, not `mono chat`, even though both exist
and `mono` is shorter.** There's also a `mono` console script that does the
same thing (`uv run --package copilot mono chat`) -- it works for everyday
use, but on macOS specifically, exporting a PDF from inside it can fail with
a confusing "cannot load library" error even after the WeasyPrint setup
above, because the `mono` script is a small shell wrapper, and macOS strips
WeasyPrint's required environment variable from processes launched that way
before Python ever sees it. Running the module directly, as shown above,
never hits this. Same app either way, this is purely about which one
reliably supports PDF export on macOS.

Sessions are saved to `projects/{name}/.session.json`, so they survive
quitting the app or restarting your machine.

## 6. Run The Plain-Terminal Interactive CLI

The same underlying workflow as step 5, as a simple line-by-line terminal
prompt instead of a full-screen app -- useful if you'd rather not use a TUI,
or are running somewhere a full-screen terminal app doesn't work well (some
CI logs, some remote sessions).

From repo root:

```bash
uv run --package copilot python3 apps/copilot/test/test_interactive_session.py
```

Type a business problem to start a new project, or the name of an existing
one to resume it. Sessions are saved to projects/{name}/.session.json, so
they survive quitting the terminal.

Commands:

- `/ask <question>` ask a question without affecting the workflow
- `/new` start a fresh idea
- `/switch <name>` change project
- `/quit` exit

Tab completes project names and commands.

To see the whole pipeline without an API key or any spend, this runs the same
flow with the model calls stubbed:

```bash
uv run --package copilot python3 apps/copilot/test/test_offline_walkthrough.py
```

## 7. Run The Copilot API

The same workflow over HTTP, sharing the orchestrator with the CLI.

From repo root:

```bash
uv run --package copilot start
```

This runs in development mode with auto-reload. Set APP_ENV=production for
standard mode.

Server URL:

- http://127.0.0.1:8000

API docs:

- http://127.0.0.1:8000/docs

## 8. Verify Endpoints

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Start a BRD:

```bash
curl -X POST http://127.0.0.1:8000/agent/start \
	-H "Content-Type: application/json" \
	-d '{"project_name":"demo","problem_statement":"Describe the business problem here.","segment":"postpaid_consumer"}'
```

Read a generated document:

```bash
curl http://127.0.0.1:8000/projects/demo/brd
```

Full endpoint list is at http://127.0.0.1:8000/docs

## Troubleshooting

Port already in use (127.0.0.1:8000):

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <PID>
```

Missing package/import issues:

```bash
uv sync
```

Check Python version used by uv:

```bash
uv run python --version
```

"Cannot load library 'libgobject-2.0-0'" or similar when exporting a PDF:

- You're missing the WeasyPrint system libraries, or the environment
  variable that points to them isn't reaching the process. Do step 4 above,
  in a genuinely new terminal window, and use `python3 -m copilot.cli chat`
  rather than `mono chat` -- see the note in step 5 for why that specific
  distinction matters on macOS.
- Everything except the export itself still works normally while this is
  unresolved -- this only blocks the one "export as pdf" action.

A diagram shows up as a code block instead of an image in an exported PDF:

- mermaid-cli couldn't find a working headless browser. Run
  `npx puppeteer browsers install chrome-headless-shell` (step 4) and
  export again. The PDF itself is still valid either way -- this only
  affects how one diagram is displayed.
