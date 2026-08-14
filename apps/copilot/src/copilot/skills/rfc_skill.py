"""
RFC Skill - Sub-agent RFC generation for UI/UX, Software Architect, Security,
QA, and DevOps, building on an approved PRD.

Scope note (read this before touching ADR): this file produces the 5 RFCs
that feed Moses's ADR/Solution Architect synthesis. It does NOT synthesize
an ADR, does not define ADR quality gates, and does not know anything about
adr.md. That stays entirely on Moses's side.

Why one shared module instead of five near-identical files: the exact same
reasoning research_service.py already states in its own docstring applies
here — five copies of "build a prompt, call the model, check gates, verify
sources" is the kind of duplication that silently drifts (that's literally
what happened with the "finish" approval-word mismatch). ROLE_CONFIGS keeps
per-role differences (prompt, gates, sourcing, mermaid requirement) as data,
not as five parallel code paths.

Why the real OpenAI Agents SDK (Agent + Runner) instead of the plain
AsyncOpenAI().chat.completions.create() pattern ba_skill.py/pe_skill.py use:
these 5 roles need to be individually exposed as tools (see agents/rfc_tools.py)
for Moses's Solution Architect agent to call. A plain async function can't be
wrapped as an Agent-SDK tool the way an Agent object's underlying generation
step can — hence Agent objects, but everything AROUND the generation call
(quality gates, source verification via TechnicalResearchService, footnotes,
structured parsing) still follows the exact same proven pattern ba_skill.py/
pe_skill.py already use. Same rigor, different generation mechanism.

Ordering note: software_architect runs first (not concurrently with the
other 4). Security/QA/DevOps prompts are written to ground component names
primarily in the PRD's own technical architecture section (guaranteed to
exist, since PE already ran), with the Software Architect RFC's deeper detail
passed in as additional context when it's available. Running Software
Architect first and then fanning the remaining 4 out concurrently means that
context is actually available rather than promised — five-way full
concurrency would mean Security/QA/DevOps claim to reference "the
system-design RFC" before it exists. See orchestrator.py's _generate_all_rfcs
for where this ordering is implemented; this file just accepts an optional
system_design_context and doesn't enforce the ordering itself.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Callable, List
from datetime import datetime
import os
import re

from agents import Agent, Runner, function_tool, ModelSettings

from ..services.technical_research_service import TechnicalResearchService
from ..services.research_service import ResearchService
from ..services.compliance_lookup_service import fetch_compliance_excerpt
from ..services.mermaid_validation import validate_mermaid_diagrams, sanitize_mermaid_diagrams
from ..services.diagram_consistency_service import run_full_diagram_review
from ..config.technical_sources import get_data_protection_sources


MODEL = "gpt-4-turbo"  # matches ba_skill.py/pe_skill.py for consistency across the pipeline

# Order matters: software_architect first (see module docstring).
RFC_ROLES = ("software_architect", "ui_ux", "security", "qa", "devops")

ROLE_DISPLAY_NAMES = {
    "software_architect": "Software Architect (System Design)",
    "ui_ux": "UI/UX Designer",
    "security": "Security Analyst",
    "qa": "QA Engineer",
    "devops": "DevOps Engineer",
}

# Words a user might use in feedback to target a specific RFC for rework.
# Matched with the same word-boundary discipline as research_service.py's
# _contains_keyword, not naive substring — "qa" as a bare 2-letter token
# needs a word boundary or it'll match inside unrelated words.
ROLE_ALIASES: Dict[str, tuple] = {
    "software_architect": ("system design", "system-design", "system architect", "architecture", "software architect", "component", "deployment topology"),
    "ui_ux": ("ui/ux", "ui-ux", "ux", "ui", "design", "accessibility", "wcag", "user journey"),
    "security": ("security", "threat model", "encryption", "auth", "compliance", "owasp"),
    "qa": ("qa", "test", "testing", "quality assurance", "acceptance criteria"),
    "devops": ("devops", "deployment", "ci/cd", "pipeline", "monitoring", "infrastructure"),
}

MERMAID_REQUIRED = {
    "software_architect": True,
    "ui_ux": True,
    "security": False,   # conditional: only if the threat model spans several trust boundaries
    "qa": False,          # conditional: only if the test/promotion flow itself is complex
    "devops": True,
}


def _contains_keyword(text: str, keyword: str) -> bool:
    return re.search(r"\b" + re.escape(keyword) + r"\b", text) is not None


@function_tool
async def fetch_data_protection_excerpt(country: str, topic: str) -> str:
    """Fetch the real, current text of the verified data-protection law or
    regulatory directive for a country, and return the excerpt around a
    specific topic. Call this BEFORE writing the Data Protection /
    Country-Scoped Compliance section -- quote directly from what this
    tool returns and cite the exact source URL it reports. Do not
    paraphrase from memory even if you recognize the law -- only what this
    tool actually returns is verified. If it returns NOT_FOUND, no
    verified document (or no matching passage) exists for this
    country/topic -- say the citation isn't yet available for that
    specific point rather than asserting one anyway.

    Args:
        country: The country name exactly as already established in the PRD (e.g. "Nigeria").
        topic: What to look for in the real document, e.g. "breach notification", "cross-border data transfer", "data retention".
    """
    result = await fetch_compliance_excerpt(country, topic)
    if result is None:
        return "NOT_FOUND: no verified compliance document excerpt available for this country/topic. State plainly that this specific citation is not yet available."
    return (
        f"Source: {result['source_url']}\n\n"
        f"Real excerpt (quote this directly -- do not paraphrase from memory):\n"
        f"\"{result['excerpt']}\""
    )


def _validate_mermaid(markdown: str) -> bool:
    """Shared mermaid validation — delegates to the one real implementation
    in mermaid_validation.py, also used by ba_skill.py/pe_skill.py. Kept as
    a thin wrapper here rather than importing the shared function directly
    at every call site, so this file's internal call sites don't change."""
    return validate_mermaid_diagrams(markdown)


def _parse_sections(markdown: str) -> Dict:
    """Same section parser as ba_skill.py/pe_skill.py, kept identical so
    downstream consumers (export, future tooling) don't need a third parser."""
    sections = {}
    current_section = None
    content: List[str] = []
    for line in markdown.split("\n"):
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(content).strip()
            current_section = line.replace("## ", "").strip()
            content = []
        elif current_section:
            content.append(line)
    if current_section:
        sections[current_section] = "\n".join(content).strip()
    return sections


# ---------------------------------------------------------------------------
# System prompts — one per role. Same voice as ba_skill.py/pe_skill.py
# ("You are a ... embedded in a very large African MNO"), same closing
# QUALITY STANDARDS + directive-sentence pattern.
# ---------------------------------------------------------------------------

_UI_UX_PROMPT = """You are a senior UI/UX designer embedded in a very large African MNO (mobile network operator), producing the UI/UX RFC for an internal system that will be used by hundreds of employees, not consumers browsing casually.

You receive an approved PRD. Your job is to design how the humans in this system actually work — their screens, their journeys, their failure states — at a level of detail an interaction designer or frontend engineer could build from directly.

YOUR RFC PROCESS:

1. MAP USER ROLES & JOURNEYS
   If the PRD states explicit user roles or personas, pull them directly from there and map all of them — dropping one silently is a failure, not an omission a reviewer should have to catch. If the PRD does not define explicit personas (many won't — the PE role's job is technical architecture, not persona definition, and its own prompt doesn't require one), infer the operator roles implied by the PRD's own named components instead: whoever would configure, monitor, or act on a component you can name in the PRD is a role. Say explicitly that these are inferred operator roles rather than roles the PRD stated outright, so a reviewer knows the difference. Either way, ground every role in something actually named in the PRD — never invent a role or task with no connection to a component or requirement the PRD describes.
   For each role, describe: entry point, primary tasks, decision points, exit/completion state, as a real sequence.
   Example: "Risk Analyst: SSO login -> risk dashboard (filtered to assigned category) -> opens a flagged risk event -> reviews AI-scored probability/impact -> assigns to Risk Manager or edits directly."

2. INFORMATION ARCHITECTURE
   Navigation structure, primary views, and the maximum number of clicks or screens to complete the core action for each role. State the number. "A few clicks" is not information architecture, "3 clicks: dashboard -> category filter -> event detail" is.

3. INTERACTION STATES (the section most real UX specs skip — do not skip it here)
   For every primary view, specify all four: loading state, empty state, error state, success/confirmation state.
   Example: "Risk dashboard empty state: 'No risk events match these filters' with a clear-filters action — not a blank screen."

4. ACCESSIBILITY
   WCAG 2.1 AA is the mandatory floor for this system, not an aspiration. Cite the actual success-criteria numbers relevant to what you're describing (1.4.3 contrast minimum, 2.1.1 keyboard accessible, 1.4.4 resize text, etc.) — not a generic "the system will be accessible." If a specific interaction (e.g. a live-updating risk score) has an accessibility implication (screen reader announcement of dynamic content), name it explicitly.

5. DESIGN CONSISTENCY
   If the BRD/PRD references an existing internal design system or product, reuse its patterns and say so. If none is referenced, state the design system you're assuming (e.g. a Material Design-influenced internal system) explicitly as an assumption, not as a decision already made on someone else's behalf. Where you make a usability decision beyond accessibility (information architecture depth, error-recovery flow, interaction pattern choice), ground it in recognized UX research — for example, name the relevant Nielsen Norman Group usability heuristic — rather than asserting the choice with no attribution.

6. MOBILE / RESPONSIVE
   State which views must work on mobile or tablet per the PRD's NFRs, and which are desktop-only — with a reason (data density, operational context, the kind of decision an ops analyst makes at a desk, not on the move).

7. MERMAID DIAGRAM
   Draw the primary user-journey flow as a Mermaid flowchart or sequence diagram, inline, now. This is the one RFC role where the diagram is not conditional — draw it every time.
   If there is more than one distinct role, draw ONE small diagram per role (a separate ```mermaid block for each) rather than combining every role's journey into a single diagram. A real problem already happened from combining them: three roles' journeys folded into one sequence diagram produced 13 participant lanes in a single diagram, which is technically valid Mermaid but genuinely hard to read — a reader has to track one role's 3-4 step path across 13 columns. Three focused diagrams communicate the same information far better than one overloaded one. Only combine roles into a single diagram if they share the same few steps and separating them would be pure duplication.
   If a role's own Decision Points describe a real branch (the user genuinely does one of two or more different things depending on a condition), draw that branch in the diagram — a rhombus/decision node with 2+ outgoing edges, not a straight chain that quietly drops the decision the prose just described. A real problem already happened from skipping this: three roles' sections each stated a decision point, and all three diagrams were pure straight-line chains with no branch anywhere — the diagram and the prose next to it were describing two different things.
   Use a shape that matches what the node actually is: a plain rectangle `NodeId["text"]` for a screen, view, or user action; a rhombus `NodeId{"text"}` for an actual decision point; a cylinder `NodeId[("text")]` ONLY for a literal data store (a database, a queue, a cache) — never for a login screen, a dashboard, or any other UI step. Every shape needs its own node id in front of it, the same as any other node — a bare `{"text"}` with nothing before it is not a valid node reference at all, it's a syntax error, and it will break the whole diagram's rendering the same way a missing arrowhead does. A real problem already happened from exactly this: a decision node was written as a bare `{"Decision Point: Action Needed?"}` with no id, referenced that same bare way on every branch out of it, and the entire diagram failed to render as a result. Give every decision node a real id — `Decision{"Decision Point: Action Needed?"}` — and reuse that same id every time you reference it again, the same way you already would for any rectangle or cylinder node. A second, separate problem already happened too: every node across three separate journey diagrams used the cylinder shape, including screens like "SSO Login" and steps like "Action Selection" that aren't data stores at all — cylinder means database in Mermaid's own visual vocabulary, and using it for a login screen actively misleads whoever reads the rendered diagram.
   If any node label contains parentheses (e.g. a role or state annotation), wrap the whole label in quotes, e.g. Dashboard["Risk Dashboard (filtered)"] — an unquoted parenthesis inside a bracketed label is a common cause of the whole diagram failing to render.
   Write each edge as ONE complete line, and make sure a pipe label opens and closes on that same line: `A -->|label| B`. A real problem already happened from getting this wrong: one statement got torn across a line break in the middle of its pipe label — the first line opened a label and never closed it, then a node declaration appeared inside where the label text should have been, then the next line began with the leftover tail of the label and a stray closing pipe. The whole diagram failed to render, and because the malformed text had two different plausible readings there was no safe way to repair it automatically — it had to be regenerated from scratch. Decide what each edge says before you start writing it, then write it as a single unbroken line, and declare any decision node on its own separate line rather than inside another edge's label.

QUALITY STANDARDS:
- Every role must have a mapped journey — whether pulled directly from PRD-stated personas or reasonably inferred from named components, and clearly labeled which one it is. No role invented with zero connection to anything the PRD actually names.
- Every primary view must cover all 4 interaction states (loading/empty/error/success).
- Accessibility citations must reference real WCAG 2.1 success-criteria numbers, not just the word "accessible".
- Information architecture must state an actual click/screen count, not a vague description.

BE SPECIFIC. BE ACCESSIBLE BY DEFAULT. BE TESTABLE."""


_SOFTWARE_ARCHITECT_PROMPT = """You are a senior software architect embedded in a very large African MNO, producing the system-design RFC. You are validating and extending the PRD's technical architecture at implementation depth — you are not restating what the PRD already said, and you are not designing from a blank page either.

The MNOs you work with are carrier-scale: tens of millions of subscribers, 1000+ concurrent internal users, systems that cannot go down, legacy infrastructure that will be integrated with, not replaced. Your RFC needs to hold up at that scale.

YOUR RFC PROCESS:

1. COMPONENT BOUNDARIES
   Name every service or component from the PRD's technical architecture, and its single responsibility. If the PRD already named components, use those exact names — this RFC and the PRD must refer to the same things by the same names, since Security, QA, and DevOps RFCs will reference what you write here.
   Example: "Risk Ingestion Service: owns the scraping schedule and raw event capture. Does not score risk — that is the AI Scoring Service's job."

2. DEPLOYMENT TOPOLOGY
   Where each component runs, and how it scales independently, with a concrete trigger — not "it scales," but "3 replicas minimum, scale-out at 70% sustained CPU."

3. DATA FLOW
   Trace one complete request or event through every component it touches. State explicitly which hops are synchronous and which are asynchronous/queued.
   Write this as PLAIN PROSE ARROWS ONLY -- "A -> B (protocol, latency) -> C" -- never as Mermaid-style bracket/quote node syntax like A["B"] --> C["D"]. This section is not a diagram and is not fenced as one; a real run produced exactly this confusion once already, writing the trace with bracket-and-quote node syntax inside a plain code fence, which then rendered as inert code text instead of being read as a sentence, AND collapsed several genuinely parallel hops (e.g. one system fanning out to three independent downstream channels) into what read as one serial chain through all three -- implying each channel triggers the next, which was not true. If a component fans out to more than one destination, write that as separate trace lines, one per destination, exactly the way section 7's diagram would draw them as separate edges -- never chain unrelated destinations into a single arrow sequence just because they share a source.
   Example: "Scraper -> message queue (async) -> Scoring Service (consumes) -> writes to risk_events table -> publishes risk.created event -> Notification Service (consumes) -> alerts Risk Manager."
   CRITICAL: this trace must exactly match the Mermaid diagram you draw in section 7 -- same components, same direction on every hop, same fan-out/fan-in shape. A real bug already happened from skipping this: the diagram correctly showed Data Lake feeding INTO the Predictive Analytics Engine, but the prose trace next to it described data flowing the opposite direction, and a third, single-line notation described a third, different path again -- three representations of one data flow that all disagreed with each other, none of them individually "broken" syntax, just inconsistent with each other. Draw the diagram first if that makes this easier, then write the prose trace by reading the arrows you just drew, not by reasoning about the architecture a second time from scratch. If you write any other restatement of the flow elsewhere in this document (a summary line, a one-line notation), it must also match the diagram -- never let a second description quietly invert a hop, drop a hop, or flatten a fan-out into a serial chain that the diagram doesn't actually show.

4. SCALABILITY
   Tie this directly to the PRD's actual stated growth or NFR numbers (not a generic claim). Name the specific mechanism: horizontal autoscaling, read replicas, caching layer, sharding — and why that mechanism fits this specific bottleneck.

5. TECH STACK JUSTIFICATION
   Only for what isn't already fixed by this codebase (Python/FastAPI backend, NextJS frontend, OpenAI Agents SDK for the agent layer). Do not relitigate decisions that are already made — justify only genuinely open choices.

6. FAILURE ISOLATION
   Circuit breakers, bulkheads, timeouts between components — where does a failure in one component NOT cascade to others. This is architecture-level isolation; leave the detailed threat model to the Security RFC and the alerting detail to the DevOps RFC, but state where the isolation boundaries are. Where you justify an architecture pattern here (autoscaling policy, caching strategy, isolation mechanism), name the framework or reference informing it — e.g. the relevant cloud provider's Well-Architected Framework pillar (Reliability, Performance Efficiency) — rather than asserting best practice with no attribution.

7. MERMAID DIAGRAM
   A system architecture diagram is mandatory here — components, data stores, message flows, external integrations, drawn inline now. Name things exactly as you named them in section 1, since other RFCs will reference this diagram's vocabulary.
   This diagram must show something the PRD's own system architecture diagram does not — implementation depth means new STRUCTURE, not richer labels on the same boxes and arrows. A real problem already happened from missing this: a diagram came out with the exact same nodes and edges as the PRD's diagram, just with protocol names and "(Extended)"/"(Built)" tags added to the labels — structurally identical, relabeled, adding no real depth, and it slipped past an automated similarity check that only compared node IDs rather than what the diagram actually showed. Use Mermaid subgraphs to show the deployment boundaries from section 2 — group nodes by where they actually run, e.g. `subgraph "Cloud (Nigeria region)"` containing the components deployed there, with replica counts folded into the node label — so the diagram shows something the PRD's logical data-flow diagram physically could not: where things run and how they're grouped for scaling and failure isolation.
   Node-label safety matters here specifically, since this diagram's node labels often carry a status suffix like "(Extended)" or "(Built)": if a label contains parentheses, wrap the whole label in quotes, e.g. CRM["CRM System (Extended)"] — never CRM[CRM System (Extended)] unquoted. Never write a node as id[(text)] unless a cylinder/database shape is actually intended — that exact bracket-paren pair is reserved shape syntax, not a way to show literal parenthesized text, and combined with other unquoted parenthetical labels it can break the whole diagram's parsing, not just that one node.
   Arrow labels always go in pipes on a single arrow token — `A -->|label| B` — never as a quoted string sitting between two dashes (`A -- "label" --> B` is invalid, on any arrow style, solid, dotted, or thick) and never on a reversed arrow (`A <-- "label" -- B`). A real problem already happened from both at once: a diagram used the quoted-dash form on every single edge, including one written backwards, and the whole diagram failed to render as a result — not just the malformed edges, the entire diagram, since one invalid line breaks the parse for all of it. If unsure, prefer the plain forward form `A -->|label| B` throughout, the same rule DevOps's prompt already follows, and always write the edge from actual source to actual target rather than reversing the statement.

8. STANDARDS GROUNDING
   For at least one of your scalability decisions and at least one of your failure-isolation decisions, name the specific framework you are drawing on — write the literal phrase, for example "per the AWS Well-Architected Framework's Reliability pillar" or "per the AWS Well-Architected Framework's Performance Efficiency pillar," or the equivalent Azure Architecture Center reference if that fits the stack better. Do not just describe good practice and leave it unattributed — name the standard explicitly, the same way the Security RFC names OWASP ASVS sections.

QUALITY STANDARDS:
- Every component named in the PRD's technical architecture section must appear here, either elaborated or explicitly marked "no change from PRD."
- The data-flow trace must be one concrete example end to end, not an abstract description of "data flows between services."
- Scalability claims must cite the PRD's actual stated numbers, never a generic "horizontally scalable" with no target attached.
- At least one scalability decision and one failure-isolation decision must explicitly name the framework informing it (see STANDARDS GROUNDING above) — not just describe the practice.

BE SPECIFIC. BE CONSISTENT WITH THE PRD. NAME THINGS THE SAME WAY EVERY TIME SO OTHER RFCS CAN REFERENCE THEM WITHOUT A TRANSLATION TABLE."""


_SECURITY_PROMPT = """You are a senior security analyst embedded in a very large African MNO, producing the security RFC for a large-scale, regulated system. Carrier-scale MNOs are real targets — treat this as production security work, not a checklist exercise.

YOUR RFC PROCESS:

1. THREAT MODEL
   Use STRIDE (Spoofing, Tampering, Repudiation, Information disclosure, Denial of service, Elevation of privilege) against the actual named components from the PRD's technical architecture (and the system-design RFC's components, if provided to you as context) — never against abstract categories with no component attached.
   Example: "AI Scoring Service (Tampering): if scoring inputs can be manipulated before ingestion, risk scores become falsifiable. Mitigation: signed ingestion payloads, input validation at the message-queue boundary."
   Where a specific vulnerability class applies, name it via its OWASP Top 10 category (e.g. "A03:2021 Injection") rather than describing the risk generically with no attribution.

2. CONTROLS MAPPED TO ONE NAMED STANDARD
   Use OWASP ASVS for application-level controls — cite actual chapter or requirement numbers, not just "follow OWASP." Use NIST CSF functions (Identify/Protect/Detect/Respond/Recover) for organizational-level controls, unless the PRD already names a different standard to follow.

3. ENCRYPTION & KEY MANAGEMENT
   At rest: what's encrypted, what algorithm and strength (AES-256 is the floor for this class of system), where keys live — a KMS or HSM, never in application config. In transit: TLS 1.2 as the floor, prefer 1.3, and this includes internal service-to-service traffic, not only the external-facing edge.

4. AUTH & ACCESS CONTROL
   Authentication mechanism (SSO/AD integration and MFA if the PRD specifies it), authorization model (RBAC roles mapped to the PRD's actual user roles), session management (timeout policy, concurrent-session handling).

5. AUDIT LOGGING
   Every state-changing operation gets logged — this project's established pattern, carry it forward here. Specify what's in each log entry (actor, action, timestamp, before/after state), where logs go, retention period, and tamper-evidence approach.

6. DATA PROTECTION / COUNTRY-SCOPED COMPLIANCE
   If a country is identified (reuse whatever country the BRD/PRD already established — do not re-guess or invent one), call the fetch_data_protection_excerpt tool for that country BEFORE writing this section — at minimum once for "breach notification" and once for "cross-border data transfer". Quote directly from what the tool returns and cite the exact source URL it reports; do not paraphrase from memory even if you recognize the law, since only what the tool actually returns is verified. If the tool returns NOT_FOUND for a topic, say explicitly that citation isn't yet available for that specific point rather than asserting one. If no country is identified at all, say so generically rather than picking one and calling the tool speculatively.

7. INCIDENT RESPONSE
   Detection -> containment -> eradication -> recovery -> post-incident review. Reference the DevOps RFC's monitoring and alerting rather than duplicating it — this section is about the response process, not the detection mechanism itself.

8. MERMAID DIAGRAM (conditional)
   Only include one if the threat model spans several distinct trust boundaries and a diagram would clarify where they sit — a security architecture or trust-boundary diagram. Do not force one in if the system is simple enough that prose covers it clearly.
   If you do include one: an arrow with a label is written `A -->|label| B` — never drop the arrowhead (`A --|label| B` is invalid). If a node label contains parentheses, wrap the whole label in quotes, e.g. CPS["Churn Prediction Service (v2)"].

QUALITY STANDARDS:
- The threat model must reference real component names, never generic categories with nothing attached.
- Every control must map to a specific standard section, not a bare product or framework name with no citation.
- Never state a compliance URL or regulation you have not been given as verified. Saying "not yet available" is correct and expected when that's the truth.

BE SPECIFIC. CITE STANDARDS BY SECTION. NEVER INVENT A COMPLIANCE CITATION."""


_QA_PROMPT = """You are a senior QA engineer embedded in a very large African MNO, producing the QA RFC. You are building a test strategy directly from the PRD's functional and non-functional requirements — every acceptance criterion in that PRD needs a test case attached to it by the time you're done, not a general statement that testing will happen.

YOUR RFC PROCESS:

1. TEST LEVELS
   Unit, integration, end-to-end, load/performance, security (define the pen-test scope, don't run it here), and disaster-recovery/failover drills. Name which components or flows each level actually covers — not a bare list of test-level names. Ground your test-level choices in a named testing standard — reference ISTQB glossary terminology (e.g. call out which ISTQB "test level" or "test type" each one corresponds to) or the ISO/IEC/IEEE 29119 software testing standard — rather than asserting test practice with no attribution.

2. ACCEPTANCE-CRITERIA TRACEABILITY (the core of this RFC — do not shortcut it)
   For every acceptance criterion in the PRD's user stories, name the specific test case that verifies it. This is a traceability matrix, not a promise to test things later.
   Example: "AC: 'Risk Manager receives notification within 5 minutes of assignment' -> TC-042: integration test asserting notification.sent fires within 300 seconds of risk_event.assigned, run against staging under simulated load."

3. NFR TEST COVERAGE (the section most real QA plans quietly skip — do not skip it here)
   Performance: a specific load profile (concurrent users, request rate) tied to the PRD's actual stated targets, not a generic "load testing will be performed." Availability: failover drill cadence and what "pass" means in concrete terms (RTO actually met). Security: state which Security-RFC controls get tested here versus left to a dedicated penetration test.

4. TEST DATA & ENVIRONMENT STRATEGY
   Synthetic data versus anonymized production data, and if production data is used at all, state explicitly how it's protected (this connects to the Security RFC — say so). Environment/production parity gaps and why they exist. Refresh cadence. If the project's per-project Docker sandbox model could plausibly serve as this environment once it exists, note that as an open question for whoever builds that infrastructure — do not assume it is already decided, since it isn't built yet.

5. DEFECT MANAGEMENT
   Severity and priority definitions, an SLA per severity level, and a regression-suite growth policy — every fixed bug gets a regression test added, not just closed.

6. MERMAID DIAGRAM (conditional)
   Only if the test or environment-promotion flow itself is complex enough to need one (e.g. a multi-environment promotion pipeline with several gates) — this is not a default-on diagram the way Software Architect's and DevOps's are.
   If you do include one: an arrow with a label is written `A -->|label| B` — never drop the arrowhead (`A --|label| B` is invalid). If a node label contains parentheses, wrap the whole label in quotes.

QUALITY STANDARDS:
- Every PRD acceptance criterion must map to at least one named test case — no acceptance criterion left untested by the time this RFC is done.
- NFR tests must cite the PRD's actual numeric targets, never a generic "performance testing will be done."
- The test-data strategy must state explicitly whether production data is ever used, and if so, how it's protected.
- Test-level rationale should reference ISTQB or ISO/IEC/IEEE 29119 terminology where practical, not assert practice with no attribution.

BE SPECIFIC. TRACE EVERYTHING BACK TO THE PRD. NO ACCEPTANCE CRITERION LEFT UNTESTED."""


_DEVOPS_PROMPT = """You are a senior DevOps engineer embedded in a very large African MNO, producing the DevOps RFC for a 24x7 carrier-scale system that cannot silently degrade without someone finding out within minutes, not hours.

YOUR RFC PROCESS:

1. CI/CD PIPELINE
   Stages (build -> automated tests -> security scan -> staging deploy -> production deploy), what gates each promotion (which automated checks must pass, where a manual approval is required), and the specific rollback trigger. Where you justify a containerization, orchestration, or pipeline-tooling choice, ground it in a named reference — the CNCF cloud-native landscape/trail map is the standard one to cite for this — rather than asserting practice with no attribution.

2. ENVIRONMENT STRATEGY
   Dev/staging/production, and how config/secrets are managed per environment. If this maps to the project's per-project Docker-sandbox model, note that as an open question for whoever builds that infrastructure — it does not exist yet, so do not assume the mapping is already decided.

3. INFRASTRUCTURE AS CODE
   What is codified (ideally everything), in what tool, how state is managed, and how configuration drift is detected.

4. MONITORING & ALERTING (the section this class of system lives or dies by)
   Cover the 5-layer pattern this project's own reference material already established: infrastructure, application, network, database, service — each with specific metrics and numeric alert thresholds, not "the system will be monitored." Match a 5-minute alert-interval bar unless the PRD states otherwise.
   Example: "Application layer: p95 latency > 200ms sustained for 5 minutes pages on-call; error rate > 1% sustained for 5 minutes pages on-call."

5. DEPLOYMENT STRATEGY
   Blue-green or canary — pick one and justify it for this system's specific risk profile, not as a default choice. State the automated rollback trigger (a specific error-rate or latency threshold, not "if something looks wrong"). Ground the choice in the relevant cloud provider's Well-Architected Framework pillar (Reliability, Operational Excellence) rather than asserting best practice with no attribution.

6. DISASTER RECOVERY
   Explicit RTO and RPO numbers, tied directly to the PRD's actual stated availability target (e.g. 99.9% uptime implies a specific RTO, state what it is and why). Backup frequency and location. Failover test cadence — this must actually be tested periodically, not just documented once.

7. MERMAID DIAGRAM
   A deployment/pipeline architecture diagram is mandatory here — environments, promotion flow, and where monitoring touches each stage, drawn inline now.
   Use `graph TD` (top-down), not `graph LR`, for the pipeline flow. A real problem already happened from this: a left-to-right pipeline with a nine-stage chain rendered as one extremely wide row, and once scaled down to fit the page width in the exported PDF every label was too small to read. Top-down grows the image downward instead, which doesn't compete with page width. If the pipeline genuinely has more than about seven stages in a single unbroken chain, split it into two diagrams (e.g. build-and-test in one, deploy-and-monitor in the other) rather than stretching one diagram across the page — a diagram nobody can read communicates nothing, however correct its contents.
   Syntax care matters here specifically: keep an arrow's style consistent from start to end. A dotted/monitoring-style connection with a label is written `A -.->|label| B` (dotted start, dotted arrowhead, label in pipes) — never mix a dotted start with a solid arrowhead (`A -. "label" --> B` is invalid), and never write a label as a bare quoted string sandwiched between two dot fragments either (`A -. "label" .-> B` is also invalid — the label always goes in pipes on a single `-.->`, never between two separate dots). This same mistake applies to every arrow style, not just dotted — `A -- "label" --> B` (solid) and `A == "label" ==> B` (thick) are exactly as invalid, and so is the reversed form on any style (`A <-- "label" -- B`). If unsure, prefer the plain solid form `A -->|label| B` throughout rather than risk an inconsistent mix, and always write the edge from actual source to actual target rather than reversing the statement.
   A pipe label must open and close on the SAME line: `A -->|label| B`. Never let a label run past the end of a line, and never start a new line with the tail of a label — a real problem already happened from this in another RFC, where one statement got torn across a line break mid-label and the whole diagram failed to render with no way to recover what was intended. Write each edge as one complete line.
   Same care applies to node labels: if a label contains parentheses (e.g. an environment or status annotation), wrap the whole label in quotes, e.g. Prod["Production (blue)"] — an unquoted parenthesis inside a bracketed label is a common cause of the whole diagram failing to render. Never nest a different bracket type inside a node's own shape delimiter either — e.g. Stage(Text [Extra]) mixing round-paren and square-bracket, or Config{["Text"]} mixing curly braces with square brackets — pick exactly one real shape delimiter ([text], (text), {text}, {{text}}, [[text]], or [(text)]) and keep the label plain text inside it.

QUALITY STANDARDS:
- Monitoring must cover all 5 layers with real numeric thresholds attached to each, not a statement that monitoring will happen.
- RTO/RPO must be explicit numbers tied to the PRD's actual availability target, never "minimal downtime."
- Infrastructure as code must name a specific tool or approach, not just assert that IaC will be used.
- Reliability and deployment choices should reference a named framework (CNCF, a cloud provider's Well-Architected Framework) where practical, not assert best practice with no attribution.

BE SPECIFIC. NAME THRESHOLDS. TIE EVERYTHING TO THE PRD'S ACTUAL AVAILABILITY TARGET."""


# ---------------------------------------------------------------------------
# Quality gate checks — one function per role, same "real content, not
# keyword presence" bar ba_skill.py/pe_skill.py already established: every
# gate requires two or more independent signals, not a single keyword hit.
# ---------------------------------------------------------------------------

def _check_ui_ux_gates(markdown: str) -> Dict[str, bool]:
    lines = markdown.split("\n")
    text = markdown.lower()

    user_journeys = (
        any(re.search(r"(journey|flow)", line, re.IGNORECASE) for line in lines) and
        any(re.search(r"(agent|analyst|manager|administrator|customer|user)", line, re.IGNORECASE) for line in lines) and
        any(sym in markdown for sym in ["->", "\u2192"])
    )

    info_architecture = (
        any(re.search(r"(nav|menu|screen|view)", line, re.IGNORECASE) for line in lines) and
        any(re.search(r"\d+\s*(click|screen|step)", line, re.IGNORECASE) for line in lines)
    )

    interaction_states = all(
        _contains_keyword(text, state) for state in ["loading", "empty", "error", "success"]
    )

    accessibility = (
        "wcag" in text and
        bool(re.search(r"\d\.\d\.\d", markdown))
    )

    return {
        "user_journeys_mapped_per_role": user_journeys,
        "information_architecture_defined": info_architecture,
        "interaction_states_covered": interaction_states,
        "accessibility_wcag_cited": accessibility,
        "mermaid_diagram_present": _validate_mermaid(markdown),
    }


def _check_software_architect_gates(markdown: str) -> Dict[str, bool]:
    lines = markdown.split("\n")
    text = markdown.lower()

    component_boundaries = (
        any(re.search(r"(service|component)", line, re.IGNORECASE) for line in lines) and
        any(kw in text for kw in ["responsib", "owns", "manages", "handles", "provides"])
    )

    deployment_topology = any(
        re.search(r"\d+\s*(replica|instance|pod)", line, re.IGNORECASE) for line in lines
    )

    arrow_count = markdown.count("->") + markdown.count("\u2192")
    # Either the literal sync/async wording OR a per-hop latency annotation
    # like (REST API, <200ms) counts as concrete tracing -- a real run
    # showed this gate false-negative on a genuinely complete trace after
    # the DATA FLOW prompt was rewritten to favor "A -> B (protocol,
    # latency) -> C" phrasing over explicit sync/async labels. The content
    # was fully concrete either way; the gate just hadn't been updated
    # alongside the prompt.
    has_sync_async_wording = any(kw in text for kw in ["sync", "async"])
    has_latency_annotation = bool(re.search(r"\(.*\d+\s*(ms|s|sec|second)\b", text))
    data_flow = arrow_count >= 2 and (has_sync_async_wording or has_latency_annotation)

    scalability = (
        "scal" in text and
        bool(re.search(r"\d+\s*(%|x\b|users?|requests?)", markdown, re.IGNORECASE))
    )

    return {
        "component_boundaries_defined": component_boundaries,
        "deployment_topology_specified": deployment_topology,
        "data_flow_traced_concretely": data_flow,
        "scalability_tied_to_prd_targets": scalability,
        "mermaid_diagram_present": _validate_mermaid(markdown),
    }


def _check_security_gates(markdown: str) -> Dict[str, bool]:
    text = markdown.lower()

    stride_words = ["spoof", "tamper", "repudiat", "disclosur", "denial of service", "elevation of privilege"]
    threat_model = (
        any(_contains_keyword(text, w) or w in text for w in stride_words) and
        any(kw in text for kw in ["service", "component"])
    )

    controls_mapped = (
        any(kw in text for kw in ["owasp", "asvs", "nist", "csf"]) and
        bool(re.search(r"(\d+\.\d+|chapter\s*\d+|requirement\s*\d+)", text))
    )

    encryption = (
        ("aes" in text or "encrypt" in text) and
        "tls" in text and
        any(kw in text for kw in ["kms", "hsm", "key management"])
    )

    auth_access = (
        any(kw in text for kw in ["rbac", "role-based"]) and
        any(kw in text for kw in ["mfa", "session"])
    )

    audit_logging = (
        "audit" in text and
        "retention" in text and
        "log" in text
    )

    return {
        "threat_model_references_real_components": threat_model,
        "controls_mapped_to_standard_sections": controls_mapped,
        "encryption_and_key_mgmt_specified": encryption,
        "auth_and_access_control_defined": auth_access,
        "audit_logging_and_retention_defined": audit_logging,
    }


def _check_qa_gates(markdown: str) -> Dict[str, bool]:
    text = markdown.lower()

    level_words = ["unit", "integration", "end-to-end", "e2e", "load", "performance", "disaster recovery", "failover"]
    test_levels = sum(1 for w in level_words if w in text) >= 3

    traceability = (
        bool(re.search(r"tc[\s-]?\d+", text)) and
        bool(re.search(r"acceptance[\s-]?criteri", text))
    )

    nfr_coverage = (
        bool(re.search(r"\d+\s*(ms|%|min|second)", text)) and
        any(kw in text for kw in ["load", "performance"]) and
        any(kw in text for kw in ["availability", "failover"])
    )

    test_data_env = (
        any(kw in text for kw in ["synthetic", "anonymiz"]) and
        any(kw in text for kw in ["staging", "environment"])
    )

    defect_mgmt = (
        any(kw in text for kw in ["severity", "priority"]) and
        "sla" in text
    )

    gates = {
        "test_levels_defined": test_levels,
        "ac_to_test_case_traceability_complete": traceability,
        "nfr_test_coverage_with_real_targets": nfr_coverage,
        "test_data_and_env_strategy_defined": test_data_env,
        "defect_management_process_defined": defect_mgmt,
    }
    return gates


def _check_devops_gates(markdown: str) -> Dict[str, bool]:
    text = markdown.lower()

    pipeline_words = ["build", "test", "staging", "prod", "deploy", "scan"]
    pipeline = (
        any(kw in text for kw in ["ci/cd", "pipeline"]) and
        sum(1 for w in pipeline_words if w in text) >= 3
    )

    layer_words = ["infrastructure", "application", "network", "database", "service"]
    monitoring = (
        sum(1 for w in layer_words if w in text) >= 3 and
        bool(re.search(r"\d+\s*(ms|%|min)", text))
    )

    deployment_strategy = (
        any(kw in text for kw in ["blue-green", "canary"]) and
        "rollback" in text
    )

    dr = (
        "rto" in text and
        "rpo" in text and
        bool(re.search(r"\d+\s*(min|hour)", text))
    )

    return {
        "pipeline_stages_and_gates_defined": pipeline,
        "monitoring_5layer_with_thresholds": monitoring,
        "deployment_strategy_justified": deployment_strategy,
        "dr_rto_rpo_explicit": dr,
        "mermaid_diagram_present": _validate_mermaid(markdown),
    }


_GATE_CHECKERS: Dict[str, Callable[[str], Dict[str, bool]]] = {
    "ui_ux": _check_ui_ux_gates,
    "software_architect": _check_software_architect_gates,
    "security": _check_security_gates,
    "qa": _check_qa_gates,
    "devops": _check_devops_gates,
}

_SYSTEM_PROMPTS: Dict[str, str] = {
    "ui_ux": _UI_UX_PROMPT,
    "software_architect": _SOFTWARE_ARCHITECT_PROMPT,
    "security": _SECURITY_PROMPT,
    "qa": _QA_PROMPT,
    "devops": _DEVOPS_PROMPT,
}


@dataclass
class RoleConfig:
    key: str
    display_name: str
    system_prompt: str
    mermaid_required: bool
    check_gates: Callable[[str], Dict[str, bool]]
    aliases: tuple = field(default_factory=tuple)


ROLE_CONFIGS: Dict[str, RoleConfig] = {
    role: RoleConfig(
        key=role,
        display_name=ROLE_DISPLAY_NAMES[role],
        system_prompt=_SYSTEM_PROMPTS[role],
        mermaid_required=MERMAID_REQUIRED[role],
        check_gates=_GATE_CHECKERS[role],
        aliases=ROLE_ALIASES[role],
    )
    for role in RFC_ROLES
}


class RFCSkill:
    """RFC Skill — turns an approved PRD into one role's RFC. Role-parameterized
    rather than five separate classes; see module docstring for why."""

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")
        self.technical_research_service = TechnicalResearchService()
        # Only used for the Security role's country-scoped data-protection
        # citation — reuses the BA/PE country resolution, does not
        # re-implement it.
        self.research_service = ResearchService()

    def _build_agent(self, role: str) -> Agent:
        config = ROLE_CONFIGS[role]
        # Only the Security role gets the compliance-fetch tool -- it's the
        # only role whose prompt asks for it, and attaching it everywhere
        # would just be an unused capability sitting on 4 agents that never
        # reference it.
        if role == "security":
            # tool_choice="required" forces a tool call on the agent's first
            # turn -- confirmed necessary on a real run: with tool_choice
            # left at its default, gpt-4-turbo simply didn't call the tool
            # and wrote "not explicitly provided through a verified source"
            # on its own initiative instead, even though the prompt already
            # said to call it. This isn't a guess at the fix -- checked the
            # installed SDK's own source (run_internal/tool_execution.py,
            # maybe_reset_tool_choice): once the agent has used a tool,
            # tool_choice is automatically reset to None for every
            # subsequent turn, so this forces exactly the one call needed
            # and doesn't force a repeated-tool-call loop afterward.
            tools = [fetch_data_protection_excerpt]
            model_settings = ModelSettings(tool_choice="required")
        else:
            tools = []
            model_settings = ModelSettings()
        return Agent(
            name=f"{config.display_name} RFC Agent",
            instructions=config.system_prompt,
            model=MODEL,
            tools=tools,
            model_settings=model_settings,
        )

    def _build_user_prompt(
        self,
        role: str,
        prd_markdown: str,
        system_design_context: Optional[str],
        feedback: Optional[str],
        run_count: int,
    ) -> str:
        prompt = f"""APPROVED PRD:
{prd_markdown}
"""
        if system_design_context and role != "software_architect":
            prompt += f"""
SYSTEM-DESIGN RFC (from the Software Architect role, for cross-reference — use its component names rather than inventing your own):
{system_design_context}
"""

        prompt += "\nProduce the complete RFC now.\n"

        if role == "ui_ux":
            prompt += (
                "Include at minimum: user journeys for every role in the PRD, "
                "information architecture with an actual click/screen count, "
                "all 4 interaction states for every primary view, WCAG 2.1 "
                "success-criteria citations, and a Mermaid user-journey diagram "
                "drawn inline now.\n"
            )
        elif role == "software_architect":
            prompt += (
                "Include at minimum: named component boundaries matching the "
                "PRD's technical architecture, deployment topology with concrete "
                "scaling triggers, one concrete end-to-end data-flow trace, "
                "scalability tied to the PRD's actual numbers, and a Mermaid "
                "system architecture diagram drawn inline now.\n"
            )
        elif role == "security":
            prompt += (
                "Include at minimum: a STRIDE threat model against real named "
                "components, controls mapped to OWASP ASVS or NIST CSF with "
                "section numbers, encryption and key-management specifics, "
                "auth/access-control mapped to the PRD's actual roles, audit "
                "logging and retention, and incident response. Do not invent a "
                "compliance citation — if a country's data-protection source "
                "is not verified, say so explicitly.\n"
            )
        elif role == "qa":
            prompt += (
                "Include at minimum: test levels naming which components each "
                "covers, a full acceptance-criteria-to-test-case traceability "
                "matrix covering every AC in the PRD, NFR test coverage with "
                "the PRD's actual numeric targets, test data/environment "
                "strategy, and defect management.\n"
            )
        elif role == "devops":
            prompt += (
                "Include at minimum: CI/CD pipeline stages and gates, "
                "environment strategy, infrastructure as code approach, "
                "5-layer monitoring with numeric thresholds, a justified "
                "deployment strategy with rollback trigger, explicit RTO/RPO "
                "tied to the PRD's availability target, and a Mermaid "
                "deployment/pipeline diagram drawn inline now.\n"
            )

        if feedback and run_count > 1:
            prompt += f"\nREFINEMENT FEEDBACK (Attempt {run_count}):\n{feedback}\n"

        return prompt

    async def _verify_security_data_protection(self, prd_markdown: str) -> Optional[Dict]:
        """Security-only: check whether a verified data-protection citation
        exists for whatever country the PRD already established. Returns a
        small dict for the caller to fold into sources_metadata, or None if
        no country is identified at all (not an error — just nothing to add)."""
        country = self.research_service.detect_country(prd_markdown)
        if not country:
            return None
        verified_urls = get_data_protection_sources(country)
        return {
            "country": country,
            "data_protection_sources_verified": verified_urls,
            "data_protection_citation_available": len(verified_urls) > 0,
        }

    async def generate_rfc(
        self,
        role: str,
        prd_dict: Dict,
        system_design_context: Optional[str] = None,
        clarification_feedback: Optional[str] = None,
        run_count: int = 1,
    ) -> Dict:
        try:
            if role not in ROLE_CONFIGS:
                return {
                    "status": "error",
                    "role": role,
                    "error": f"Unknown RFC role: {role}",
                    "markdown": None,
                    "quality_gates_passed": False,
                }

            if not prd_dict:
                return {
                    "status": "error",
                    "role": role,
                    "error": "PRD dict required as input",
                    "markdown": None,
                    "quality_gates_passed": False,
                }

            config = ROLE_CONFIGS[role]
            document_id = f"RFC-{role.upper()}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

            prd_markdown = prd_dict.get("markdown", "")

            user_prompt = self._build_user_prompt(
                role, prd_markdown, system_design_context, clarification_feedback, run_count
            )

            agent = self._build_agent(role)
            result = await Runner.run(agent, user_prompt)
            markdown = result.final_output

            if not markdown or not isinstance(markdown, str):
                return {
                    "status": "error",
                    "role": role,
                    "error": "Failed to extract RFC content from agent response",
                    "markdown": None,
                    "quality_gates_passed": False,
                }

            # Deterministic punctuation-level cleanup -- see mermaid_validation.py
            # and ba_skill.py's identical wiring for why this runs before gates.
            markdown = sanitize_mermaid_diagrams(markdown)

            # Structural (Layer 1) + prose-consistency (Layer 2) diagram review,
            # same as ba_skill.py/pe_skill.py. Layer 3 (cross-document similarity)
            # only applies to software_architect: it's the one role whose own
            # prompt explicitly says its job is to add implementation depth beyond
            # the PRD, so comparing its diagram against the PRD's own diagram is
            # checking it against its own stated mandate, not an arbitrary rule --
            # a real run showed this RFC's system-architecture diagram came out
            # 100% structurally identical to the PRD's, adding no depth at all.
            compare_against = prd_markdown if role == "software_architect" else None
            diagram_review = await run_full_diagram_review(markdown, compare_against_markdown=compare_against)

            quality_gates = config.check_gates(markdown)
            # RFC's gates_passed below is all(quality_gates.values()) -- unlike
            # BA/PE, this genuinely counts toward the role's pass/fail summary,
            # matching how mermaid_diagram_present is already treated for RFCs.
            quality_gates["diagram_review_ok"] = diagram_review["overall_ok"]

            sources_metadata = await self.technical_research_service.extract_and_verify_sources(
                markdown=markdown,
                role=role,
                id_key="rfc_id",
                id_prefix="RFC",
            )

            if role == "security":
                data_protection_check = await self._verify_security_data_protection(prd_markdown)
                if data_protection_check:
                    sources_metadata["data_protection"] = data_protection_check

            enhanced_markdown = self._add_verified_footnotes(markdown, sources_metadata, role)

            if config.mermaid_required:
                quality_gates["mermaid_diagram_present"] = _validate_mermaid(enhanced_markdown)
            elif "```mermaid" in enhanced_markdown:
                # Included voluntarily even though not required for this role —
                # validate it anyway rather than silently ignoring bad syntax.
                quality_gates["mermaid_diagram_present"] = _validate_mermaid(enhanced_markdown)
            else:
                quality_gates.setdefault("mermaid_diagram_present", True)  # not required, none given — not a failure

            gates_passed = all(quality_gates.values())

            return {
                "status": "success",
                "role": role,
                "document_id": document_id,
                "markdown": enhanced_markdown,
                "structured": _parse_sections(markdown),
                "sources_metadata": sources_metadata,
                "diagram_review": diagram_review,
                "quality_gates": quality_gates,
                "quality_gates_passed": gates_passed,
                "approval_required": True,
                "generated_at": datetime.now().isoformat(),
                "run_count": run_count,
                "sources_verified_count": len(sources_metadata.get("sources_used", [])),
            }

        except Exception as e:
            return {
                "status": "error",
                "role": role,
                "error": str(e),
                "markdown": None,
                "quality_gates_passed": False,
            }

    def _add_verified_footnotes(self, markdown: str, sources_metadata: Dict, role: str) -> str:
        """Same footnote format as ba_skill.py/pe_skill.py, plus a Security-only
        data-protection citation. The data-protection source gets its own
        real, inspectable [DP-n] citation (URL, authority, verified date) —
        kept in a separate subsection rather than folded into the
        engineering-standards numbered list above it, since those are two
        categorically different kinds of source (technical_sources.py's own
        docstring is explicit about this) and merging them would make
        "Total sources verified"/hallucination-risk silently stop meaning
        what it says. Built independently of the `sources` empty-check below
        so the data-protection section still renders correctly even when an
        RFC has zero engineering-standard sources — a bare "available, see
        references above" pointing at nothing was the actual bug here."""
        sources = sources_metadata.get("sources_used", [])

        if not sources:
            references = "\n\n## References\n\nNote: No engineering-standard sources were verified for this RFC. Manual review recommended before approval.\n"
        else:
            references = "\n\n## Verified References\n\n"
            for idx, source in enumerate(sources, 1):
                authority = source.get("authority_level", "unknown").upper()
                confidence = source.get("confidence_level", "unknown").upper()
                accessed = source.get("accessed_at", "N/A")
                claim = source.get("claim", "N/A")
                url = source.get("source_url", "N/A")

                references += f"[{idx}] {claim}\n"
                references += f"- Source: {url}\n"
                references += f"- Authority: {authority} | Confidence: {confidence}\n"
                references += f"- Verified: {accessed}\n\n"

            references += "---\n\nData Integrity Summary\n"
            references += f"- Total sources verified: {len(sources)}\n"
            references += f"- Hallucination risk: {sources_metadata['data_integrity'].get('hallucination_risk', 'unknown')}\n"

        if role == "security" and "data_protection" in sources_metadata:
            dp = sources_metadata["data_protection"]
            verified_urls = dp.get("data_protection_sources_verified") or []
            if dp.get("data_protection_citation_available") and verified_urls:
                references += "\n### Data Protection / Compliance Citation\n\n"
                for idx, url in enumerate(verified_urls, 1):
                    full_url = url if url.startswith("http") else f"https://{url}"
                    references += f"[DP-{idx}] Data protection / privacy law compliance for {dp['country']}\n"
                    references += f"- Source: {full_url}\n"
                    references += "- Authority: HIGH | Confidence: HIGH\n"
                    references += f"- Verified: {datetime.now().isoformat()}\n\n"
                references += f"Data-protection law citation for {dp['country']}: available, see citation above.\n"
            else:
                references += (
                    f"\nData-protection law citation for {dp['country']}: NOT YET VERIFIED in the "
                    f"whitelist — confirm the correct citation before relying on this section.\n"
                )

        return markdown + references


async def generate_rfc(
    role: str,
    prd_dict: Dict,
    system_design_context: Optional[str] = None,
    clarification_feedback: Optional[str] = None,
    run_count: int = 1,
) -> Dict:
    """Generate one role's RFC from an approved PRD."""
    skill = RFCSkill()
    return await skill.generate_rfc(
        role=role,
        prd_dict=prd_dict,
        system_design_context=system_design_context,
        clarification_feedback=clarification_feedback,
        run_count=run_count,
    )
