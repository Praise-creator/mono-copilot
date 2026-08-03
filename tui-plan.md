# Plan: Convert mono-copilot into a CLI chat application

## Context (discovery findings)
- Workspace is Live Share: use `vsls:/` paths for edits. Local mirror at /Users/mosesgameli/MTN/_/mono-copilot is stale (has extra `mono` script; vsls pyproject only has `start`).
- Existing architecture: FastAPI app (main.py) → Orchestrator (13-state BRD→PRD workflow) → BAAgent/PEAgent → ba_skill/pe_skill (AsyncOpenAI gpt-4-turbo) → ResearchService (keyword-based source whitelist verification) + FileManager (projects/{name}/ba-output.md, pe-output.md) + ContextManager (in-memory dict sessions).
- test/test_full_run.py is a proto-CLI: input() loop, approval words set, feedback → handle_approval(needs_changes) → handle_clarification_response({"feedback": ...}). Use as behavioral template.
- storm.md at repo root is empty (scratchpad).
- User decisions: Textual full-screen TUI; FastAPI coexists; sessions persist to disk; chat handles workflow + ad-hoc research queries.

## Steps

### Phase 1 — CLI entry + persistence (foundation)
1. Add `textual` dependency to apps/copilot/pyproject.toml; add console script `mono = "copilot.cli.__main__:main"` (keep existing `start` FastAPI script). Note: stale local mirror once had a `mono` script pointing to copilot.mono:main — vsls pyproject has no such module, so the name is free.
2. Create `copilot/cli/__main__.py`: argparse subcommands:
   - `mono chat [--project NAME]` → launch Textual TUI
   - `mono start --project NAME --problem TEXT [--segment S]` → headless BRD generation
   - `mono approve --project NAME --stage ba|pe` / `mono feedback --project NAME --stage ba|pe --message TEXT`
   - `mono show brd|prd|sources --project NAME` → print to stdout
   - `mono projects` → list projects dirs + stage
3. ContextManager persistence: save session JSON to projects/{name}/session.json on every update; load on demand (get_session falls back to disk); serialize datetimes to isoformat. Orchestrator unchanged (uses same API).

### Phase 2 — Textual chat TUI
4. `cli/app.py`: ChatApp(App) — Header, VerticalScroll message log, Input, Footer/status bar (project | stage | run_count). Orchestrator calls in run_worker to keep UI responsive; loading indicator during OpenAI calls (30-60s).
5. Workflow wiring: no project → prompt for name+segment+problem; then process_input → render BRD summary + quality gates as chat message; at ba_approval/pe_approval, plain text = feedback (needs_changes + clarification flow), approval words / `/approve` = advance. Mirrors test_full_run.py logic incl. APPROVAL_WORDS.
6. Slash commands (`cli/commands.py` parser): /show brd|prd|sources, /files, /projects, /switch NAME, /new, /ask QUERY, /help, /quit. File display via Textual Markdown widget in a modal screen (widgets.py).

### Phase 3 — Ad-hoc query routing
7. `skills/chat_skill.py`: answer free-form questions with AsyncOpenAI + ResearchService.search_and_verify for source-grounded answers; returns markdown + sources.
8. `cli/router.py`: route input — slash command → commands; at approval stage plain text → workflow feedback; `/ask` or no-active-workflow text → chat_skill.

### Phase 4 — Verification
9. Unit tests: ContextManager disk round-trip; command parser; router decisions. Textual Pilot smoke test for app boot. Manual: `uv run --package copilot mono chat` with OPENAI_API_KEY.

## Files
- vsls:/apps/copilot/pyproject.toml — dep + script
- vsls:/apps/copilot/src/copilot/cli/{__init__,__main__,app,commands,router,widgets}.py — new
- vsls:/apps/copilot/src/copilot/services/context_manager.py — persistence
- vsls:/apps/copilot/src/copilot/skills/chat_skill.py — new
- vsls:/apps/copilot/test/ — new unit tests

## Decisions
- Textual (not rich REPL); argparse (no typer) to limit deps
- FastAPI kept as-is; both interfaces share Orchestrator
- projects/ dir stays CWD-relative but overridable via --projects-dir / COPILOT_PROJECTS_DIR
- Out of scope: ADR stage (enum mentions adr_pending but not implemented), real web search (Phase 2 per code comments), auth

## Open considerations
- ba_skill/pe_skill also write flat projects/brd.md + prd.md (legacy duplicates of FileManager per-project saves) — optional cleanup, flagged in plan
- Approval-stage ambiguity: plain text treated as feedback (consistent with test_full_run); /approve is explicit escape hatch
