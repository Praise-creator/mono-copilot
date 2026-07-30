"""
Business Analyst Skill - BRD Generation with Web Search + Source Verification + Smart Mermaid Diagrams.

Implements real web search for regulatory compliance and market data.
Uses ResearchService for source verification against authorized whitelist.
Generates Mermaid diagrams when problem involves multiple integrations or stakeholders.

Specific process per meeting notes:
1. Analyze CURRENT PROCESS FLOW (customer journey, stakeholder activities, system logs)
2. Identify BOTTLENECKS and pain points
3. Design PROPOSED PROCESS FLOW (what changes, who does what)
4. Break down USE CASES (technical + business perspectives)
5. Define INTEGRATION ARCHITECTURE (system A ↔ system B, protocols, APIs)
6. Define EXCEPTION MANAGEMENT (failure scenarios, error handling, recovery)
7. Define BUSINESS RULES (validation, authorization, calculation rules)
8. Generate MERMAID DIAGRAMS when problem has >1 integration or >2 stakeholders
"""

from typing import Optional, Dict, List
from datetime import datetime
import json
from pathlib import Path
import os
import re
from openai import AsyncOpenAI

from ..services.research_service import ResearchService


class BASkill:
    """BA Skill - Process flow analysis with web search and source verification."""
    
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")
        self.client = AsyncOpenAI(api_key=self.api_key)
        self.model = "gpt-4-turbo"
        self.research_service = ResearchService()
        self.max_search_attempts = 3
    
    def _system_prompt(self) -> str:
        return """You are a Business Analyst for enterprise MNO systems (Nigeria, Ghana, Kenya, South Africa, Egypt).

YOUR BA PROCESS:

1. ANALYZE CURRENT PROCESS FLOW
   What happens today?
   - Customer journey: Entry → interactions → resolution
   - Stakeholder activities: What each person/system does
   - Bottlenecks: Where does friction occur? [MUST be quantified: "45 sec wait", "15% abandon rate"]
   Example: "Outbound upsell: customer call → IVR → agent wait (45s avg) → recommendation → acceptance"

2. DESIGN PROPOSED PROCESS FLOW
   What changes with this solution?
   - Automated activities, human activities, system changes
   - Expected improvements: "AI pre-analysis → agent sees recommendation → 20s decision time → 5% abandon"

3. USE CASES (Business + Technical)
   Business: "As [actor], I want [capability], so that [outcome]"
   Technical: "System A calls System B → data exchange → result"

4. INTEGRATION ARCHITECTURE (CRITICAL)
   For each integration, specify:
   - Source system (CRM, IVR, AI Engine, etc.)
   - Target system
   - Protocol (REST API, message queue, real-time sync)
   - Latency requirement (< X seconds)
   - Data flow direction and content
   Example: "CRM → AI Engine: REST API, customer data request, < 2 second latency"

5. EXCEPTION MANAGEMENT (CRITICAL FOR LARGE-SCALE MNO)
   For each failure scenario, document:
   - Detection method (e.g., "Connection timeout > 3 seconds")
   - User impact (what customer/agent sees)
   - Recovery action (e.g., "Show cached data, retry 3x")
   - System action (e.g., "Log incident, use fallback")
   - Support action (e.g., "Alert ops team")

6. BUSINESS RULES
   - Validation: [specific conditions]
   - Authorization: [who can do what]
   - Calculation: [formulas]
   - Retention: [compliance requirements]
   - Escalation: [when to escalate]

7. MERMAID DIAGRAMS
   When the problem involves more than one system integration or more than two stakeholders,
   draw a Mermaid diagram inline in the document. Do not reference it as a future deliverable.
   Draw it now, as part of the BRD.

QUALITY STANDARDS FOR LARGE-SCALE MNO:
- All bottlenecks MUST include metrics (seconds, percentages, volumes)
- All integrations MUST specify system names, protocols, and latencies
- All exceptions MUST have detection method, impact, recovery, and support action
- All business rules MUST be testable/enforceable
- All regulatory references MUST be to real government sources (NCC, NCA, CMA, ICASA, NTRA)
- All market data MUST cite GSMA, Statista, or industry analysts

BE SPECIFIC. BE MEASURABLE. BE IMPLEMENTABLE. BE VERIFIED."""
    
    async def generate_brd(
        self,
        problem_statement: str,
        segment: str,
        context: Optional[Dict] = None,
        clarification_feedback: Optional[str] = None,
        run_count: int = 1
    ) -> Dict:
        try:
            document_id = f"BRD-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            
            user_prompt = self._build_user_prompt(
                problem_statement, segment, context, clarification_feedback, run_count
            )
            
            response = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=4000,
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
                    "error": "Failed to extract BRD content from response",
                    "markdown": None,
                    "quality_gates_passed": False
                }
            
            needs_mermaid = self._should_generate_mermaid(problem_statement, context, markdown)
            quality_gates = self._check_quality_gates(markdown, context, needs_mermaid)
            
            sources_metadata = await self._extract_and_verify_sources(
                markdown, segment, problem_statement
            )
            
            enhanced_markdown = self._add_verified_footnotes(markdown, sources_metadata)
            
            if needs_mermaid and "```mermaid" in enhanced_markdown:
                quality_gates["mermaid_diagrams"] = self._validate_mermaid_syntax(enhanced_markdown)
            else:
                quality_gates["mermaid_diagrams"] = not needs_mermaid

            Path("projects").mkdir(exist_ok=True)
            brd_path = Path("projects") / "brd.md"
            brd_path.write_text(enhanced_markdown)
            
            sources_path = Path("projects") / "sources.json"
            sources_path.write_text(json.dumps(sources_metadata, indent=2, default=str))
            
            mandatory_gates = [
                quality_gates.get("process_flow_analysis", False),
                quality_gates.get("integration_architecture", False),
                quality_gates.get("exception_management", False),
                quality_gates.get("business_rules", False)
            ]
            gates_passed = all(mandatory_gates)
            
            return {
                "status": "success",
                "document_id": document_id,
                "markdown": enhanced_markdown,
                "structured": self._parse_sections(markdown),
                "sources_metadata": sources_metadata,
                "quality_gates": quality_gates,
                "quality_gates_passed": gates_passed,
                "approval_required": True,
                "generated_at": datetime.now().isoformat(),
                "run_count": run_count,
                "file_path": str(brd_path),
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
        problem_statement: str,
        segment: str,
        context: Optional[Dict],
        feedback: Optional[str],
        run_count: int
    ) -> str:
        prompt = f"""SEGMENT: {segment}

PROCESS FLOW PROBLEM:
{problem_statement}
"""
        
        if context:
            prompt += "\nCONTEXT:\n"
            if "current_process" in context:
                prompt += f"Current Process: {context['current_process']}\n"
            if "bottleneck" in context:
                prompt += f"Main Bottleneck: {context['bottleneck']}\n"
            if "systems_involved" in context:
                prompt += f"Systems Involved: {', '.join(context['systems_involved'])}\n"
            if "target_latency" in context:
                prompt += f"Target Performance: {context['target_latency']}\n"
            if "regulatory_context" in context:
                prompt += f"Regulatory Context: {context['regulatory_context']}\n"
        
        if feedback and run_count > 1:
            prompt += f"\nREFINEMENT FEEDBACK (Attempt {run_count}):\n{feedback}\n"
        
        prompt += """
INSTRUCTIONS:
1. Use web search for regulatory requirements (NCC, NCA, CMA, ICASA, NTRA)
2. Use web search for market data (GSMA Intelligence, Statista)
3. Generate comprehensive BRD with:
   - Current & proposed process flows (with quantified bottlenecks)
   - Business & technical use cases
   - Integration architecture (all systems, protocols, latencies)
   - Exception management (detection, impact, recovery, support actions)
   - Business rules (validation, authorization, calculation, retention, escalation)
4. This problem involves multiple system integrations — draw a Mermaid process flow diagram inline now. Do not reference it as a future deliverable.
5. Cite all sources clearly (government bodies, industry analysts)
6. All metrics MUST be specific (not "fast", but "< 2 seconds")
7. All regulations MUST be real (not hypothetical)
"""
        
        return prompt
    
    def _extract_markdown_from_response(self, response) -> Optional[str]:
        if hasattr(response, 'choices') and len(response.choices) > 0:
            choice = response.choices[0]
            if hasattr(choice, 'message') and hasattr(choice.message, 'content'):
                return choice.message.content
        return None
    
    def _should_generate_mermaid(
        self,
        problem_statement: str,
        context: Optional[Dict],
        markdown: str
    ) -> bool:
        text = (problem_statement + " " + markdown).lower()
        
        integration_keywords = ["api", "integration", "system", "crm", "ivr", "database", "queue", "sync", "protocol"]
        integration_count = sum(1 for kw in integration_keywords if kw in text)
        
        stakeholder_keywords = ["customer", "agent", "system", "operator", "admin", "manager"]
        stakeholder_count = sum(1 for kw in stakeholder_keywords if kw in text)
        
        exception_keywords = ["exception", "failure", "timeout", "error", "recovery", "fallback", "retry"]
        exception_count = sum(1 for kw in exception_keywords if kw in text)
        
        if context and "systems_involved" in context:
            if len(context["systems_involved"]) > 1:
                return True
        
        return (
            integration_count >= 2 or
            stakeholder_count >= 2 or
            exception_count >= 2 or
            "workflow" in text or
            ("process" in text and "flow" in text)
        )
    
    def _check_quality_gates(
        self,
        markdown: str,
        context: Optional[Dict],
        needs_mermaid: bool
    ) -> Dict[str, bool]:
        text = markdown.lower()
        lines = markdown.split('\n')
        
        process_flow = (
            ("bottleneck" in text or "current process" in text or "customer journey" in text) and
            any(re.search(r'\d+\s*(sec|second|minute|hour|%|percent|ms)', line, re.IGNORECASE) for line in lines)
        )
        
        integration = (
            ("api" in text or "integration" in text or "system" in text) and
            any(re.search(r'(rest|graphql|message|queue|sync|protocol|https|websocket)', line, re.IGNORECASE) for line in lines)
        )
        
        exception = (
            ("exception" in text or "failure" in text or "error" in text or "unavailable" in text) and
            any(re.search(r'(detection|impact|recovery|action|fallback|retry|alert|escalat)', line, re.IGNORECASE) for line in lines)
        )
        
        rules = (
            ("rule" in text or "validation" in text or "authorization" in text or "must" in text) and
            any(re.search(r'(must|should|can only|required|approval|condition|only)', line, re.IGNORECASE) for line in lines)
        )
        
        mermaid = not needs_mermaid or "```mermaid" in markdown
        
        return {
            "process_flow_analysis": process_flow,
            "integration_architecture": integration,
            "exception_management": exception,
            "business_rules": rules,
            "mermaid_diagrams": mermaid
        }
    
    async def _extract_and_verify_sources(
        self,
        markdown: str,
        segment: str,
        problem_statement: str
    ) -> Dict:
        sources_used = []
        
        regulatory_keywords = ["ncc", "nca", "cma", "icasa", "ntra", "compliance", "regulation", "requirement"]
        market_keywords = ["gsma", "statista", "gartner", "market", "arpu", "churn", "coverage"]
        
        text_lower = markdown.lower()
        problem_lower = problem_statement.lower()
        
        for keyword in regulatory_keywords + market_keywords:
            if keyword in text_lower or keyword in problem_lower:
                search_result = await self.research_service.search_and_verify(keyword, segment)
                if search_result.get("verified_sources"):
                    for source in search_result["verified_sources"]:
                        sources_used.append(source)
        
        sentences = re.split(r'(?<=[.!?])\s+', markdown)
        for sentence in sentences[:10]:
            if any(kw in sentence.lower() for kw in regulatory_keywords + market_keywords):
                search_result = await self.research_service.search_and_verify(sentence, segment)
                if search_result.get("verified_sources"):
                    for source in search_result["verified_sources"]:
                        if source not in sources_used:
                            sources_used.append(source)
        
        sources_metadata = {
            "brd_id": f"BRD-{datetime.now().strftime('%Y%m%d')}",
            "project_name": segment,
            "generated_at": datetime.now().isoformat(),
            "sources_used": sources_used,
            "search_statistics": {
                "total_searches": len(regulatory_keywords + market_keywords),
                "sources_verified": len(sources_used),
                "verification_coverage": "high" if len(sources_used) >= 2 else "medium" if len(sources_used) == 1 else "low"
            },
            "data_integrity": {
                "all_sources_verified": len(sources_used) >= 2,
                "hallucination_risk": "low" if len(sources_used) >= 2 else "medium" if len(sources_used) == 1 else "high",
                "unresolved_conflicts": 0,
                "manual_review_recommended": len(sources_used) == 0
            }
        }
        
        return sources_metadata
    
    def _add_verified_footnotes(self, markdown: str, sources_metadata: Dict) -> str:
        sources = sources_metadata.get("sources_used", [])
        
        if not sources:
            return markdown + "\n\n## References\n\nNote: No sources were verified for this BRD. Manual review recommended before approval.\n"
        
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
    
    def _validate_mermaid_syntax(self, markdown: str) -> bool:
        mermaid_blocks = re.findall(r'```mermaid\n(.*?)\n```', markdown, re.DOTALL)
        
        if not mermaid_blocks:
            return False
        
        for block in mermaid_blocks:
            if not any(kw in block.lower() for kw in ["graph", "flowchart", "sequencediagram", "classdiagram", "statediagram"]):
                return False
            if not ("->" in block or "-->" in block or ":" in block):
                return False
        
        return True
    
    def _parse_sections(self, markdown: str) -> Dict:
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


async def generate_brd(
    problem_statement: str,
    segment: str,
    context: Optional[Dict] = None,
    clarification_feedback: Optional[str] = None,
    run_count: int = 1
) -> Dict:
    """Generate process flow BRD with web search, source verification, and Mermaid diagrams."""
    skill = BASkill()
    return await skill.generate_brd(
        problem_statement=problem_statement,
        segment=segment,
        context=context,
        clarification_feedback=clarification_feedback,
        run_count=run_count
    )
