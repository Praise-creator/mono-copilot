#!/usr/bin/env python3
"""
Full end-to-end test: problem statement → BRD → approval → PRD.
No hardcoded BRD. The BA agent generates the BRD from scratch, then the
PE agent generates the PRD from that BRD. Same flow as production.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "apps" / "copilot" / "src"))

from copilot.orchestrator import Orchestrator


PROBLEM_STATEMENT = """
Nigeria's largest postpaid segment is experiencing 18% annual churn concentrated
in metro Lagos and Abuja. Current retention process: customer calls IVR, queued
to agent, agent manually reviews account history in Salesforce (average 45 seconds),
agent decides on retention offer without data-driven guidance.

Key pain points:
- 15% of customers abandon during the 45-second wait before agent engages
- Agents rely on gut feel for offer selection — acceptance rate is 20%
- No feedback loop: accepted/rejected offers not fed back to improve future decisions
- CRM, IVR (Genesys), and Agent Portal are siloed — no real-time data sharing

Goal: deploy an AI recommendation engine that pre-scores each customer before the
agent picks up, surfacing the right retention offer with a confidence score.
Target: reduce decision time to under 20 seconds, cut churn to 10%, lift
offer acceptance to 35%.

Compliance: NCC mandates all customer data remain on Nigerian soil. All agent-customer
interactions must be logged and retained for regulatory audit.
"""

SEGMENT = "postpaid_consumer"
PROJECT_NAME = "nigeria-churn-reduction-v1"
USER_ID = "kb-test"


async def main():
    print("\nFULL END-TO-END TEST: Problem Statement → BRD → PRD")
    print("No hardcoded inputs. Real BA → Real PE.")
    print("-" * 70)

    orchestrator = Orchestrator()

    print("\nStep 1: BA Agent generating BRD from problem statement...")
    print("(This calls OpenAI — expect 30-60 seconds)\n")

    ba_result = await orchestrator.process_input(
        project_name=PROJECT_NAME,
        user_id=USER_ID,
        problem_statement=PROBLEM_STATEMENT,
        segment=SEGMENT
    )

    if ba_result.get("status") != "success":
        print(f"BA FAILED: {ba_result.get('message')}")
        return

    print(f"BRD generated")
    print(f"Stage    : {ba_result.get('stage')}")
    print(f"Document : {ba_result.get('document_id')}")

    brd_gates = ba_result.get("quality_gates", {})
    print("\nBA Quality Gates:")
    for gate, passed in brd_gates.items():
        print(f"  {gate}: {'PASS' if passed else 'FAIL'}")

    brd_markdown = ba_result.get("output", "")
    print(f"\nBRD length : {len(brd_markdown)} characters")
    has_mermaid = "```mermaid" in brd_markdown
    print(f"BRD Mermaid: {'YES - ' + str(brd_markdown.count('```mermaid')) + ' diagram(s)' if has_mermaid else 'NO'}")

    print("\nBRD Preview (first 600 characters):")
    print("-" * 70)
    print(brd_markdown[:600])
    print("...")

    print("\n" + "-" * 70)
    print("Step 2: Approving BRD → triggering PE Agent...")
    print("(This calls OpenAI again — expect another 30-60 seconds)\n")

    pe_result = await orchestrator.handle_approval(
        project_name=PROJECT_NAME,
        stage="ba",
        decision="approve"
    )

    if pe_result.get("status") != "success":
        print(f"PE FAILED: {pe_result.get('message')}")
        return

    print(f"PRD generated")
    print(f"Stage    : {pe_result.get('stage')}")
    print(f"Document : {pe_result.get('document_id')}")

    session = orchestrator.context_manager.get_session(PROJECT_NAME)
    pe_output = session.get("pe_output", {})

    prd_gates = pe_output.get("quality_gates", {})
    print("\nPE Quality Gates:")
    for gate, passed in prd_gates.items():
        print(f"  {gate}: {'PASS' if passed else 'FAIL'}")

    overall = "PASS" if pe_output.get("quality_gates_passed") else "FAIL"
    print(f"\nOverall PE: {overall}")

    prd_markdown = pe_result.get("output", "")
    sources_count = pe_output.get("sources_verified_count", 0)
    hallucination_risk = pe_output.get("sources_metadata", {}).get("data_integrity", {}).get("hallucination_risk", "unknown")

    print(f"\nPRD length        : {len(prd_markdown)} characters")
    print(f"Sources verified  : {sources_count}")
    print(f"Hallucination risk: {hallucination_risk.upper()}")

    has_prd_mermaid = "```mermaid" in prd_markdown
    print(f"Mermaid diagrams  : {'YES - ' + str(prd_markdown.count('```mermaid')) + ' diagram(s)' if has_prd_mermaid else 'NO'}")
    print(f"Verified refs     : {'YES' if 'Verified References' in prd_markdown else 'NO'}")

    print("\nPRD Preview (first 600 characters):")
    print("-" * 70)
    print(prd_markdown[:600])
    print("...")

    if has_prd_mermaid:
        print("\nFirst Mermaid Diagram:")
        print("-" * 70)
        start = prd_markdown.find("```mermaid")
        end = prd_markdown.find("```", start + 10) + 3
        print(prd_markdown[start:end])

    print("\n" + "-" * 70)
    print("Files saved:")
    print(f"  BRD → projects/{PROJECT_NAME}/ba-output.md")
    print(f"  PRD → projects/{PROJECT_NAME}/pe-output.md")
    print("-" * 70)

    if pe_output.get("quality_gates_passed") and hallucination_risk == "low":
        print("\nRESULT: PRODUCTION READY")
    else:
        print("\nRESULT: NEEDS REVIEW")
        print("Check failed gates above and re-run if needed.")


if __name__ == "__main__":
    asyncio.run(main())
