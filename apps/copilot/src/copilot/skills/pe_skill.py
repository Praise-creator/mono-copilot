"""
Product Engineer Skill - PRD Generation for Enterprise-Scale African MNO Systems.

Takes approved BRD and produces a technically rigorous PRD.
The PE's job is fundamentally different from the BA's — BA answers "what and why",
PE answers "how, at what cost, with what risk, and how do we operate it".

Key design decisions:
- System prompt teaches reasoning, not output format (same philosophy as BA)
- Mermaid diagrams are part of good PE writing at this scale, not a conditional
- Sources: government first (NCC, NCA, CMA, ICASA, NTRA), then industry (GSMA, Gartner, Statista)
- Confidence levels on every claim (HIGH/MEDIUM/LOW) — same hallucination prevention as BA
- Quality gates validate technical depth, not keyword presence
"""

from typing import Optional, Dict
from datetime import datetime
import os
import re
from openai import AsyncOpenAI

from ..services.research_service import ResearchService
from ..services.mermaid_validation import validate_mermaid_diagrams, sanitize_mermaid_diagrams
from ..services.diagram_consistency_service import run_full_diagram_review


# Signal words indicating the PRD's own described architecture actually
# includes a predictive/ML component -- gates the ML Methodology section
# below so it only fires when relevant. This is the same shape of decision
# rfc_skill.py's MERMAID_REQUIRED conditionals already make ("only if the
# threat model spans several trust boundaries") rather than a new pattern:
# a marketing-campaign or network-ops PRD with no ML component should never
# see a section asking about class imbalance or model retraining cadence --
# forcing it in unconditionally would be exactly the kind of one-project
# overfit this codebase's own SRS-genericity discipline already warns
# against.
_ML_SIGNAL_KEYWORDS = (
    "predictive analytic", "machine learning", "ml model", "classifier",
    "classification model", "prediction engine", "scoring model",
    "risk score", "recommendation engine", "ai-driven", "artificial intelligence",
    "neural network", "regression model",
)


def _mentions_ml_component(text: str) -> bool:
    text_lower = text.lower()
    return any(re.search(r"\b" + re.escape(kw) + r"s?\b", text_lower) for kw in _ML_SIGNAL_KEYWORDS)


_ML_METHODOLOGY_INSTRUCTION = """
ML METHODOLOGY & MODEL GOVERNANCE (required -- the BRD/problem statement describes a predictive/ML component):
This PRD's whole premise involves a model making a real decision, so the model itself needs the same rigor as everything else here -- not an architecture box with no substance behind it. Cover, concretely:
- Model framing: binary classification vs. survival/time-to-event analysis, stated with a reason, not just named.
- Feature categories: name real categories (behavioral/RFM signals, usage-trend deltas, support-contact frequency, tenure, etc.), not just "historical data."
- Class imbalance handling: state the actual technique (class weighting, resampling, precision/recall-focused evaluation) -- rare-event prediction always needs one, name it.
- Explainability: state the per-prediction explanation approach (e.g. SHAP or equivalent). This is the first thing a legal/compliance reviewer asks about when a model's output determines who gets a financial incentive and who doesn't.
- Validation approach: temporal holdout, not a random split -- state this explicitly, since a random split leaks future information into training for this kind of time-ordered prediction problem.
- Retraining cadence and drift monitoring: a concrete trigger condition, not "periodically."
- Human-in-the-loop threshold: state the score band (if any) where a human reviews before action is taken automatically.
"""


class PESkill:
    """PE Skill — turns an approved BRD into a technically complete PRD."""

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")
        self.client = AsyncOpenAI(api_key=self.api_key)
        self.model = "gpt-4-turbo"
        self.research_service = ResearchService()

    def _system_prompt(self) -> str:
        return """You are a senior Product Engineer embedded in a very large African MNO (mobile network operator).

You receive an approved Business Requirements Document from the BA team. Your job is to take those requirements and produce a PRD that a backend engineering team can build from directly — no ambiguity, no hand-waving, no "TBD", and absolutely no promises of future diagrams.

The MNOs you work with are large. Not startup large. Carrier large.
- Tens of millions of subscribers
- 1000+ concurrent internal users (agents, analysts, ops)
- 100M+ customer data points under management
- Systems that cannot go down: IVR, billing, provisioning, CRM
- Regulatory environments with real teeth: NCC in Nigeria, NCA in Ghana, CA in Kenya, ICASA in South Africa, TRA in Egypt
- Legacy infrastructure that will not be replaced — it must be integrated

This means your PRD carries weight that a startup PRD does not. When you write "< 200ms p95", that number gets put into an SLA. When you write "fallback to cached data", an engineer designs a cache invalidation strategy around it. Write accordingly.

HOW TO THINK THROUGH A PRD:

What are we actually building?
Break the requirements into real technical components. Not "an AI recommendation system" but "a scoring service that ingests customer features from a feature store, runs a gradient-boosted model, and returns an offer recommendation via REST in under 2 seconds." Name the components. Describe their boundaries. Decide what gets built vs. bought vs. extended.

How do the pieces talk to each other?
Every integration between systems is a potential failure point. Document each one: which system calls which, what protocol, what payload, what the latency SLA is, and what happens when it fails. "The CRM is unavailable" is not an edge case at MNO scale, it is a Tuesday. Model the failure explicitly — detection method, what the user sees, what the system does, when ops gets paged.

DRAW THE DIAGRAMS NOW. Do not say "a diagram will be provided." Do not say "see attached." Write the actual Mermaid code blocks inline, right here, in this document. Every PRD at this scale needs EXACTLY two diagrams, no more:
- ONE system architecture diagram showing all components and their connections -- this is the FIRST technical, system-level diagram in the whole pipeline. The BRD you were handed draws only a business-process/customer-journey diagram with business actors (Subscriber, CSR, Care Team) -- introducing real internal component names (a CDP, an analytics engine, whatever the actual backend systems are) for the first time is your job here, not a restatement of anything already drawn. A real problem already happened from treating "integration map" as a second diagram: it produced two nearly-identical Mermaid blocks in the same PRD, one styled with colors and one plain, both showing the same architecture. "Integration map" is a section of TEXT (protocol, latency SLA, failure handling per connection, in prose or a table) sitting next to the ONE diagram, not a second diagram.
- ONE monitoring/observability diagram showing metrics flow through to alerting.

Use ```mermaid blocks. Use real component names. Show actual data flows with arrows.

Syntax care matters here specifically, since an inconsistent arrow breaks the whole diagram's rendering, not just one edge: an arrow with a label is written `A -->|label| B` (solid arrowhead, label in pipes) — never drop the arrowhead partway through a diagram (`A --|label| B` is invalid and will fail to render, even if earlier lines in the same diagram used the correct form). If a label contains parentheses, wrap the whole node label in quotes, e.g. CRM["CRM System (Extended)"] — an unquoted parenthesis inside a bracketed label is a common cause of the whole diagram failing to render.

What are the non-negotiable technical properties?
State exact numbers. Not "highly available" — "99.95% uptime, RTO 5 minutes, RPO zero for customer financial records." Not "fast" — "< 200ms p95 for the recommendation API under 1000 concurrent sessions." Every number must trace to a source or be marked with its confidence level: CONFIDENCE: HIGH (verified source), CONFIDENCE: MEDIUM (industry norm), CONFIDENCE: LOW (assumption).

How does data flow and where does it live?
Where does customer data originate? Where is it stored? What is the consistency model? For African MNOs specifically — where must data physically reside? NCC requires customer data to remain in Nigeria. This affects every cloud architecture decision.

How do we know it is working?
What metrics does ops watch? What triggers an alert? Who gets paged and when? Draw the observability Mermaid diagram.

How do we ship it safely?
Canary, blue-green, or rolling — pick one and justify it. State the specific error rate or latency threshold that triggers automatic rollback. State whether database migrations are reversible.

What will slow us down?
Name the real risks with real mitigations. "CRM API extensions take 6+ weeks historically — if not ready by Week 4, agent portal falls back to manual lookup and latency target is missed."

SOURCES:
Government sources first: NCC (ncc.gov.ng), NCA (nca.org.gh), CA (ca.go.ke), ICASA (icasa.org.za), TRA (tra.gov.eg).
Match the regulator to the ACTUAL country in the approved BRD — a Ghana project cites NCA, not NCC. Do not default to NCC/Nigeria out of habit.
If NO country or market is stated anywhere in the BRD or problem statement, do NOT invent one — including in the Data Residency section. Write it generically instead (e.g. "jurisdiction not specified — confirm target market before finalizing data residency requirements") rather than asserting a specific country's compliance requirement as CONFIDENCE: HIGH.
Industry benchmarks: GSMA Intelligence, Gartner, Statista, Forrester.
Mark every estimate: CONFIDENCE: HIGH / MEDIUM / LOW.
Do not invent data. If you do not know, say so and mark it LOW confidence."""

    async def generate_prd(
        self,
        brd_dict: Dict,
        clarification_feedback: Optional[str] = None,
        run_count: int = 1
    ) -> Dict:
        """Generate PRD from approved BRD."""

        try:
            if not brd_dict:
                return {
                    "status": "error",
                    "document_id": None,
                    "error": "BRD dict required as input",
                    "markdown": None,
                    "quality_gates_passed": False
                }

            document_id = f"PRD-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

            brd_markdown = brd_dict.get("markdown", "")
            segment = brd_dict.get("segment", "postpaid_consumer")
            problem_statement = brd_dict.get("problem_statement", "")

            user_prompt = self._build_user_prompt(
                brd_markdown,
                segment,
                problem_statement,
                clarification_feedback,
                run_count
            )

            response = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=4096,
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": user_prompt}
                ]
            )

            markdown = self._extract_markdown_from_response(response)

            if not markdown:
                return {
                    "status": "error",
                    "document_id": None,
                    "error": "Failed to extract PRD content from response",
                    "markdown": None,
                    "quality_gates_passed": False
                }

            # Deterministic punctuation-level cleanup -- see mermaid_validation.py
            # and ba_skill.py's identical wiring for why this runs before gates.
            markdown = sanitize_mermaid_diagrams(markdown)

            # Structural (Layer 1) + prose-consistency (Layer 2) diagram review --
            # see diagram_consistency_service.py and ba_skill.py's identical wiring.
            # This is exactly the layer that catches the real bug ba_skill.py's own
            # sanitizer can't: a PRD diagram merging "REST API" and "SMPP" into one
            # shared edge label when the prose two lines up says they're different.
            # Also passes the BRD as Layer 3's comparison target -- a real run
            # showed PE's own system architecture diagram come out as a
            # character-for-character copy of BA's diagram, since the BRD (with
            # its diagram already drawn) sits right there in PE's own input and
            # nothing was checking whether PE's diagram was actually new.
            diagram_review = await run_full_diagram_review(markdown, compare_against_markdown=brd_markdown)

            quality_gates = self._check_quality_gates(markdown)
            # Informational, not mandatory -- same treatment as mermaid_diagrams below.
            quality_gates["diagram_review_ok"] = diagram_review["overall_ok"]

            sources_metadata = await self.research_service.extract_and_verify_sources(
                markdown=markdown,
                segment=segment,
                problem_statement=problem_statement,
                id_key="prd_id",
                id_prefix="PRD",
            )

            enhanced_markdown = self._add_verified_footnotes(markdown, sources_metadata)

            quality_gates["mermaid_diagrams"] = self._validate_mermaid(enhanced_markdown)

            mandatory_gates = [
                quality_gates.get("integration_architecture", False),
                quality_gates.get("exception_management", False),
                quality_gates.get("nfrs_with_numbers", False),
                quality_gates.get("compliance_referenced", False),
            ]
            gates_passed = all(mandatory_gates)

            return {
                "status": "success",
                "document_id": document_id,
                "brd_reference": brd_dict.get("document_id"),
                "markdown": enhanced_markdown,
                "structured": self._parse_sections(markdown),
                "sources_metadata": sources_metadata,
                "diagram_review": diagram_review,
                "quality_gates": quality_gates,
                "quality_gates_passed": gates_passed,
                "approval_required": True,
                "generated_at": datetime.now().isoformat(),
                "run_count": run_count,
                "sources_verified_count": len(sources_metadata.get("sources_used", []))
            }

        except Exception as e:
            return {
                "status": "error",
                "document_id": None,
                "error": str(e),
                "markdown": None,
                "quality_gates_passed": False
            }

    def _build_user_prompt(
        self,
        brd_markdown: str,
        segment: str,
        problem_statement: str,
        feedback: Optional[str],
        run_count: int
    ) -> str:
        prompt = f"""SEGMENT: {segment}

APPROVED BRD:
{brd_markdown}

ORIGINAL PROBLEM STATEMENT:
{problem_statement}

Produce the complete PRD now.

Important: draw the Mermaid diagrams inline in this document — do not reference them as future deliverables.

Include at minimum:
- Component breakdown (what is built, bought, extended)
- Integration map, as TEXT (not a second diagram): for each system connection, name the protocol, latency SLA, and exact failure handling
- ONE Mermaid system architecture diagram (draw it now) -- the pipeline's first technical diagram, introducing real component names for the first time
- ONE Mermaid observability diagram (draw it now)
- Failure scenarios: for each critical dependency, state detection method, user impact, system recovery action, and escalation path
- NFRs with exact numbers: uptime percentage, RTO, RPO, p95 latency, max concurrent users
- Data residency: where data lives, how that is enforced technically per NCC or relevant regulator
- Deployment strategy with specific rollback trigger criteria
- Technical risks with named mitigations and timeline impact
- Source or confidence level for every number stated
"""

        if feedback and run_count > 1:
            prompt += f"\nREFINEMENT FEEDBACK (Attempt {run_count}):\n{feedback}\n"

        if _mentions_ml_component(brd_markdown + " " + problem_statement):
            prompt += _ML_METHODOLOGY_INSTRUCTION

        return prompt

    def _extract_markdown_from_response(self, response) -> Optional[str]:
        if hasattr(response, 'choices') and len(response.choices) > 0:
            choice = response.choices[0]
            if hasattr(choice, 'message') and hasattr(choice.message, 'content'):
                return choice.message.content
        return None

    def _check_quality_gates(self, markdown: str) -> Dict[str, bool]:
        """
        Validate technical depth of the PRD.
        Gates check for real content, not exact phrasing.
        """

        lines = markdown.split('\n')

        # Integration: protocol named + latency number + any failure handling
        integration = (
            any(re.search(r'(https|rest|grpc|graphql|kafka|websocket|api call|http)', line, re.IGNORECASE) for line in lines) and
            any(re.search(r'\d+\s*(ms|milliseconds?|seconds?)', line, re.IGNORECASE) for line in lines) and
            any(re.search(r'(fallback|retry|timeout|failure handling|if unavailable|cached)', line, re.IGNORECASE) for line in lines)
        )

        # Exception management: at least one failure scenario documented with what happens
        exception = (
            any(re.search(r'(unavailable|timeout|failure|goes down|degraded|outage)', line, re.IGNORECASE) for line in lines) and
            any(re.search(r'(fallback|cached|manual|default|backup)', line, re.IGNORECASE) for line in lines) and
            any(re.search(r'(alert|escalat|ops|paged?|notify|monitor|incident)', line, re.IGNORECASE) for line in lines)
        )

        # NFRs: uptime number + latency + either RTO/RPO or recovery mentioned
        nfrs_with_numbers = (
            any(re.search(r'99\.\d+\s*%|uptime.*\d+|availability.*\d+', line, re.IGNORECASE) for line in lines) and
            any(re.search(r'(p95|p99|\d+\s*ms|latency.*\d+|\d+.*latency)', line, re.IGNORECASE) for line in lines) and
            any(re.search(r'(rto|rpo|recovery time|recovery point|rollback)', line, re.IGNORECASE) for line in lines)
        )

        # Compliance: any real African regulator mentioned
        compliance = any(
            re.search(r'(ncc|nca|cma|icasa|ntra|data residency|on.prem|in.country|nigerian border)', line, re.IGNORECASE)
            for line in lines
        )

        mermaid = "```mermaid" in markdown

        return {
            "integration_architecture": integration,
            "exception_management": exception,
            "nfrs_with_numbers": nfrs_with_numbers,
            "compliance_referenced": compliance,
            "mermaid_diagrams": mermaid
        }

    def _validate_mermaid(self, markdown: str) -> bool:
        """Validate mermaid blocks have real content and no known-bad syntax
        pattern -- shared logic, see mermaid_validation.py for why this used
        to be three separate weaker copies."""
        return validate_mermaid_diagrams(markdown)

    def _add_verified_footnotes(self, markdown: str, sources_metadata: Dict) -> str:
        """Add source footnotes. Mirrors ba_skill exactly."""

        sources = sources_metadata.get("sources_used", [])

        if not sources:
            return markdown + "\n\n## References\n\nNote: No sources were verified for this PRD. Manual review recommended before approval.\n"

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
            references += f"- Verified: {accessed}\n"
            references += f"- Type: {source.get('source_type', 'N/A')}\n\n"

        references += "---\n\nData Integrity Summary\n"
        references += f"- Total sources verified: {len(sources)}\n"
        references += f"- Hallucination risk: {sources_metadata['data_integrity'].get('hallucination_risk', 'unknown')}\n"
        references += f"- Manual review recommended: {sources_metadata['data_integrity'].get('manual_review_recommended', True)}\n"

        return markdown + references

    def _parse_sections(self, markdown: str) -> Dict:
        """Parse PRD markdown into structured sections."""

        sections = {}
        current_section = None
        content = []

        for line in markdown.split('\n'):
            if line.startswith('## '):
                if current_section:
                    sections[current_section] = '\n'.join(content).strip()
                current_section = line.replace('## ', '').strip()
                content = []
            elif current_section:
                content.append(line)

        if current_section:
            sections[current_section] = '\n'.join(content).strip()

        return sections


async def generate_prd(
    brd_dict: Dict,
    clarification_feedback: Optional[str] = None,
    run_count: int = 1
) -> Dict:
    """Generate technical PRD from approved BRD."""
    skill = PESkill()
    return await skill.generate_prd(
        brd_dict=brd_dict,
        clarification_feedback=clarification_feedback,
        run_count=run_count
    )
