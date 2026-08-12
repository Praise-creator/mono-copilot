#!/usr/bin/env python3
"""
Full end-to-end test: problem statement -> BRD -> PRD -> 5 RFCs -> export as PDF.

Extends test_full_run.py's pattern (direct problem statement, no
entry-classifier) through the new RFC stage. No ADR step — that's Moses's
scope, not built here.

Run from the repo root (same convention as test_full_run.py/test_guided_start.py,
since FileManager resolves "projects/" relative to cwd):

    uv run --package copilot python3 apps/copilot/test/test_rfc_run.py

No hardcoded scenario — you're prompted for a real problem statement,
segment, and project name at runtime.

What this proves end to end:
  1. PE approval automatically fans out to all 5 RFC sub-agents
     (software_architect first, then ui_ux/security/qa/devops concurrently
     with its output as cross-reference context).
  2. Combined RFC review — one approval gate for all 5, not five separate loops.
  3. Targeted rework — feedback naming a role only reworks that RFC.
  4. Export step — turns any approved document into a PDF and prints the
     resulting path, matching the storm.md sketch (export as PDF -> here's
     your document).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

from copilot.orchestrator import Orchestrator
from copilot.cli.approval_words import is_approval
from copilot.cli.loading_messages import LoadingAnimator, BA_MESSAGES, PE_MESSAGES, RFC_MESSAGES
from copilot.services.pdf_export import export_document
from copilot.services.file_manager import RFC_ROLE_FILENAMES
from copilot.skills.rfc_skill import RFC_ROLES, ROLE_DISPLAY_NAMES, ROLE_ALIASES


SEGMENT_DEFAULT = "general"
PROJECT_NAME_DEFAULT = "untitled-project"
USER_ID = "kb-rfc-test"


def _prompt_for_project_input() -> tuple:
    """Gather a real problem statement, segment, and project name at
    runtime -- no hardcoded scenario. This is the actual live-use path:
    whatever you type here is exactly what the BA agent sees, same as a
    real user would type into the eventual chat interface."""
    print("Describe the business problem or idea you want to explore.")
    print("(Multi-line is fine — press Enter on an empty line when done.)\n")
    lines = []
    while True:
        line = input()
        if line.strip() == "" and lines:
            break
        lines.append(line)
    problem_statement = "\n".join(lines).strip()

    segment = input(f"\nSegment (e.g. postpaid_consumer, enterprise, wholesale) [{SEGMENT_DEFAULT}]: ").strip() or SEGMENT_DEFAULT
    project_name = input(f"Project name (used for the projects/ folder) [{PROJECT_NAME_DEFAULT}]: ").strip() or PROJECT_NAME_DEFAULT

    return problem_statement, segment, project_name


def _get_feedback(decision_text: str, what: str) -> str:
    if decision_text.lower() in ("no", "n", "reject", "disapprove", "decline"):
        return input(f"What should change in {what}? ").strip()
    return decision_text


# RFC_MESSAGES (loading_messages.py) keys its software-architect entry as
# "system_design" — a display-name choice made independently of RFC_ROLES'
# "software_architect" key (rfc_skill.py). Bridged here rather than changing
# either module just to make them match.
_LOADING_KEY = {
    "software_architect": "system_design",
    "ui_ux": "ui_ux",
    "security": "security",
    "qa": "qa",
    "devops": "devops",
}


def _combined_rfc_messages() -> list:
    """All 5 roles are in flight together during the initial fan-out — cycle
    through one message from each rather than picking a single role's set."""
    return [msgs[0] for msgs in RFC_MESSAGES.values()]


def _rework_messages(feedback: str) -> list:
    """Best-effort guess at which role(s) the feedback names, purely to pick
    a fitting loading message — this duplicates orchestrator._match_roles_in_feedback's
    matching logic for cosmetic purposes only. The orchestrator does its own,
    authoritative matching independently; if this guess is wrong or ambiguous,
    it just falls back to the combined set rather than showing a misleading message."""
    feedback_lower = feedback.lower()
    matched = [role for role, aliases in ROLE_ALIASES.items() if any(a in feedback_lower for a in aliases)]
    if len(matched) == 1:
        return RFC_MESSAGES.get(_LOADING_KEY[matched[0]], _combined_rfc_messages())
    return _combined_rfc_messages()


def _print_rfc_summary(rfc_response: dict) -> None:
    print("\nRFCs generated:")
    for role in RFC_ROLES:
        markdown = rfc_response.get("rfc_outputs", {}).get(role)
        gates = rfc_response.get("quality_gates_by_role", {}).get(role, {})
        gates_passed = rfc_response.get("quality_gates_passed_by_role", {}).get(role)
        error = rfc_response.get("errors", {}).get(role)

        display_name = ROLE_DISPLAY_NAMES.get(role, role)
        if error:
            print(f"  [{role}] {display_name}: FAILED — {error}")
            continue

        overall = "PASS" if gates_passed else "FAIL"
        mermaid = "yes" if gates.get("mermaid_diagram_present") else "no"
        length = len(markdown) if markdown else 0
        print(f"  [{role}] {display_name}: gates={overall} ({sum(gates.values())}/{len(gates)}), "
              f"mermaid={mermaid}, {length} chars -> {rfc_response.get('file_paths', {}).get(role, 'n/a')}")


async def main():
    print("\nFULL END-TO-END TEST: Problem Statement -> BRD -> PRD -> 5 RFCs -> Export")
    print("-" * 70)

    problem_statement, segment, project_name = _prompt_for_project_input()

    if not problem_statement:
        print("\nNo problem statement given — nothing to do.")
        return

    print("\n" + "-" * 70)

    orchestrator = Orchestrator()

    # --- BA generation ---
    print("\nStep 1: BA Agent generating BRD from problem statement...\n")

    async with LoadingAnimator(BA_MESSAGES):
        ba_result = await orchestrator.process_input(
            project_name=project_name,
            user_id=USER_ID,
            problem_statement=problem_statement,
            segment=segment,
        )

    if ba_result.get("status") != "success":
        print(f"BA FAILED: {ba_result.get('message')}")
        return

    # --- BA approval loop ---
    while True:
        print(f"\nBRD generated -> {ba_result.get('file_path')}")
        print(f"Quality gates: {ba_result.get('quality_gates')}")
        print("Open that file and review it.")

        decision = input("\nApprove BRD and move to PE? (type 'approve', or describe what to change): ").strip()
        if is_approval(decision):
            break

        feedback = _get_feedback(decision, "the BRD")
        if not feedback:
            print("Please type 'approve' or describe the changes you want.")
            continue

        clarify_result = await orchestrator.handle_approval(project_name=project_name, stage="ba", decision="needs_changes")
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
    print("\n" + "-" * 70)
    print("Step 2: BRD approved -> triggering PE Agent...\n")

    async with LoadingAnimator(PE_MESSAGES):
        pe_result = await orchestrator.handle_approval(project_name=project_name, stage="ba", decision="approve")
    if pe_result.get("status") != "success":
        print(f"PE FAILED: {pe_result.get('message')}")
        return

    # --- PE approval loop ---
    while True:
        session = orchestrator.context_manager.get_session(project_name)
        pe_output = session.get("pe_output", {})

        print(f"\nPRD generated -> {pe_result.get('file_path')}")
        print(f"Quality gates: {pe_output.get('quality_gates')}")
        print("Open that file and review it.")

        decision = input("\nApprove PRD and generate RFCs? (type 'approve', or describe what to change): ").strip()
        if is_approval(decision):
            break

        feedback = _get_feedback(decision, "the PRD")
        if not feedback:
            print("Please type 'approve' or describe the changes you want.")
            continue

        clarify_result = await orchestrator.handle_approval(project_name=project_name, stage="pe", decision="needs_changes")
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

    # --- PE approve triggers all 5 RFCs (software_architect first, then the
    # other 4 concurrently with its output as cross-reference context) ---
    print("\n" + "-" * 70)
    print("Step 3: PRD approved -> generating all 5 RFCs...\n")

    async with LoadingAnimator(_combined_rfc_messages()):
        rfc_result = await orchestrator.handle_approval(project_name=project_name, stage="pe", decision="approve")
    if rfc_result.get("status") not in ("success", "partial_success"):
        print(f"RFC GENERATION FAILED: {rfc_result.get('message')}")
        return

    # --- RFC approval loop (one combined gate for all 5) ---
    while True:
        _print_rfc_summary(rfc_result)
        print(f"\n{rfc_result.get('message', '')}")

        decision = input(
            "\nApprove all RFCs and finish? (type 'approve', or name a role and "
            "describe the change, e.g. 'security: add key rotation detail'): "
        ).strip()

        if is_approval(decision):
            done_result = await orchestrator.handle_approval(project_name=project_name, stage="rfc", decision="approve")
            if done_result.get("status") != "success":
                print(f"APPROVAL FAILED: {done_result.get('message')}")
                return
            print(f"\n{done_result.get('message')}")
            break

        clarify_result = await orchestrator.handle_approval(project_name=project_name, stage="rfc", decision="needs_changes")
        if clarify_result.get("status") != "success":
            print(f"CLARIFICATION FAILED: {clarify_result.get('message')}")
            return

        async with LoadingAnimator(_rework_messages(decision)):
            rework_result = await orchestrator.handle_clarification_response(
                project_name=project_name, stage="rfc", responses={"feedback": decision}
            )
        if rework_result.get("status") == "error":
            # Ambiguous feedback — orchestrator asked for clarification, not a hard failure.
            print(f"\n{rework_result.get('message')}")
            continue
        rfc_result = rework_result

    # --- Export step: view the files, export as PDF, respond with the link ---
    print("\n" + "-" * 70)
    print("Step 4: Export as PDF")
    print("Available documents: brd, prd, " + ", ".join(RFC_ROLES) + ", all")

    session = orchestrator.context_manager.get_session(project_name)
    ba_output = session.get("ba_output", {})
    pe_output = session.get("pe_output", {})
    rfc_outputs = session.get("rfc_outputs", {})

    choice = input("\nWhich document(s) to export? ").strip().lower()
    if not choice:
        print("Nothing exported.")
    else:
        targets = list(RFC_ROLES) + ["brd", "prd"] if choice == "all" else [c.strip() for c in choice.split(",")]
        for target in targets:
            if target == "brd":
                path = export_document(project_name, "brd", ba_output.get("markdown", ""))
            elif target == "prd":
                path = export_document(project_name, "prd", pe_output.get("markdown", ""))
            elif target in rfc_outputs and rfc_outputs[target].get("status") == "success":
                path = export_document(project_name, target, rfc_outputs[target]["markdown"])
            else:
                print(f"  Skipped '{target}' — not a recognized or available document.")
                continue
            print(f"  {target} -> {path}")

    print("\n" + "-" * 70)
    print("Files saved:")
    print(f"  BRD -> projects/{project_name}/ba-output.md")
    print(f"  PRD -> projects/{project_name}/pe-output.md")
    for role in RFC_ROLES:
        print(f"  {role} RFC -> projects/{project_name}/adr/{RFC_ROLE_FILENAMES[role]}.md")
    print(f"  Exports -> projects/{project_name}/exports/")
    print("-" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except EOFError:
        print("\nNo more input — exiting.")
    except KeyboardInterrupt:
        print("\nInterrupted — exiting.")
