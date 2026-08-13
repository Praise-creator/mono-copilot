# mono-copilot

Monorepo for a Python FastAPI app powered by OpenAI Agents, managed with uv workspaces.

## Requirements

- macOS, Linux, or Windows
- Python 3.13+
- uv 0.11+

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

## 4. Run The Interactive CLI

The main way to use Mono-Copilot. Takes a business idea through BRD, then PRD,
then five role RFCs, pausing for your review at each stage.

From repo root:

```bash
uv run --package copilot python3 apps/copilot/test/test_interactive_session.py
```

Type a business problem to start a new project, or the name of an existing one
to resume it. Sessions are saved to projects/{name}/.session.json, so they
survive quitting the terminal.

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

## 5. Run The Copilot API

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

## 6. Verify Endpoints

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
