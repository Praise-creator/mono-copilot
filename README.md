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

## 4. Run The Copilot API

From repo root:

- Development mode (auto-reload):

```bash
uv run --package copilot copilot-dev
```

- Standard mode:

```bash
uv run --package copilot copilot-server
```

Server URL:

- http://127.0.0.1:8000

API docs:

- http://127.0.0.1:8000/docs

## 5. Verify Endpoints

Health/root endpoint:

```bash
curl http://127.0.0.1:8000/
```

Agent endpoint:

```bash
curl -X POST http://127.0.0.1:8000/agent \
	-H "Content-Type: application/json" \
	-d '{"user_input":"When did the Roman Empire fall?"}'
```

Expected response shape:

```json
{
	"response": "..."
}
```

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
