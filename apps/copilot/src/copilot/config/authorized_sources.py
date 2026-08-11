"""
Whitelist of authorized sources by country and type.
Used for source verification in BA/PE agents.
"""

from typing import Dict, List


# Authorized sources by country and type
AUTHORIZED_SOURCES: Dict[str, Dict[str, List[str]]] = {
    "Nigeria": {
        "government": [
            "ncc.gov.ng",
            "nrs.gov.ng",
            "naicom.gov.ng",
            "cbn.gov.ng",
        ],
        "industry": [
            "gsma.com",
            "statista.com",
        ],
        "academic": [
            "unilag.edu.ng",
            "ui.edu.ng",
        ],
    },
    "Ghana": {
        "government": [
            "nca.org.gh",
            "mofep.gov.gh",
            "bog.gov.gh",
        ],
        "industry": [
            "gsma.com",
            "statista.com",
        ],
        "academic": [],
    },
    "Kenya": {
        "government": [
            "ca.go.ke",
            "cma.or.ke",
            "centralbank.go.ke",
        ],
        "industry": [
            "gsma.com",
            "statista.com",
        ],
        "academic": [],
    },
    "South Africa": {
        "government": [
            "icasa.org.za",
            "sars.gov.za",
            "treasury.gov.za",
        ],
        "industry": [
            "gsma.com",
            "statista.com",
        ],
        "academic": [],
    },
    "Egypt": {
        "government": [
            "tra.gov.eg",
            "cbe.org.eg",
        ],
        "industry": [
            "gsma.com",
            "statista.com",
        ],
        "academic": [],
    },
    "Global": {
        "industry": [
            "gsma.com",
            "statista.com",
            "gartner.com",
            "forrester.com",
        ],
        "academic": [
            "ieee.org",
            "acm.org",
            "scholar.google.com",
        ],
    },
}


def is_source_authorized(source_url: str) -> bool:
    """
    Check if a source URL is in the authorized sources whitelist.
    
    Args:
        source_url: URL to verify
    
    Returns:
        True if authorized, False otherwise
    """
    url_lower = source_url.lower()
    for sources_by_type in AUTHORIZED_SOURCES.values():
        for urls in sources_by_type.values():
            for authorized_url in urls:
                if authorized_url.lower() in url_lower:
                    return True
    return False


def get_authority_level(source_url: str) -> str:
    """
    Get authority level for a source (high, medium, low).
    
    Args:
        source_url: URL to check
    
    Returns:
        Authority level: "high", "medium", or "low"
    """
    url_lower = source_url.lower()
    for sources_by_type in AUTHORIZED_SOURCES.values():
        for source_type, urls in sources_by_type.items():
            for authorized_url in urls:
                if authorized_url.lower() in url_lower:
                    return "high" if source_type in ("government", "industry", "academic") else "low"
    return "low"
