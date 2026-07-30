#!/usr/bin/env python3
"""
PE Skill Test - validates PRD generation from a sample BRD.
Shows: mermaid diagrams, source verification, quality gates, no hallucination.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "apps" / "copilot" / "src"))

from copilot.skills.pe_skill import PESkill


SAMPLE_BRD = {
    "document_id": "BRD-20260724-120000",
    "segment": "postpaid_consumer",
    "problem_statement": "Reduce customer churn in metro Nigeria markets through AI-powered agent recommendations",
    "quality_gates_passed": True,
    "markdown": """
# Business Requirements Document — AI Churn Reduction

## Overview
Nigeria's postpaid market sees 15% annual churn in metro Lagos and Abuja.
Current process: customer calls IVR, routed to agent, agent manually reviews account (45 second average), makes retention offer decision.
Bottleneck: 45 second decision time, 15% call abandon rate during wait.

## Proposed Solution
Deploy AI recommendation engine that pre-scores customer before agent receives the call.
Agent sees: recommended offer, confidence score, customer risk tier.
Expected outcome: decision time drops to 20 seconds, abandon rate drops to 5%.

## Integrations Required
- CRM (Salesforce): customer profile, contract history, ARPU
- AI Scoring Service: real-time recommendation generation
- IVR (Genesys Cloud): pre-call data trigger
- Agent Portal (internal): recommendation display
- Analytics Platform (internal): outcome tracking

## Key Business Metrics
- Churn target: reduce from 15% to 8% in metro markets
- Decision time target: under 20 seconds
- Offer acceptance target: 35% (baseline 20%)
- System availability requirement: 99.95%

## Regulatory Context
NCC Nigeria mandates customer data remain on-prem within Nigerian borders.
Customer interaction logs must be retained for audit purposes per NCC directive.
All agent-customer interactions must be recorded and stored.

## Business Rules
- Only agents assigned to a customer territory can see that customer's offers
- Offers above 50,000 naira require supervisor approval before presentation
- Recommendations expire after 2 hours — system must re-score if stale
- Agents cannot override AI confidence score without logging a reason
""",
}


async def main():
    print("\nPE SKILL TEST")
    print("Enterprise MNO — Nigeria Postpaid Churn Reduction")
    print("-" * 70)

    skill = PESkill()

    print("\nGenerating PRD from approved BRD...")
    print("(This calls OpenAI and may take 20-40 seconds)\n")

    result = await skill.generate_prd(brd_dict=SAMPLE_BRD, run_count=1)

    if result.get("status") != "success":
        print(f"FAILED: {result.get('error')}")
        return

    print(f"Document ID : {result.get('document_id')}")
    print(f"BRD Reference: {result.get('brd_reference')}")
    print(f"File saved  : {result.get('file_path')}")
    print(f"Sources     : {result.get('sources_verified_count')} verified")
    print()

    print("Quality Gates:")
    for gate, passed in result.get("quality_gates", {}).items():
        status = "PASS" if passed else "FAIL"
        print(f"  {gate}: {status}")

    overall = "PASS" if result.get("quality_gates_passed") else "FAIL"
    print(f"\nOverall: {overall}")

    markdown = result.get("markdown", "")

    print()
    print("Content checks:")
    print(f"  PRD length         : {len(markdown)} characters")
    print(f"  Mermaid diagrams   : {'YES - ' + str(markdown.count('```mermaid')) + ' diagram(s)' if '```mermaid' in markdown else 'NO'}")
    print(f"  Verified references: {'YES' if 'Verified References' in markdown else 'NO'}")
    print(f"  Hallucination risk : {result.get('sources_metadata', {}).get('data_integrity', {}).get('hallucination_risk', 'unknown').upper()}")

    print()
    print("PRD Preview (first 800 characters):")
    print("-" * 70)
    print(markdown[:800])
    print("...")

    if "```mermaid" in markdown:
        print()
        print("Mermaid Diagram Preview:")
        print("-" * 70)
        start = markdown.find("```mermaid")
        end = markdown.find("```", start + 10) + 3
        print(markdown[start:end])


if __name__ == "__main__":
    asyncio.run(main())
