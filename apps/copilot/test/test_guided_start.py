#!/usr/bin/env python3
"""
Guided start, full journey: intake -> BA -> approve/rework -> PE -> approve/rework -> done.

Run from the repo root (matches test_full_run.py's convention, since
FileManager resolves "projects/" relative to cwd):

    uv run python3 apps/copilot/test/test_guided_start.py

Layers:
  1. EntryClassifier — free, rule-based, handles the clear-cut cases.
  2. IntakeAgent — only when (1) can't resolve it confidently. Remembers the
     exchange, so a short reply to its own question is understood correctly.
  3. Orchestrator — the real 13-state BA/PE workflow, unchanged.

Approval word matching is shared with test_full_run.py via
copilot.cli.approval_words, so both scripts agree on what counts as approval
rather than risking the two drifting apart.

RFC/ADR stage and standalone BRD->PE entry still aren't wired — same honest
"not runnable yet" messages as before for those paths.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from copilot.orchestrator import Orchestrator
from copilot.cli.entry_classifier import EntryClassifier, EntryPath, list_projects_on_disk
from copilot.cli.intake_agent import IntakeAgent, IntakeDecision
from copilot.cli.loading_messages import LoadingAnimator, BA_MESSAGES, PE_MESSAGES
from copilot.cli.approval_words import is_approval
from copilot.services.file_manager import sanitize_project_name


def orient_user(existing_projects) -> None:
    print("\nMono-Copilot")
    print("Pipeline: idea -> BRD -> PRD -> RFCs -> ADR. You can also jump in "
          "partway if you already have a BRD or PRD.")

    if existing_projects:
        print(f"\nExisting projects: {', '.join(existing_projects)}")
        print("Name one to pick it up, or describe a new idea to start fresh.\n")
    else:
        print("\nNo existing projects yet. Describe the problem or idea you "
              "want to work on.\n")


def print_clarification(result) -> None:
    if result.clarification:
        print(result.clarification.question)
        for i, option in enumerate(result.clarification.options, 1):
            print(f"  {i}. {option}")
    print()


def handle_terminal_paths(path: EntryPath, reason: str) -> bool:
    if path == EntryPath.AD_HOC_QUESTION:
        print("Ad-hoc Q&A isn't wired up yet (that's the chat_skill.py piece "
              "from the CLI plan) — formal pipeline requests only for now.\n")
        return True

    if path == EntryPath.RESUME_FROM_DISK_NO_SESSION:
        print("No live session to resume into — that needs the "
              "disk-persistence work in progress. Can't continue this one "
              "right now.\n")
        return True

    if path == EntryPath.RESUME_LIVE_SESSION:
        print("Live-session resume path recognized, but this script only "
              "demonstrates a fresh start today.\n")
        return True

    if path == EntryPath.STANDALONE_FROM_BRD_PE_NOT_WIRED:
        print("Standalone BRD -> PE entry isn't wired yet — flagged for "
              "after the coordination-pattern question is answered.\n")
        return True

    if path in (EntryPath.STANDALONE_FROM_PRD, EntryPath.STANDALONE_RFC_REQUEST):
        print("RFC stage isn't implemented yet — recognized correctly, just "
              "not runnable yet.\n")
        return True

    return False


async def run_intake_conversation(initial_input: str, existing_projects) -> IntakeDecision:
    agent = IntakeAgent(existing_projects=existing_projects)
    turn = await agent.send(initial_input)

    while not turn.is_final:
        print(f"\n{turn.question}\n")
        follow_up = input("> ").strip()
        turn = await agent.send(follow_up)

    return turn.decision


def _get_feedback(decision_text: str, what: str) -> str:
    """decision_text is whatever the user typed instead of approving. A bare
    'no'/'reject' with no substance gets a follow-up prompt; anything else is
    used directly as the feedback."""
    if decision_text.lower() in ("no", "n", "reject", "disapprove", "decline"):
        return input(f"What should change in the {what}? ").strip()
    return decision_text


async def main() -> None:
    orchestrator = Orchestrator()
    projects_dir = Path("projects")
    existing_projects = list_projects_on_disk(projects_dir)

    orient_user(existing_projects)

    classifier = EntryClassifier(
        context_manager=orchestrator.context_manager,
        existing_projects=existing_projects,
    )

    problem_statement = None

    while True:
        user_input = input("> ").strip()
        if not user_input:
            continue

        result = classifier.classify(user_input)

        if result.path == EntryPath.AMBIGUOUS_NEEDS_CLARIFICATION:
            print(f"\n{result.reason}")
            try:
                decision = await run_intake_conversation(user_input, existing_projects)
            except ValueError as e:
                print(f"\nIntake agent unavailable ({e}) — falling back to "
                      "rule-based options.\n")
                print_clarification(result)
                continue

            print(f"\n{decision.reason}\n")

            if handle_terminal_paths(decision.path, decision.reason):
                continue

            if decision.path == EntryPath.NEW_PROJECT_FROM_IDEA:
                problem_statement = decision.idea_summary or user_input
                if decision.country_or_market and decision.country_or_market.lower() not in problem_statement.lower():
                    problem_statement = f"{problem_statement}\n\nMarket/country: {decision.country_or_market}"
                break

            print("Couldn't resolve a clear next step from that — let's try again.\n")
            continue

        if handle_terminal_paths(result.path, result.reason):
            continue

        if result.path == EntryPath.NEW_PROJECT_FROM_IDEA:
            print(f"\n{result.reason}")
            problem_statement = user_input
            break

    project_name = input("\nProject name (short, no spaces): ").strip()
    sanitized_name = sanitize_project_name(project_name)
    if sanitized_name != project_name:
        print(f"(using '{sanitized_name}' as the project name — no spaces or special characters)")
    project_name = sanitized_name

    segment = input("Segment [postpaid_consumer]: ").strip() or "postpaid_consumer"

    preview = problem_statement[:80] + ("..." if len(problem_statement) > 80 else "")
    print("\nAbout to run: BA agent -> generate BRD")
    print(f"  Project : {project_name}")
    print(f"  Segment : {segment}")
    print(f"  Input   : {preview}")

    confirm = input("\nProceed? (y/n): ").strip().lower()
    if confirm not in ("y", "yes"):
        print("Cancelled.")
        return

    # --- BA generation ---
    async with LoadingAnimator(BA_MESSAGES):
        ba_result = await orchestrator.process_input(
            project_name=project_name,
            user_id="kb-guided-start",
            problem_statement=problem_statement,
            segment=segment,
        )

    if ba_result.get("status") != "success":
        print(f"\nBA FAILED: {ba_result.get('message')}")
        return

    # --- BA approval loop ---
    while True:
        print(f"\nBRD generated -> {ba_result.get('file_path', f'projects/{project_name}/ba-output.md')}")
        print(f"Quality gates: {ba_result.get('quality_gates')}")
        print("Open that file and review it.")

        decision = input("\nApprove BRD and move to PE? (type 'approve', or describe what to change): ").strip()

        if is_approval(decision):
            break

        feedback = _get_feedback(decision, "BRD")
        if not feedback:
            print("Please type 'approve' or describe the changes you want.")
            continue

        clarify_result = await orchestrator.handle_approval(
            project_name=project_name, stage="ba", decision="needs_changes"
        )
        if clarify_result.get("status") != "success":
            print(f"CLARIFICATION FAILED: {clarify_result.get('message')}")
            return

        async with LoadingAnimator(BA_MESSAGES):
            rework_result = await orchestrator.handle_clarification_response(
                project_name=project_name, stage="ba", responses={"feedback": feedback}
            )
        if rework_result.get("status") != "success":
            print(f"BRD REWORK FAILED: {rework_result.get('message')}")
            return

        ba_result = rework_result

    # --- Advance to PE ---
    print("\nBRD approved -> triggering PE agent...")
    async with LoadingAnimator(PE_MESSAGES):
        pe_result = await orchestrator.handle_approval(
            project_name=project_name, stage="ba", decision="approve"
        )

    if pe_result.get("status") != "success":
        print(f"\nPE FAILED: {pe_result.get('message')}")
        return

    # --- PE approval loop ---
    while True:
        session = orchestrator.context_manager.get_session(project_name)
        pe_output = session.get("pe_output", {})
        hallucination_risk = pe_output.get("sources_metadata", {}).get("data_integrity", {}).get("hallucination_risk", "unknown")

        print(f"\nPRD generated -> {pe_result.get('file_path', f'projects/{project_name}/pe-output.md')}")
        print(f"Quality gates: {pe_output.get('quality_gates')}")
        print(f"Sources verified: {pe_output.get('sources_verified_count', 0)}")
        print(f"Hallucination risk: {hallucination_risk}")
        print("Open that file and review it.")

        decision = input("\nApprove PRD and finish? (type 'approve', or describe what to change): ").strip()

        if is_approval(decision):
            done_result = await orchestrator.handle_approval(
                project_name=project_name, stage="pe", decision="approve"
            )
            if done_result.get("status") != "success":
                print(f"APPROVAL FAILED: {done_result.get('message')}")
                return
            print("\nWorkflow complete. BRD and PRD approved.")
            break

        feedback = _get_feedback(decision, "PRD")
        if not feedback:
            print("Please type 'approve' or describe the changes you want.")
            continue

        clarify_result = await orchestrator.handle_approval(
            project_name=project_name, stage="pe", decision="needs_changes"
        )
        if clarify_result.get("status") != "success":
            print(f"CLARIFICATION FAILED: {clarify_result.get('message')}")
            return

        async with LoadingAnimator(PE_MESSAGES):
            rework_result = await orchestrator.handle_clarification_response(
                project_name=project_name, stage="pe", responses={"feedback": feedback}
            )
        if rework_result.get("status") != "success":
            print(f"PRD REWORK FAILED: {rework_result.get('message')}")
            return

        pe_result = rework_result

    print(f"\nBRD -> projects/{project_name}/ba-output.md")
    print(f"PRD -> projects/{project_name}/pe-output.md")
    print(f"Sources -> projects/{project_name}/sources.json, projects/{project_name}/prd-sources.json")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except EOFError:
        print("\nNo more input — exiting.")
    except KeyboardInterrupt:
        print("\nInterrupted — exiting.")
