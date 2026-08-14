"""
Regenerate just the Security RFC for an existing project, reusing its
already-approved PRD -- avoids paying for a full BA->PE->5-RFC run just to
confirm the compliance-fetch tool actually gets used correctly by a live
agent call, not just by fetch_compliance_excerpt() in isolation.

Run from apps/copilot/:
    uv run --package copilot python3 test/debug_security_rfc_only.py mtn-nigeria-churn-v3
"""
import asyncio
import sys

sys.path.insert(0, "src")

from copilot.services.file_manager import FileManager
from copilot.agents.rfc_agent import RFCAgent


async def main():
    if len(sys.argv) < 2:
        print("Usage: python3 test/debug_security_rfc_only.py <project_name>")
        return

    project_name = sys.argv[1]
    file_manager = FileManager()

    prd_markdown = file_manager.load_prd(project_name)
    if not prd_markdown:
        print(f"No PRD found on disk for project '{project_name}'")
        return

    print(f"Loaded PRD for '{project_name}' ({len(prd_markdown)} characters). Regenerating Security RFC...\n")

    agent = RFCAgent()
    result = await agent.run(
        role="security",
        prd_dict={"markdown": prd_markdown, "quality_gates_passed": True},
    )

    if result.get("status") != "success":
        print("FAILED:", result.get("error"))
        return

    print(result["markdown"])
    print("\n\nQuality gates:", result.get("quality_gates"))


if __name__ == "__main__":
    asyncio.run(main())
