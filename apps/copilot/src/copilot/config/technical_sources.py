"""
Whitelist of authorized engineering-standards sources for the RFC sub-agents
(UI/UX, Software Architect, Security, QA, DevOps).

This is deliberately a SEPARATE whitelist from authorized_sources.py, not an
extension of it. authorized_sources.py is scoped to telecom regulators and
is country-keyed (Nigeria/Ghana/Kenya/South Africa/Egypt/Global) because BA/PE
claims are about regulatory compliance and market data. RFC claims are about
engineering practice — accessibility standards, security frameworks, testing
methodology, cloud architecture patterns — which aren't country-scoped at
all. Keying this whitelist by role instead of by country matches what's
actually being verified.

One exception: the Security RFC also needs country-scoped data-protection
law citations (NDPR, POPIA, etc.). Rather than duplicating country logic
here, the Security RFC reuses the EXISTING authorized_sources.py country
resolution (via ResearchService.detect_country()) and checks against
DATA_PROTECTION_SOURCES below — which starts empty on purpose. The project
already burned real time once on invented whitelist URLs (naira.gov.ng,
ica.go.ke, and others were wrong or didn't exist, caught only by live
browser verification). No data-protection URL goes in this file until it's
been checked against the real internet the same way.
"""

from typing import Dict, List


# Engineering-standards sources by RFC role. "standards_bodies" is the
# authorized-domain whitelist itself; "keywords" maps a claim keyword to
# which of those domains is relevant, mirroring the keyword->URL pattern
# already established in authorized_sources.py / research_service.py.
TECHNICAL_SOURCES: Dict[str, Dict[str, object]] = {
    "ui_ux": {
        "standards_bodies": [
            "w3.org",
            "nngroup.com",
        ],
        "keywords": {
            "wcag": ["w3.org"],
            "accessibility": ["w3.org"],
            "success criterion": ["w3.org"],
            "usability": ["nngroup.com"],
            "user experience": ["nngroup.com"],
            "heuristic": ["nngroup.com"],
        },
    },
    "software_architect": {
        "standards_bodies": [
            "aws.amazon.com",
            "learn.microsoft.com",
        ],
        "keywords": {
            "well-architected": ["aws.amazon.com"],
            "scalability": ["aws.amazon.com"],
            "microservice": ["aws.amazon.com"],
            "architecture center": ["learn.microsoft.com"],
            "reference architecture": ["learn.microsoft.com"],
        },
    },
    "security": {
        "standards_bodies": [
            "owasp.org",
            "nist.gov",
            "cve.mitre.org",
        ],
        "keywords": {
            "owasp": ["owasp.org"],
            "asvs": ["owasp.org"],
            "nist": ["nist.gov"],
            "csf": ["nist.gov"],
            "cve": ["cve.mitre.org"],
            "vulnerability": ["cve.mitre.org"],
        },
    },
    "qa": {
        "standards_bodies": [
            "istqb.org",
            "iso.org",
        ],
        "keywords": {
            "istqb": ["istqb.org"],
            "test strategy": ["istqb.org"],
            "iso 29119": ["iso.org"],
            "iso/iec 29119": ["iso.org"],
        },
    },
    "devops": {
        "standards_bodies": [
            "cncf.io",
            "aws.amazon.com",
            "learn.microsoft.com",
        ],
        "keywords": {
            "cncf": ["cncf.io"],
            "kubernetes": ["cncf.io"],
            "cloud native": ["cncf.io"],
            "well-architected": ["aws.amazon.com"],
            "reliability pillar": ["aws.amazon.com"],
            "operational excellence": ["aws.amazon.com"],
        },
    },
}


# Country-scoped data-protection law citations for the Security RFC only.
# INTENTIONALLY EMPTY. Do not add a URL here without live-verifying it
# against the real internet first (visit it, confirm it resolves and is the
# right entity) — the same discipline that caught invented/wrong URLs in
# authorized_sources.py. Until a country's entry here is populated, the
# Security RFC must say the citation isn't yet available rather than guess.
DATA_PROTECTION_SOURCES: Dict[str, List[str]] = {
    "Nigeria": [],       # NDPR (Nigeria Data Protection Regulation) — pending live verification
    "Ghana": [],         # Data Protection Act — pending live verification
    "Kenya": [],         # Data Protection Act — pending live verification
    "South Africa": [],  # POPIA — pending live verification
    "Egypt": [],         # Data protection law — pending live verification
}


def is_technical_source_authorized(source_url: str) -> bool:
    """Check if a source URL is in the engineering-standards whitelist
    (either role-scoped standards_bodies, or a verified data-protection
    entry)."""
    url_lower = source_url.lower()
    for role_sources in TECHNICAL_SOURCES.values():
        for authorized_url in role_sources.get("standards_bodies", []):
            if authorized_url.lower() in url_lower:
                return True
    for urls in DATA_PROTECTION_SOURCES.values():
        for authorized_url in urls:
            if authorized_url.lower() in url_lower:
                return True
    return False


def get_technical_authority_level(source_url: str) -> str:
    """All whitelisted engineering-standards sources are treated as high
    authority (standards bodies, not blogs); anything not on the whitelist
    is low, same convention as authorized_sources.get_authority_level()."""
    return "high" if is_technical_source_authorized(source_url) else "low"


def get_data_protection_sources(country: str) -> List[str]:
    """Verified data-protection URLs for a country. Returns an empty list
    (not an error) if none are verified yet — callers must treat that as
    'not yet available', not as license to cite something else instead."""
    return DATA_PROTECTION_SOURCES.get(country, [])
