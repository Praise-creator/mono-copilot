"""
Live compliance-document lookup for the Security RFC role.

Deliberately NOT a hardcoded provision store -- an earlier version of this
was a Python dict with the actual legal text typed in by hand, which is
exactly the wrong shape: it goes stale the moment the law changes, and it's
really just a more convincing-looking flavor of the same hallucination risk
this project keeps having to correct (invented URLs, decorative citations).

What's persisted here is only a VERIFIED DOCUMENT LOCATION per country --
confirming a URL is the real, current, authoritative document required an
actual live browser session (searching the regulator's own site, finding
the real GAID/Act PDF, confirming it resolves) -- same bar as
authorized_sources.py/technical_sources.py's URL whitelists, which is worth
persisting for the same reason those are. The substantive legal text itself
is fetched fresh and quoted live, at generation time, on every run --
if the law changes, the next run picks it up automatically; nothing here
goes stale the way a hardcoded provision string would.

Known limitation, stated plainly rather than glossed over: this can only
look inside a document whose location is ALREADY verified and registered
below. It cannot discover a country's compliance document from scratch --
that needs a real web-search tool, which this pipeline does not have yet
(research_service.py and technical_research_service.py are both explicit
that live web search is still a "Phase 2" gap, not built). Registering a
new country here still means someone live-verifies the URL first, exactly
like every other whitelist in this codebase -- what's different from before
is that the actual QUOTED TEXT is never typed by a human into this codebase;
it's read from the real document, fresh, every time.

Excerpt matching is a simple case-insensitive substring search against the
real extracted document text, not semantic search -- it works because
regulatory documents like the NDPC GAID use clean, literal section headings
("Article 33: Data Breach Notification"), confirmed by manually reading it.
It will miss a topic if the real document phrases it differently than the
search term -- that's a real limitation of this MVP approach, not hidden:
a miss returns None (caller must say "not found"), never a fabricated
excerpt to paper over it.
"""

import io
import re
from typing import Dict, Optional

import httpx
from pypdf import PdfReader


# VERIFIED DOCUMENT LOCATIONS only -- never the substantive text itself.
# Each URL below was live-verified (navigated to, confirmed it's the real
# current document) before being added. Do not add a country here without
# doing that same check first -- this project has already had to correct
# invented/wrong URLs once.
VERIFIED_COMPLIANCE_DOCUMENTS: Dict[str, str] = {
    "Nigeria": "https://ndpc.gov.ng/wp-content/uploads/2025/07/NDP-ACT-GAID-2025-MARCH-20TH.pdf",
    # Ghana, Kenya, South Africa, Egypt: pending live verification.
}


async def fetch_compliance_excerpt(country: str, topic: str, context_chars: int = 900, lookahead_chars: int = 60) -> Optional[Dict]:
    """
    Fetch the verified compliance document for `country` and return the
    real excerpt surrounding the SUBSTANTIVE occurrence of `topic` in the
    actual extracted text -- not a summary, the literal surrounding
    passage.

    Regulatory documents like this one list every article in a table of
    contents before the actual article bodies -- confirmed by hitting this
    exact bug on a real run: naively taking the first text match landed on
    the ToC's one-line heading list, not the real requirement, and the
    model correctly declined to invent a citation from a bare list of
    titles rather than quoting the (missing) substantive text. Real article
    bodies in this document start with a numbered subsection marker like
    "(1)" immediately (~20-25 characters) after their heading (confirmed by
    direct inspection); a ToC line never has one nearby at all.

    lookahead_chars defaults to 60, not something looser -- confirmed via a
    second real bug this window has to avoid: a 400-char window was wide
    enough to walk past an unrelated INCIDENTAL mention of the topic phrase
    (e.g. "breach notification" appearing as a checklist item inside a
    completely different article) and grab that OTHER article's "(1)",
    producing a real-sounding but wrong excerpt. The real measured distance
    to that false-positive "(1)" was 123 characters on the actual document;
    60 gives real margin below that while still safely catching the correct
    heading pattern's ~20-25 character distance.

    So: among every place `topic` appears, prefer the first one followed by
    "(1)" within `lookahead_chars` -- that's the real body. If none qualify
    (a different document might not follow this exact convention), fall
    back to the LAST occurrence rather than the first, since a ToC/index is
    far more likely to appear early in a legal document than late.

    Returns None (never a guess) if:
    - no verified document is registered for this country yet, or
    - the live fetch fails (network error, bad status, unreadable PDF), or
    - `topic` isn't found anywhere in the real fetched text at all.

    Args:
        country: Country name matching VERIFIED_COMPLIANCE_DOCUMENTS' keys.
        topic: Search term to locate in the real document, e.g. "breach notification".
        context_chars: How much real text to return after the chosen match.
        lookahead_chars: How far past each candidate match to look for a "(1)" marker before deciding it's substantive body text rather than a ToC line.
    """
    url = VERIFIED_COMPLIANCE_DOCUMENTS.get(country)
    if not url:
        return None

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")

            if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
                reader = PdfReader(io.BytesIO(response.content))
                full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
            else:
                full_text = response.text
    except Exception:
        # Network failure, bad status, corrupt/unreadable PDF -- all
        # collapse to "couldn't verify this right now," never a guess.
        return None

    text_lower = full_text.lower()
    topic_lower = topic.lower()

    candidates = []
    search_start = 0
    while True:
        idx = text_lower.find(topic_lower, search_start)
        if idx == -1:
            break
        candidates.append(idx)
        search_start = idx + 1

    if not candidates:
        return None

    chosen = None
    for idx in candidates:
        window = full_text[idx: idx + lookahead_chars]
        if re.search(r"\(1\)", window):
            chosen = idx
            break
    if chosen is None:
        chosen = candidates[-1]

    start = max(0, chosen - 80)
    end = min(len(full_text), chosen + context_chars)
    # Collapse whitespace/line-wrap noise that PDF extraction introduces —
    # the source PDF's real paragraphs get broken across lines by the
    # extractor; a reader shouldn't see mid-sentence line breaks that
    # aren't actually in the original document's prose.
    excerpt = " ".join(full_text[start:end].split())

    return {"source_url": url, "topic": topic, "excerpt": excerpt}
