"""
Research service for web search and source verification.

Implements source verification against authorized sources per SRS.
Used by BA Skill and PE Skill to verify claims and ground BRD/PRD output in
real data.

Single source of truth for the BA/PE "extract and verify sources" logic —
both skills call extract_and_verify_sources() here instead of each keeping
their own near-identical copy. That duplication is exactly the shape of bug
this project already hit once (the "finish" approval-word mismatch): two
places that have to agree forever, and quietly didn't.
"""

import os
import re
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from ..config.authorized_sources import AUTHORIZED_SOURCES


# Country-agnostic keywords: match anywhere, filtered to whichever country's
# regulator is actually relevant when one can be determined.
_GENERIC_REGULATORY_KEYWORDS = ["data residency", "regulation", "regulatory", "government"]

# Regulator abbreviation -> country. Already unambiguous per-keyword (each
# abbreviation belongs to exactly one country), so these don't need country
# filtering the way the generic keywords above do.
_REGULATOR_ABBREVIATION_TO_COUNTRY = {
    "ncc": "Nigeria",
    "nca": "Ghana",
    "cma": "Kenya",
    "icasa": "South Africa",
    "ntra": "Egypt",
}

# Business/industry keywords are country-agnostic by nature (market data,
# not regulation), so they're never filtered by country.
_INDUSTRY_KEYWORDS = {
    "churn": ["gsma.com", "statista.com"],
    "coverage": ["gsma.com"],
    "arpu": ["statista.com", "gsma.com"],
    "network": ["gsma.com"],
    "5g": ["gsma.com"],
    "compliance": ["gartner.com", "gsma.com"],
    "security": ["gartner.com"],
    "mobile": ["statista.com", "gsma.com"],
}

_MARKDOWN_ARTIFACT_RE = re.compile(r"[*_#`]")
_LEADING_LIST_MARKER_RE = re.compile(r"^[\-\d.)\s]+")
_WHITESPACE_RE = re.compile(r"\s+")


def _contains_keyword(text: str, keyword: str) -> bool:
    """
    Word-boundary keyword match, not a naive substring check. Short
    abbreviations like "ntra" are real substrings of ordinary English words
    ("contractual" contains "ntra") — a plain `in` check silently cites the
    wrong country's regulator whenever a document happens to use one of
    those words for an unrelated reason. \\b handles multi-word keywords
    (e.g. "data residency") correctly too, since the boundary applies to the
    whole matched phrase.
    """
    return re.search(r"\b" + re.escape(keyword) + r"\b", text) is not None


_MARKET_TAG_RE = re.compile(r"market/country:\s*([^\n.]{1,60})", re.IGNORECASE)
_NON_ANSWER_MARKET_VALUES = ("internal", "multi-market", "no specific country", "n/a", "none")


def _extract_unsupported_market(text: str) -> Optional[str]:
    """
    If the intake agent's explicit "Market/country: X" tag names a real
    country that _detect_country() didn't recognize (i.e. one outside the
    current 5-country whitelist), return it. Distinguishes "a real country
    was stated, we just don't have whitelist coverage for it yet" from
    "genuinely no country was given anywhere" — the two need different
    fallback behavior: the former should cite nothing rather than
    substitute five unrelated countries' regulators.
    """
    match = _MARKET_TAG_RE.search(text)
    if not match:
        return None
    stated = match.group(1).strip().rstrip(".")
    if not stated:
        return None
    stated_lower = stated.lower()
    if any(non_answer in stated_lower for non_answer in _NON_ANSWER_MARKET_VALUES):
        return None
    return stated

# Every keyword this service knows how to match against a claim/sentence —
# used by extract_and_verify_sources() to decide what's worth checking.
_ALL_KEYWORDS = (
    _GENERIC_REGULATORY_KEYWORDS
    + list(_REGULATOR_ABBREVIATION_TO_COUNTRY.keys())
    + list(_INDUSTRY_KEYWORDS.keys())
)


class ResearchService:
    """Service for web search and source verification."""

    def __init__(self):
        """Initialize research service."""
        self.authorized_sources = AUTHORIZED_SOURCES

    def verify_source_authority(self, source_url: str) -> Dict:
        """
        Verify if a source is authorized against whitelist.

        Returns:
            {
                "verified": bool,
                "authority_level": "high|medium|low",
                "source_type": "government|industry|academic",
                "country": "Nigeria|Ghana|..." or None,
                "url": source_url
            }
        """
        url_lower = source_url.lower()

        for country, sources_by_type in self.authorized_sources.items():
            for source_type, urls in sources_by_type.items():
                for authorized_url in urls:
                    if authorized_url.lower() in url_lower:
                        return {
                            "verified": True,
                            "authority_level": self._get_authority_for_type(source_type),
                            "source_type": source_type,
                            "country": country,
                            "url": source_url
                        }

        return {
            "verified": False,
            "authority_level": "unknown",
            "source_type": "unknown",
            "country": None,
            "url": source_url
        }

    def _get_authority_for_type(self, source_type: str) -> str:
        """Map source type to authority level."""
        authority_map = {
            "government": "high",
            "industry": "high",
            "academic": "high",
            "other": "low"
        }
        return authority_map.get(source_type, "low")

    def _detect_country(self, text: str) -> Optional[str]:
        """
        Detect which authorized-sources country (if any) is mentioned in the
        given text, so a claim can be checked against the country it's
        actually about instead of every country's regulator whenever the
        caller doesn't correctly say which one is relevant. "Global" is
        never returned here since it isn't a country whose regulator a claim
        could be scoped to.
        """
        text_lower = text.lower()
        for country in self.authorized_sources:
            if country == "Global":
                continue
            if re.search(r"\b" + re.escape(country.lower()) + r"\b", text_lower):
                return country
        return None

    def detect_country(self, text: str) -> Optional[str]:
        """Public wrapper around _detect_country() — the Security RFC reuses
        this exact BA/PE country-resolution logic for its data-protection
        citations rather than re-implementing country matching a third time."""
        return self._detect_country(text)

    def _all_government_sources(self) -> List[Tuple[str, str]]:
        """[(country, full_url), ...] across every country, excluding Global."""
        result = []
        for country, sources_by_type in self.authorized_sources.items():
            if country == "Global":
                continue
            for url in sources_by_type.get("government", []):
                result.append((country, f"https://{url}"))
        return result

    def _make_source_entry(self, claim: str, full_url: str, confidence: str, search_query: str) -> Optional[Dict]:
        verification = self.verify_source_authority(full_url)
        if not verification.get("verified"):
            return None
        return {
            "claim": claim,
            "source_url": full_url,
            "source_type": verification.get("source_type"),
            "authority_level": verification.get("authority_level"),
            "accessed_at": datetime.now().isoformat(),
            "verified": True,
            "confidence_level": confidence,
            "verification_status": "verified",
            "search_queries_used": [search_query]
        }

    def _clean_claim_text(self, text: str, max_length: int = 140) -> str:
        """
        Strip markdown syntax and truncate so a citation stays presentable
        even when it's built from a raw sentence pulled straight out of
        generated markdown (bold markers, leading bullet dashes, headers).
        """
        cleaned = _MARKDOWN_ARTIFACT_RE.sub("", text).strip()
        cleaned = _LEADING_LIST_MARKER_RE.sub("", cleaned).strip()
        cleaned = _WHITESPACE_RE.sub(" ", cleaned)
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length].rstrip() + "..."
        return cleaned or text[:max_length]

    async def search_and_verify(self, claim: str, country: Optional[str] = None, suppress_unscoped_government: bool = False) -> Dict:
        """
        Search for a claim and attempt to verify against authorized sources.

        For MVP: uses keyword matching against known sources.
        For Phase 2: will use real OpenAI web_search_20250305 tool.

        Args:
            claim: Claim to search and verify
            country: Country this claim is about, if known (e.g. "Ghana").
                If this isn't a recognized country (e.g. a segment value got
                passed by mistake), falls back to detecting a country
                mentioned in the claim text itself, rather than trusting a
                bad value or silently returning every country's regulator.
            suppress_unscoped_government: True when a real, specific country
                was stated somewhere but isn't one of the 5 in the current
                whitelist. In that case a generic regulatory keyword match
                should cite nothing rather than substitute five unrelated
                countries' regulators as if they were relevant.

        Returns:
            {
                "claim": claim,
                "verified_sources": [...],
                "confidence_level": "high|medium|low",
                "hallucination_risk": "low|medium|high",
                "search_attempts": int,
                "sources_found": int
            }
        """
        verified_sources = []
        search_attempts = 0
        claim_lower = claim.lower()

        resolved_country = country if country in self.authorized_sources else self._detect_country(claim)

        if any(_contains_keyword(claim_lower, kw) for kw in _GENERIC_REGULATORY_KEYWORDS):
            if resolved_country:
                government_sources = [(c, u) for c, u in self._all_government_sources() if c == resolved_country]
                confidence = "high"
                for _, url in government_sources:
                    entry = self._make_source_entry(claim, url, confidence, "data residency")
                    if entry:
                        verified_sources.append(entry)
                search_attempts += 1
            elif not suppress_unscoped_government:
                # Genuinely ambiguous — no country known anywhere in context.
                # Return all as before, but mark it medium rather than high
                # since citing every country's regulator for an unscoped
                # claim is weaker evidence than citing the one that matters.
                government_sources = self._all_government_sources()
                confidence = "medium"
                for _, url in government_sources:
                    entry = self._make_source_entry(claim, url, confidence, "data residency")
                    if entry:
                        verified_sources.append(entry)
                search_attempts += 1
            # else: suppressed — a real, specific country was stated, it's
            # just outside the current whitelist. Citing five other
            # countries' regulators here would be worse than citing none.

        for abbreviation, country_name in _REGULATOR_ABBREVIATION_TO_COUNTRY.items():
            if _contains_keyword(claim_lower, abbreviation):
                for url in self.authorized_sources.get(country_name, {}).get("government", []):
                    entry = self._make_source_entry(claim, f"https://{url}", "high", abbreviation)
                    if entry:
                        verified_sources.append(entry)
                search_attempts += 1

        for keyword, urls in _INDUSTRY_KEYWORDS.items():
            if _contains_keyword(claim_lower, keyword):
                for url in urls:
                    entry = self._make_source_entry(claim, f"https://{url}", "high", keyword)
                    if entry:
                        verified_sources.append(entry)
                search_attempts += 1

        if len(verified_sources) >= 2:
            confidence_level = "high"
            hallucination_risk = "low"
        elif len(verified_sources) == 1:
            confidence_level = "medium"
            hallucination_risk = "low"
        else:
            confidence_level = "low"
            hallucination_risk = "medium"

        return {
            "claim": claim,
            "verified_sources": verified_sources,
            "confidence_level": confidence_level,
            "hallucination_risk": hallucination_risk,
            "search_attempts": search_attempts,
            "sources_found": len(verified_sources)
        }

    async def extract_and_verify_sources(
        self,
        markdown: str,
        segment: str,
        problem_statement: str,
        id_key: str,
        id_prefix: str,
    ) -> Dict:
        """
        Shared BA/PE source-extraction logic. Detects the project's country
        once from the full document (problem statement + generated markdown)
        rather than per-keyword, so every check in this pass is scoped to
        the right country consistently. id_key/id_prefix let BA and PE each
        get their own metadata id field (brd_id/BRD vs prd_id/PRD) from this
        one shared implementation.

        Returns the sources_metadata dict saved alongside the document.
        """
        combined_text = f"{problem_statement}\n\n{markdown}"
        resolved_country = self._detect_country(combined_text)
        unsupported_market = _extract_unsupported_market(combined_text) if not resolved_country else None
        suppress_unscoped_government = unsupported_market is not None

        sources_used: List[Dict] = []
        seen_urls: set = set()

        def _add_unique(source: Dict) -> None:
            """A source counts once per document, no matter how many
            different keywords happened to surface the same URL —
            otherwise a compliance-heavy document that naturally repeats
            'regulation'/'regulatory'/'compliance' inflates the same handful
            of URLs into a misleadingly large 'sources verified' count."""
            url = source.get("source_url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                sources_used.append(source)

        text_lower = markdown.lower()
        problem_lower = problem_statement.lower()

        for keyword in _ALL_KEYWORDS:
            if _contains_keyword(text_lower, keyword) or _contains_keyword(problem_lower, keyword):
                result = await self.search_and_verify(keyword, resolved_country, suppress_unscoped_government=suppress_unscoped_government)
                for source in result.get("verified_sources", []):
                    _add_unique(source)

        sentences = re.split(r"(?<=[.!?])\s+", markdown)
        for sentence in sentences[:10]:
            sentence_lower = sentence.lower()
            if any(_contains_keyword(sentence_lower, kw) for kw in _ALL_KEYWORDS):
                cleaned_claim = self._clean_claim_text(sentence)
                result = await self.search_and_verify(cleaned_claim, resolved_country, suppress_unscoped_government=suppress_unscoped_government)
                for source in result.get("verified_sources", []):
                    relabeled = {**source, "claim": cleaned_claim}
                    _add_unique(relabeled)

        return {
            id_key: f"{id_prefix}-{datetime.now().strftime('%Y%m%d')}",
            "segment": segment,
            "country": resolved_country,
            "stated_market_no_whitelist_coverage": unsupported_market,
            "generated_at": datetime.now().isoformat(),
            "sources_used": sources_used,
            "search_statistics": {
                "total_searches": len(_ALL_KEYWORDS),
                "sources_verified": len(sources_used),
                "verification_coverage": "high" if len(sources_used) >= 3 else "medium" if len(sources_used) >= 1 else "low"
            },
            "data_integrity": {
                "all_sources_verified": len(sources_used) >= 3,
                "hallucination_risk": "low" if len(sources_used) >= 3 else "medium" if len(sources_used) >= 1 else "high",
                "unresolved_conflicts": 0,
                "manual_review_recommended": len(sources_used) == 0
            }
        }

    def get_authorized_sources_for_country(self, country: str) -> Dict:
        """Get all authorized sources for a specific country."""
        return self.authorized_sources.get(country, {})

    def list_all_authorized_sources(self) -> Dict:
        """Get all authorized sources."""
        return self.authorized_sources

    def create_verified_source(
        self,
        claim: str,
        source_url: str,
        search_query: str,
        confidence: str = "high"
    ) -> Dict:
        """Create a verified source object."""
        verification = self.verify_source_authority(source_url)

        return {
            "claim": claim,
            "source_url": source_url,
            "source_type": verification.get("source_type"),
            "authority_level": verification.get("authority_level"),
            "accessed_at": datetime.now().isoformat(),
            "verified": verification.get("verified"),
            "confidence_level": confidence,
            "verification_status": "verified" if verification.get("verified") else "unverified",
            "search_queries_used": [search_query],
            "cross_verified_count": 0,
            "content_snippet": None,
            "agent_notes": None
        }
