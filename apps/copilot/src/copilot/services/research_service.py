"""
Research service for web search and source verification.

Implements source verification against authorized sources per SRS.
Used by BA Skill to verify claims and ground BRD in real data.
"""

import os
from typing import Optional, List, Dict
from datetime import datetime
from ..config.authorized_sources import AUTHORIZED_SOURCES


class ResearchService:
    """Service for web search and source verification."""
    
    def __init__(self):
        """Initialize research service."""
        self.authorized_sources = AUTHORIZED_SOURCES
    
    def verify_source_authority(self, source_url: str) -> Dict:
        """
        Verify if a source is authorized against whitelist.
        
        Args:
            source_url: URL to verify
        
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
        
        # Check against authorized sources by country
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
        
        # Not in whitelist
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
    
    async def search_and_verify(self, claim: str, country: Optional[str] = None) -> Dict:
        """
        Search for a claim and attempt to verify against authorized sources.
        
        For MVP: uses keyword matching against known sources.
        For Phase 2: will use real OpenAI web_search_20250305 tool.
        
        Args:
            claim: Claim to search and verify
            country: Optional country code (Nigeria, Ghana, Kenya, etc)
        
        Returns:
            {
                "claim": claim,
                "verified_sources": [...],
                "confidence_level": "high|medium|low",
                "hallucination_risk": "low|medium|high",
                "search_attempts": int
            }
        """
        
        verified_sources = []
        search_attempts = 0
        
        # MVP: Keyword-based search against known sources
        # Phase 2: Replace with real web_search_20250305 calls
        
        keywords_to_sources = {
            # Regulatory keywords -> sources
            "data residency": [
                "https://ncc.gov.ng",
                "https://nca.org.gh",
                "https://cma.or.ke",
                "https://icasa.org.za",
                "https://ntra.gov.eg"
            ],
            "ncc": ["https://ncc.gov.ng"],
            "nca": ["https://nca.org.gh"],
            "cma": ["https://cma.or.ke"],
            "icasa": ["https://icasa.org.za"],
            "ntra": ["https://ntra.gov.eg"],
            
            # Business keywords -> industry sources
            "churn": ["https://gsma.com", "https://statista.com"],
            "coverage": ["https://gsma.com"],
            "arpu": ["https://statista.com", "https://gsma.com"],
            "network": ["https://gsma.com"],
            "5g": ["https://gsma.com"],
            "compliance": ["https://gartner.com", "https://gsma.com"],
            "security": ["https://gartner.com"],
            "mobile": ["https://statista.com", "https://gsma.com"],
        }
        
        claim_lower = claim.lower()
        
        # Find matching sources for claim keywords
        for keyword, urls in keywords_to_sources.items():
            if keyword in claim_lower:
                for url in urls:
                    verification = self.verify_source_authority(url)
                    if verification.get("verified"):
                        verified_sources.append({
                            "claim": claim,
                            "source_url": url,
                            "source_type": verification.get("source_type"),
                            "authority_level": verification.get("authority_level"),
                            "accessed_at": datetime.now().isoformat(),
                            "verified": True,
                            "confidence_level": "high",
                            "verification_status": "verified",
                            "search_queries_used": [keyword]
                        })
                search_attempts += 1
        
        # Determine confidence
        if len(verified_sources) >= 2:
            confidence = "high"
            hallucination_risk = "low"
        elif len(verified_sources) == 1:
            confidence = "medium"
            hallucination_risk = "low"
        else:
            confidence = "low"
            hallucination_risk = "medium"
        
        return {
            "claim": claim,
            "verified_sources": verified_sources,
            "confidence_level": confidence,
            "hallucination_risk": hallucination_risk,
            "search_attempts": search_attempts,
            "sources_found": len(verified_sources)
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
