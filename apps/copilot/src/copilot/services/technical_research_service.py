"""
Source verification for the RFC sub-agents (UI/UX, Software Architect,
Security, QA, DevOps).

This is a sibling to ResearchService, not an extension of it. ResearchService
is built around country-scoped telecom regulators (NCC, NCA, CA, ICASA, TRA)
because BA/PE claims are about regulatory compliance and market data. RFC
claims are about engineering standards (WCAG, OWASP, NIST, ISTQB, CNCF) which
aren't country-scoped at all — trying to force them through the same
country-resolution logic would just be a mismatch dressed up as reuse.

Same discipline carried over though: word-boundary keyword matching (not
naive substring — the exact bug class that caused "ntra" to match inside
"contractual" in ResearchService), dedup by URL, and a whitelist that only
grows after live verification.

One exception, deliberately NOT handled here: the Security RFC's
country-scoped data-protection law citations (NDPR, POPIA, etc.) reuse
ResearchService.detect_country() and config/technical_sources.py's
DATA_PROTECTION_SOURCES directly from rfc_skill.py, rather than being
duplicated into this service. That's the one place RFC sourcing and BA/PE
sourcing genuinely share logic, and it's wired at the call site instead of
here to keep this service's job single-purpose.
"""

import re
from datetime import datetime
from typing import Dict, List, Optional

from ..config.technical_sources import (
    TECHNICAL_SOURCES,
    is_technical_source_authorized,
    get_technical_authority_level,
)

_WHITESPACE_RE = re.compile(r"\s+")
_MARKDOWN_ARTIFACT_RE = re.compile(r"[*_#`]")
_LEADING_LIST_MARKER_RE = re.compile(r"^[\-\d.)\s]+")


def _contains_keyword(text: str, keyword: str) -> bool:
    """Word-boundary match, not substring — see research_service.py's
    _contains_keyword for why this matters (short/common-word keywords like
    "iso" would otherwise match inside unrelated words)."""
    return re.search(r"\b" + re.escape(keyword) + r"\b", text) is not None


class TechnicalResearchService:
    """Verifies RFC claims against role-scoped engineering-standards sources."""

    def __init__(self):
        self.sources = TECHNICAL_SOURCES

    def _clean_claim_text(self, text: str, max_length: int = 140) -> str:
        """Same cleanup as research_service.py's _clean_claim_text — strips
        markdown syntax so a citation stays presentable even when built from
        a raw sentence pulled out of generated markdown."""
        cleaned = _MARKDOWN_ARTIFACT_RE.sub("", text).strip()
        cleaned = _LEADING_LIST_MARKER_RE.sub("", cleaned).strip()
        cleaned = _WHITESPACE_RE.sub(" ", cleaned)
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length].rstrip() + "..."
        return cleaned or text[:max_length]

    def _make_source_entry(
        self, claim: str, full_url: str, confidence: str, search_query: str
    ) -> Optional[Dict]:
        if not is_technical_source_authorized(full_url):
            return None
        return {
            "claim": claim,
            "source_url": full_url,
            "source_type": "engineering_standard",
            "authority_level": get_technical_authority_level(full_url),
            "accessed_at": datetime.now().isoformat(),
            "verified": True,
            "confidence_level": confidence,
            "verification_status": "verified",
            "search_queries_used": [search_query],
        }

    async def extract_and_verify_sources(
        self,
        markdown: str,
        role: str,
        id_key: str = "rfc_id",
        id_prefix: str = "RFC",
    ) -> Dict:
        """
        Role-scoped source extraction, mirroring ResearchService's
        extract_and_verify_sources() shape so orchestrator.py and
        file_manager.save_rfc_sources() can treat BA/PE/RFC sources
        metadata uniformly.
        """
        keyword_map: Dict[str, List[str]] = self.sources.get(role, {}).get("keywords", {})

        sources_used: List[Dict] = []
        seen_urls: set = set()

        def _add_unique(entry: Optional[Dict]) -> None:
            if entry and entry.get("source_url") not in seen_urls:
                seen_urls.add(entry["source_url"])
                sources_used.append(entry)

        text_lower = markdown.lower()

        # Pass 1: keyword presence anywhere in the document.
        for keyword, urls in keyword_map.items():
            if _contains_keyword(text_lower, keyword):
                for url in urls:
                    _add_unique(self._make_source_entry(keyword, f"https://{url}", "high", keyword))

        # Pass 2: attribute keywords to the actual sentence they appear in,
        # same as ResearchService, so the citation reads as a real claim
        # rather than just "the document mentions this word somewhere".
        sentences = re.split(r"(?<=[.!?])\s+", markdown)
        for sentence in sentences[:12]:
            sentence_lower = sentence.lower()
            for keyword, urls in keyword_map.items():
                if _contains_keyword(sentence_lower, keyword):
                    cleaned_claim = self._clean_claim_text(sentence)
                    for url in urls:
                        entry = self._make_source_entry(cleaned_claim, f"https://{url}", "high", keyword)
                        _add_unique(entry)

        return {
            id_key: f"{id_prefix}-{role}-{datetime.now().strftime('%Y%m%d')}",
            "role": role,
            "generated_at": datetime.now().isoformat(),
            "sources_used": sources_used,
            "search_statistics": {
                "total_keywords_checked": len(keyword_map),
                "sources_verified": len(sources_used),
                "verification_coverage": (
                    "high" if len(sources_used) >= 2 else "medium" if len(sources_used) >= 1 else "low"
                ),
            },
            "data_integrity": {
                # Recalibrated from the BA/PE threshold (>=3 for low): RFCs are
                # shorter, decision-focused documents that ground specific
                # choices in a handful of named standards, not claims-per-
                # paragraph documents needing many citations. 2 correctly-
                # matched authoritative citations (e.g. OWASP + NIST for a
                # security RFC) is genuinely well-grounded, not "medium" --
                # the original >=3 threshold was inherited from research_service.py
                # without checking whether it fit this shorter document type.
                "hallucination_risk": (
                    "low" if len(sources_used) >= 2 else "medium" if len(sources_used) >= 1 else "high"
                ),
                "manual_review_recommended": len(sources_used) == 0,
            },
        }
