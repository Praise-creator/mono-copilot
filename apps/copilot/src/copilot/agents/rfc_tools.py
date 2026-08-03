"""
RFC tool exposure — the actual hand-off interface for Moses's ADR/Solution
Architect agent.

Design note (read this before changing the tool-wrapping approach): the
initial plan said to expose each sub-agent via Agent.as_tool(). Checked what
that actually does in the installed SDK (openai-agents 0.17.7, agents/agent.py):
as_tool() re-runs the bare nested Agent fresh and extracts its raw text
output. It does NOT run our quality-gate checks, source verification, or
file persistence — those all live in rfc_skill.py's generate_rfc() and
RFCAgent.run(), which as_tool() has no way to invoke. Using it as originally
planned would have handed Moses's agent an unverified, ungated draft while
KB's own orchestrator path produces the fully verified version — the exact
kind of two-paths-that-quietly-disagree bug this project has hit before.

Instead, each of the 5 tools below is built with @function_tool wrapping the
FULL pipeline (RFCAgent.run() -> quality gates -> TechnicalResearchService
verification -> footnotes -> file persistence). Whichever path Moses's agent
takes — calling these tools fresh, or just reading the already-approved
files under projects/{name}/adr/ — the content is the same quality, because
both paths go through the identical generate_rfc() pipeline.

Known limitation, stated plainly rather than glossed over: these tools
trust that a PRD file existing on disk (projects/{name}/pe-output.md) means
it's usable. There is currently no persisted "PRD was human-approved" flag
on disk — ContextManager session state (which does track that) is in-memory
only and tied to a single orchestrator process, and disk persistence for it
is separate, already-flagged teammate work, not built here. Once that
exists, this file's approval check should be tightened to read it instead
of trusting file presence alone.
"""

from typing import Optional

from agents import function_tool, FunctionTool

from .rfc_agent import RFCAgent
from ..services.file_manager import FileManager
from ..skills.rfc_skill import RFC_ROLES, ROLE_DISPLAY_NAMES


async def _run_and_persist_rfc(role: str, project_name: str) -> str:
    """Shared implementation behind all 5 tool functions below. Loads the
    approved PRD from disk, runs the full generate_rfc() pipeline for this
    role, persists the result, and returns the enhanced markdown plus a
    quality-gate summary as the tool's model-visible output."""
    file_manager = FileManager()

    prd_markdown = file_manager.load_prd(project_name)
    if not prd_markdown:
        return (
            f"No PRD found on disk for project '{project_name}' "
            f"(expected projects/{project_name}/pe-output.md). Generate and "
            f"approve a BRD and PRD via the BA/PE pipeline before requesting "
            f"RFCs for this project."
        )

    # See module docstring: file presence is currently the only signal
    # available to a standalone tool call about whether the PRD is usable.
    prd_dict = {"markdown": prd_markdown, "quality_gates_passed": True}

    system_design_context: Optional[str] = None
    if role != "software_architect":
        system_design_context = file_manager.load_rfc(project_name, "software_architect")

    agent = RFCAgent()
    result = await agent.run(
        role=role,
        prd_dict=prd_dict,
        system_design_context=system_design_context,
    )

    if result.get("status") != "success":
        return (
            f"RFC generation failed for role '{role}' on project "
            f"'{project_name}': {result.get('error', 'unknown error')}"
        )

    markdown = result["markdown"]
    file_manager.save_rfc(project_name, role, markdown)
    file_manager.save_rfc_sources(project_name, role, result.get("sources_metadata", {}))

    gates = result.get("quality_gates", {})
    gates_summary = "\n".join(f"- {name}: {'PASS' if passed else 'FAIL'}" for name, passed in gates.items())
    overall = "ALL GATES PASS" if result.get("quality_gates_passed") else "SOME GATES FAILED — review before relying on this RFC"

    return (
        f"{markdown}\n\n"
        f"---\n"
        f"Quality gates ({overall}):\n"
        f"{gates_summary}\n"
    )


@function_tool
async def generate_ui_ux_rfc(project_name: str) -> str:
    """Generate the UI/UX RFC for a project whose PRD has already been
    approved. Covers user journeys per role, information architecture,
    interaction states, WCAG 2.1 AA accessibility, and a user-journey
    Mermaid diagram. Persists the result to projects/{project_name}/adr/ui-ux.md.

    Args:
        project_name: The mono-copilot project's name.
    """
    return await _run_and_persist_rfc("ui_ux", project_name)


@function_tool
async def generate_system_design_rfc(project_name: str) -> str:
    """Generate the Software Architect (system-design) RFC for a project
    whose PRD has already been approved. Covers component boundaries,
    deployment topology, data-flow tracing, scalability, and a system
    architecture Mermaid diagram. Persists the result to
    projects/{project_name}/adr/system-design.md.

    Args:
        project_name: The mono-copilot project's name.
    """
    return await _run_and_persist_rfc("software_architect", project_name)


@function_tool
async def generate_security_rfc(project_name: str) -> str:
    """Generate the Security RFC for a project whose PRD has already been
    approved. Covers a STRIDE threat model against real components, controls
    mapped to OWASP ASVS / NIST CSF, encryption and key management, auth and
    access control, audit logging, and country-scoped data-protection
    compliance (only citing what's already verified). Persists the result to
    projects/{project_name}/adr/security.md.

    Args:
        project_name: The mono-copilot project's name.
    """
    return await _run_and_persist_rfc("security", project_name)


@function_tool
async def generate_qa_rfc(project_name: str) -> str:
    """Generate the QA RFC for a project whose PRD has already been
    approved. Covers test levels, full acceptance-criteria-to-test-case
    traceability, NFR test coverage, test data/environment strategy, and
    defect management. Persists the result to
    projects/{project_name}/adr/qa.md.

    Args:
        project_name: The mono-copilot project's name.
    """
    return await _run_and_persist_rfc("qa", project_name)


@function_tool
async def generate_devops_rfc(project_name: str) -> str:
    """Generate the DevOps RFC for a project whose PRD has already been
    approved. Covers CI/CD pipeline stages, environment strategy,
    infrastructure as code, 5-layer monitoring with numeric thresholds,
    deployment strategy, disaster recovery RTO/RPO, and a deployment
    pipeline Mermaid diagram. Persists the result to
    projects/{project_name}/adr/devops.md.

    Args:
        project_name: The mono-copilot project's name.
    """
    return await _run_and_persist_rfc("devops", project_name)


_ALL_RFC_TOOLS = [
    generate_ui_ux_rfc,
    generate_system_design_rfc,
    generate_security_rfc,
    generate_qa_rfc,
    generate_devops_rfc,
]


def get_rfc_tools() -> list[FunctionTool]:
    """Returns the 5 RFC-generator tools, ready to drop into any Agent's
    tools=[...] list. This is the entry point Moses's Solution Architect
    agent imports — the actual hand-off from KB's RFC sub-agents to his
    ADR synthesis, per the "use tools for agent interaction from rfc to
    adr" decision."""
    return list(_ALL_RFC_TOOLS)
