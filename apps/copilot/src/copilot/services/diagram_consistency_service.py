"""
Diagram-vs-prose consistency review -- the one layer of Mermaid quality
control that genuinely needs a model, because it's a meaning question, not
a syntax or structure question. mermaid_structure.py's Layer 1 checks would
pass a diagram that perfectly parses and perfectly connects but still gets
the actual facts wrong -- the real bug this was built to catch was exactly
that: a PRD's own diagram merged two different protocols (REST API and
SMPP) into one shared edge label, directly contradicting a sentence one
paragraph above it in the very same document. No parser catches that; it
requires actually reading both the prose and the diagram and noticing they
disagree.

Kept explainable the same way compliance_lookup_service.py is: this never
returns a bare "consistent: false" verdict. Every finding must carry two
exact, verbatim quotes -- one from the document's prose, one from inside
the diagram -- and BOTH quotes are verified against the actual document
text after the model responds, before either one is trusted. A finding
whose quotes don't actually appear in the document is dropped, not shown,
the same "returns None rather than a guess" discipline
compliance_lookup_service.py already uses for a different kind of
unverifiable claim. This means a caller can always show a human the exact
two sentences that disagree, never just a model's unsupported opinion that
something "seems inconsistent."

Three real bugs have been found and fixed here across two separate runs,
all variations on the same underlying theme -- a "finding" whose two
quotes are individually real text, but don't actually mean what the model
claims they mean together:

1. The model sometimes includes an entry whose own `explanation` says
   something like "there is no contradiction found in this diagram" --
   i.e. it checked a quote pair, concluded they agree, but still added it.
   Fixed with an explicit prompt rule AND a defensive phrase filter
   (`_looks_like_non_finding`) that drops any finding whose explanation
   contains an unambiguous self-negating phrase, even if the quotes verify.

2. The model repeatedly flags a diagram simply being LESS DETAILED than
   the prose as a "contradiction" -- e.g. prose names a tool and describes
   its role at length, a diagram box just names the tool, and the model
   calls that a disagreement. Confirmed recurring on a second run even
   after the first prompt fix added three concrete negative examples --
   this category has proven genuinely hard to eliminate with prompt
   wording alone, so more negative examples were added rather than
   assuming the earlier ones were sufficient.

3. A genuinely different failure, found on the same run as (2): the model
   quotes something real from the prose and something real from the
   diagram, and both quotes verify individually, but they are not actually
   about the same thing -- e.g. a sentence describing what the SMPP
   Gateway does NOT do, paired against a diagram edge belonging to the
   CRM, both mentioning "USSD" so they look related, but describing two
   different components entirely. Exact-substring quote verification
   cannot catch this on its own, since both strings genuinely appear in
   the document -- the flaw is in which two real things got paired, not
   in either quote's authenticity. Fixed by requiring a new
   `component_name` field naming the specific component both quotes are
   actually about, then mechanically verifying that name appears in BOTH
   quotes (not just somewhere in the document) before trusting the
   finding. This is a real, meaningful improvement, confirmed against the
   actual case that exposed it -- but not a complete guarantee: a model
   that names a genuinely shared but incidental word (e.g. "USSD," which
   both a SMPP Gateway sentence and a CRM edge happen to mention) as the
   component_name would still pass this check. The prompt now also
   explicitly warns against exactly this failure mode with the real
   example, since the mechanical check alone can be routed around.

Cost discipline: uses gpt-4o-mini (same choice as cli/intake_agent.py, for
the same reason -- this is a classification/review task, not a document-
generation task, and doesn't need gpt-4-turbo's cost). Skips the API call
entirely when a document has no mermaid diagrams at all, rather than
spending a call to learn nothing.

Generic by construction, not hardcoded: the instruction given to the model
is "does anything in any diagram disagree with something the prose states,"
not a list of known bug patterns to check for. It will catch the next
protocol/actor/label mismatch this project produces, not just the one that
was already found once.

run_full_diagram_review() below is the one function ba_skill.py, pe_skill.py,
and rfc_skill.py actually call -- it combines this module's Layer 2 with
mermaid_structure.py's Layer 1 (structural) and Layer 3 (cross-document
similarity, only when a caller has a document to compare against) into one
result, the same "one shared implementation, not three near-identical
copies" discipline this codebase already applies to research_service.py
and rfc_skill.py's ROLE_CONFIGS.
"""

import json
import os
import re
from typing import Dict, List, Optional

from openai import AsyncOpenAI

from .mermaid_structure import (
    find_diagrams_in_markdown,
    check_all_diagrams_structurally,
    check_diagram_similarity_against,
    check_internal_diagram_duplication,
    check_decision_points_reflected,
)


MODEL = "gpt-4o-mini"

_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "report_diagram_consistency",
        "description": (
            "Report every place a mermaid diagram's own content (an edge label, "
            "a node name, a stated protocol, an actor role) disagrees with "
            "something the surrounding document text states about that same "
            "thing. Only report a genuine, factual contradiction backed by two "
            "exact quotes. If a diagram simplifies or omits something the prose "
            "covers in more detail, that is not a contradiction -- do not report "
            "it. A shorter label for the same action, or an omitted list of "
            "channels or steps the prose spells out, is simplification, not "
            "disagreement -- do not report it either, even though it can look "
            "similar to a real finding at a glance. "

            "CRITICAL: both quotes must be about the exact same specific "
            "component or edge, not just share a topic word. A sentence "
            "describing what one component does NOT do is not a contradiction "
            "of a diagram edge belonging to a DIFFERENT component, even if both "
            "happen to mention the same keyword (e.g. a sentence about what the "
            "SMS gateway does not handle is not contradicted by a diagram edge "
            "showing the CRM doing that thing -- those are two different "
            "components, and the sentence was never a claim about the CRM). "

            "CRITICAL: only add an entry to findings if you have concluded the "
            "two quotes ACTUALLY DISAGREE. If you check a pair of quotes and "
            "conclude they agree, or that the diagram correctly reflects the "
            "prose, do NOT add an entry for it -- leave it out entirely, even "
            "if you want to note that you checked it. An entry whose own "
            "explanation says the quotes are consistent, or that there is no "
            "contradiction, must never appear in findings. "
            "If nothing actually disagrees anywhere in the document, call this "
            "with an empty findings list. Do not invent a disagreement to have "
            "something to report, and do not add a 'checked, looks fine' entry "
            "either -- both are wrong for the same reason: findings must "
            "contain only real, confirmed disagreements."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "diagram_index": {
                                "type": "integer",
                                "description": "Which mermaid diagram this concerns, counting from 1 in document order.",
                            },
                            "component_name": {
                                "type": "string",
                                "description": (
                                    "The single specific named component, service, or edge that "
                                    "BOTH quotes below are actually about. Must be the real "
                                    "subject whose behavior is being described -- not a generic "
                                    "shared topic word (a protocol name, a channel name) that "
                                    "happens to appear in both quotes without being what either "
                                    "sentence is really about. If the prose_quote is describing "
                                    "what one component does, this must be that component's name, "
                                    "not something it merely mentions in passing."
                                ),
                            },
                            "prose_quote": {
                                "type": "string",
                                "description": (
                                    "An exact, verbatim quote copied from the document's prose "
                                    "text (not from inside the diagram) that states the fact "
                                    "being contradicted. Must be copied exactly, not paraphrased, "
                                    "and must contain component_name."
                                ),
                            },
                            "diagram_quote": {
                                "type": "string",
                                "description": (
                                    "An exact, verbatim fragment copied from inside the mermaid "
                                    "diagram itself (a node label or edge label) that contradicts "
                                    "the prose_quote. Must be copied exactly, not paraphrased, and "
                                    "must contain component_name."
                                ),
                            },
                            "explanation": {
                                "type": "string",
                                "description": (
                                    "One sentence explaining HOW these two quotes disagree. "
                                    "This field must describe a real disagreement -- never write "
                                    "'no contradiction', 'consistent', or 'accurately reflected' "
                                    "here. If that is your conclusion, do not create this entry "
                                    "at all."
                                ),
                            },
                        },
                        "required": ["diagram_index", "component_name", "prose_quote", "diagram_quote", "explanation"],
                    },
                },
            },
            "required": ["findings"],
        },
    },
}

_SYSTEM_PROMPT = """You are reviewing one technical document for internal consistency between its prose and its mermaid diagrams.

You will be given the full document text, with each mermaid diagram numbered in the order it appears. Your only job is to find real, factual disagreements between what a diagram shows and what the surrounding prose states about the same relationship, protocol, actor, or component -- then call report_diagram_consistency with exact quotes proving each one.

A genuine contradiction looks like: the prose says "SMS delivery uses SMPP" and a diagram edge is labeled "REST API" for that same SMS connection. That is worth reporting.

Not a contradiction: a diagram that is simply less detailed than the prose, uses a shortened name for something the prose names in full, or omits a component the prose mentions in passing. Diagrams are allowed to simplify. Only report an actual factual disagreement, never a difference in detail level. Concrete examples of this that have been wrongly reported before, since apparently this needs to be very explicit: prose says "Adjusts model parameters if drift detected" and a diagram box says "Reviews/Adjusts Model" -- NOT a contradiction, the diagram box is just a shorter label for the same action. Prose says "Dispatches offers through RMS Interface to App/SMS/USSD" and a diagram box says "Creates and dispatches offers" -- NOT a contradiction, the diagram just doesn't spell out the channel list, it doesn't claim a different one. Prose says "Investigates and resolves issues or escalates" and a diagram box says "Resolves or escalates" -- NOT a contradiction, the diagram dropped one step's word, it didn't add a false one. Prose says "Jenkins is used for orchestrating the pipeline due to its robust plugin ecosystem..." and a diagram box says "CI Pipeline (Jenkins)" -- NOT a contradiction, both name Jenkins as the tool, one just also describes why it was chosen. Prose says "Deploy to a mirror of the production environment... Requires manual approval" and a diagram box says "Staging Environment (Manual Approval Required)" -- NOT a contradiction, the diagram box correctly reflects the manual-approval fact, it just doesn't repeat the word "mirror" -- a box not repeating every adjective from a longer sentence is not a disagreement. None of these belong in findings. A real finding requires the diagram to say something that is actually false relative to the prose, not merely shorter.

SEPARATE AND EQUALLY IMPORTANT RULE, since this has been gotten wrong a different way: both quotes must be about the exact same specific component or edge, not just share a topic word. A real example of getting this wrong: a document's prose says an SMS gateway's "sole responsibility is SMS communication; does not handle USSD or other interaction types" -- that sentence is a boundary statement about the SMS gateway. A diagram elsewhere in the same document has an edge showing the CRM system connecting to a USSD platform. These two are NOT a contradiction, even though both mention USSD -- the prose sentence was never a claim about the CRM, it was describing what the SMS gateway itself does not do. Before reporting a finding, identify the ONE specific component or edge both quotes are genuinely about, and make sure it is the same one on both sides, not just a shared keyword riding along.

CRITICAL RULE, since this has been gotten wrong before too: findings is a list of confirmed disagreements ONLY. If you examine a pair of quotes and conclude they actually agree -- for example the prose says "GSM" and the diagram also says "GSM" -- do not add an entry saying so. Do not add an entry whose explanation is "there is no contradiction" or "this is accurately reflected" or anything similar. Checking something and confirming it's fine is not a finding; only report the cases where something is actually wrong. If everything you check turns out fine, findings should simply be empty.

Every finding must include a component_name naming the one specific thing both quotes are about, plus two exact quotes copied verbatim from the actual text you were given -- one from the prose, one from inside a diagram -- and component_name must actually appear in both of them. Do not paraphrase any of the three. If you cannot find an exact quote containing component_name on both sides, do not report that finding.

If you find nothing wrong, call the tool with an empty findings list. Do not manufacture a finding just to have something to say, and do not add a "checked, looks fine" entry either."""

# Defensive backstop, not the primary fix (the primary fix is the prompt
# above). Prompt-only guidance has already been proven, on real runs, to
# not be followed 100% of the time on its own -- so this catches the model
# explicitly denying its own finding in plain words, even if it still adds
# the entry. Deliberately narrow: only matches unambiguous self-negation
# phrases that would essentially never appear inside the explanation of an
# ACTUAL contradiction (nobody explains a real disagreement by writing "no
# contradiction"). Not attempting anything broader/fuzzier than that --
# a wider net risks discarding a genuine finding that happens to use
# similar words while actually describing a real disagreement.
#
# The "accurately/correctly VERB" branch originally only matched the verb
# "reflect" -- a real run showed three findings slip straight through
# because the model wrote "accurately depicts", "accurately shows", and
# "correctly illustrates" instead, three synonyms the narrower word list
# never covered, all describing the exact same "yes, this matches"
# self-praise this filter exists to catch. Generalized to a small set of
# synonymous verbs rather than the single one first observed. Each verb
# branch has a negative lookbehind for "not "/"n't "/"never " immediately
# before "accurately"/"correctly", since a real disagreement could
# plausibly be phrased as "does NOT accurately reflect" -- that sentence
# is describing an actual mismatch, not denying one, and must not be
# filtered.
_NON_FINDING_PHRASES_RE = re.compile(
    r"no contradiction|not a contradiction|no discrepancy|not a discrepancy|"
    r"there is no conflict|"
    r"(?<!not )(?<!n't )(?<!never )accurately (reflect|depict|show|illustrate|represent|capture|portray)\w*|"
    r"(?<!not )(?<!n't )(?<!never )correctly (reflect|depict|show|illustrate|represent|capture|portray)\w*",
    re.IGNORECASE,
)


def _looks_like_non_finding(explanation: str) -> bool:
    return bool(_NON_FINDING_PHRASES_RE.search(explanation or ""))


# A second, distinct defensive backstop for a different recurring failure:
# the model flagging a diagram simply OMITTING a detail the prose has as a
# "contradiction", even with three concrete negative examples already in
# the prompt above. Confirmed recurring on a real run with a fourth,
# different instance those three examples didn't cover: prose stated a
# rollback trigger with two conditions ("5% increase... for over 10
# minutes"), the diagram's edge label only carried the first, and the
# model's own explanation was literally "the diagram does not specify the
# condition of observing the 5% error increase continuously for over 10
# minutes" -- describing an omission, not a contradiction, in almost the
# same words every time this happens. Scoped to phrases that specifically
# describe absence ("does not specify/mention/detail/include", "without
# specifying/detailing/mentioning", "omits the") rather than difference --
# a genuine contradiction is described as the diagram stating something
# ACTIVELY DIFFERENT ("labels this X instead of Y", "shows Z which
# contradicts..."), never as the diagram merely lacking a detail, so this
# phrase family shouldn't overlap with real findings' explanations.
_OMISSION_PHRASES_RE = re.compile(
    r"does not specify|doesn't specify|does not mention|doesn't mention|"
    r"does not detail|doesn't detail|without specifying|without detailing|"
    r"without mentioning|does not include|doesn't include|omits the|"
    r"does not capture|doesn't capture",
    re.IGNORECASE,
)


def _looks_like_omission_non_finding(explanation: str) -> bool:
    return bool(_OMISSION_PHRASES_RE.search(explanation or ""))


def _normalize_for_match(text: str) -> str:
    """Whitespace-insensitive comparison -- a quote copied from markdown
    can legitimately differ from the source by a line-wrap or extra space
    without being any less "verbatim" in the sense that matters here."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _quote_appears_in(quote: str, full_text: str) -> bool:
    if not quote or not quote.strip():
        return False
    return _normalize_for_match(quote) in _normalize_for_match(full_text)


async def review_diagram_consistency(markdown: str) -> Dict:
    """
    Reviews every mermaid diagram in `markdown` against the document's own
    prose for factual disagreements. Returns:

        {
            "reviewed": bool,          # False only when there was nothing to review
                                        # (no diagrams) or the model call/response
                                        # itself failed -- never a silent guess
            "diagram_count": int,
            "findings": [              # only quote-verified, correctly-attributed,
                                        # genuine-disagreement findings ever appear here
                {
                    "diagram_index": int,
                    "component_name": str,
                    "prose_quote": str,
                    "diagram_quote": str,
                    "explanation": str,
                }
            ],
            "unverifiable_findings_discarded": int,  # model claimed these but the
                                                       # prose_quote or diagram_quote
                                                       # didn't actually appear in the
                                                       # document -- dropped, not shown,
                                                       # but counted so this is never
                                                       # silently lossy
            "misattributed_findings_discarded": int,  # both quotes were individually
                                                       # real, but component_name --
                                                       # the thing supposedly shared
                                                       # between them -- didn't actually
                                                       # appear in both, meaning the two
                                                       # quotes were likely about
                                                       # different things
            "non_findings_filtered": int,             # model's own quotes verified,
                                                       # but its own explanation said
                                                       # there was no real disagreement
                                                       # -- see module docstring
            "omission_findings_filtered": int,        # model's own quotes verified,
                                                       # but its own explanation
                                                       # described the diagram merely
                                                       # OMITTING a detail the prose
                                                       # has, not stating something
                                                       # different -- see module
                                                       # docstring
            "consistent": bool,        # True iff findings is empty
        }
    """
    diagrams = find_diagrams_in_markdown(markdown)
    if not diagrams:
        return {
            "reviewed": False,
            "diagram_count": 0,
            "findings": [],
            "unverifiable_findings_discarded": 0,
            "misattributed_findings_discarded": 0,
            "non_findings_filtered": 0,
            "omission_findings_filtered": 0,
            "consistent": True,
        }

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        # Same fail-safe posture as everywhere else in this codebase that
        # depends on a key being present: don't crash the caller's whole
        # generation pipeline over an optional review step.
        return {
            "reviewed": False,
            "diagram_count": len(diagrams),
            "findings": [],
            "unverifiable_findings_discarded": 0,
            "misattributed_findings_discarded": 0,
            "non_findings_filtered": 0,
            "omission_findings_filtered": 0,
            "consistent": True,
            "error": "OPENAI_API_KEY not set",
        }

    numbered_diagrams = "\n\n".join(
        f"--- Diagram {i} ---\n{body}" for i, body in enumerate(diagrams, start=1)
    )
    user_prompt = (
        f"FULL DOCUMENT TEXT:\n{markdown}\n\n"
        f"DIAGRAMS IN THIS DOCUMENT, NUMBERED:\n{numbered_diagrams}\n\n"
        f"Call report_diagram_consistency now."
    )

    client = AsyncOpenAI(api_key=api_key)
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            max_tokens=1500,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "function", "function": {"name": "report_diagram_consistency"}},
        )
    except Exception as e:
        return {
            "reviewed": False,
            "diagram_count": len(diagrams),
            "findings": [],
            "unverifiable_findings_discarded": 0,
            "misattributed_findings_discarded": 0,
            "non_findings_filtered": 0,
            "omission_findings_filtered": 0,
            "consistent": True,
            "error": f"model call failed: {e}",
        }

    message = response.choices[0].message
    tool_calls = getattr(message, "tool_calls", None)
    if not tool_calls:
        return {
            "reviewed": False,
            "diagram_count": len(diagrams),
            "findings": [],
            "unverifiable_findings_discarded": 0,
            "misattributed_findings_discarded": 0,
            "non_findings_filtered": 0,
            "omission_findings_filtered": 0,
            "consistent": True,
            "error": "model did not call the required tool",
        }

    try:
        raw_findings = json.loads(tool_calls[0].function.arguments).get("findings", [])
    except (json.JSONDecodeError, AttributeError):
        return {
            "reviewed": False,
            "diagram_count": len(diagrams),
            "findings": [],
            "unverifiable_findings_discarded": 0,
            "misattributed_findings_discarded": 0,
            "non_findings_filtered": 0,
            "omission_findings_filtered": 0,
            "consistent": True,
            "error": "malformed tool call arguments",
        }

    verified: List[Dict] = []
    discarded = 0
    misattributed = 0
    filtered_non_findings = 0
    filtered_omissions = 0
    for finding in raw_findings:
        prose_quote = finding.get("prose_quote", "")
        diagram_quote = finding.get("diagram_quote", "")
        explanation = finding.get("explanation", "")
        component_name = finding.get("component_name", "")

        # Checked first, independent of quote verification: an entry whose
        # own explanation denies there's a real disagreement should never
        # count as a finding, regardless of whether its quotes are real.
        if _looks_like_non_finding(explanation):
            filtered_non_findings += 1
            continue

        # Checked next, same reasoning: an entry whose own explanation
        # describes the diagram merely OMITTING a detail (not stating
        # something different) is simplification, not a contradiction,
        # regardless of how real its quotes are.
        if _looks_like_omission_non_finding(explanation):
            filtered_omissions += 1
            continue

        # Both quotes must actually appear in the real document text --
        # the prose quote anywhere in the full markdown, the diagram quote
        # specifically within the diagram it claims to be from. A finding
        # failing this check is discarded outright: an unverifiable quote
        # is worse than no finding, since it would otherwise look exactly
        # as credible as a real one to whoever reads the quality gate output.
        diagram_index = finding.get("diagram_index")
        diagram_body = None
        if isinstance(diagram_index, int) and 1 <= diagram_index <= len(diagrams):
            diagram_body = diagrams[diagram_index - 1]

        prose_ok = _quote_appears_in(prose_quote, markdown)
        diagram_ok = diagram_body is not None and _quote_appears_in(diagram_quote, diagram_body)

        if not (prose_ok and diagram_ok):
            discarded += 1
            continue

        # Real bug this catches: both quotes can be individually verbatim
        # and still not be about the same thing -- a boundary statement
        # about one component paired against a diagram edge belonging to a
        # different one, related only by a shared incidental keyword. The
        # named component_name must actually appear in BOTH quotes, not
        # just somewhere in the document, before the finding is trusted.
        component_ok = (
            bool(component_name and component_name.strip())
            and _quote_appears_in(component_name, prose_quote)
            and _quote_appears_in(component_name, diagram_quote)
        )
        if not component_ok:
            misattributed += 1
            continue

        verified.append({
            "diagram_index": diagram_index,
            "component_name": component_name.strip(),
            "prose_quote": prose_quote.strip(),
            "diagram_quote": diagram_quote.strip(),
            "explanation": explanation.strip(),
        })

    return {
        "reviewed": True,
        "diagram_count": len(diagrams),
        "findings": verified,
        "unverifiable_findings_discarded": discarded,
        "misattributed_findings_discarded": misattributed,
        "non_findings_filtered": filtered_non_findings,
        "omission_findings_filtered": filtered_omissions,
        "consistent": len(verified) == 0,
    }


async def run_full_diagram_review(markdown: str, compare_against_markdown: Optional[str] = None) -> Dict:
    """
    The one function every skill (ba_skill.py, pe_skill.py, rfc_skill.py)
    actually calls -- runs every layer against `markdown` and combines them
    into a single result:

      Layer 1 (mermaid_structure.py, deterministic): does each diagram's own
      structure hold together -- real labels, connected graph, no
      contradictory duplicate edges, no dangling sequence-diagram
      activations.

      Layer 2 (this module, one model call): does each diagram agree with
      what the surrounding prose in the SAME document says.

      Layer 3 (mermaid_structure.py, deterministic, optional): only runs
      when `compare_against_markdown` is given -- does this document's
      diagram just restate a diagram already present in another document
      it was handed as context, instead of adding real depth. A real run
      showed this needed to run more places than just Software Architect
      vs the PRD: a PE diagram turned out to be a character-for-character
      copy of the BA diagram it was handed as input, because both stages'
      diagram instructions overlapped -- see pe_skill.py's own call site
      for why it now also passes the BRD here.

      Internal duplication check (mermaid_structure.py, deterministic,
      always runs): does this ONE document draw the same diagram twice
      under two different headings -- found for real in a PRD that drew
      an "Integration Map" and a "System Architecture Diagram" as two
      separate blocks that were structurally the same graph.

      Decision-point check (mermaid_structure.py, deterministic, always
      runs, informational only -- see overall_ok below): if this
      document's own prose states a role has a decision point, does at
      least one of its diagrams show an actual branch.

    Safe to call on a document with zero mermaid diagrams (every layer
    degrades to "nothing to check" rather than erroring), and cheap to call
    broadly: only Layer 2 costs a model call, and it skips itself entirely
    when there are no diagrams to review.
    """
    structural_findings = check_all_diagrams_structurally(markdown)
    structural_errors = [f for f in structural_findings if f["severity"] == "error"]

    similarity_findings: List[Dict] = []
    if compare_against_markdown:
        similarity_findings = check_diagram_similarity_against(markdown, compare_against_markdown)

    internal_duplication_findings = check_internal_diagram_duplication(markdown)
    decision_point_findings = check_decision_points_reflected(markdown)

    prose_consistency = await review_diagram_consistency(markdown)

    return {
        "structural_findings": structural_findings,
        "structural_ok": len(structural_errors) == 0,
        "similarity_findings": similarity_findings,
        "internal_duplication_findings": internal_duplication_findings,
        # Informational, not gating overall_ok -- deliberately coarse
        # (document-level, not matched per-role) per its own docstring, so
        # it's surfaced for a human to look at rather than treated as a
        # definitive failure the way real duplication or a structural error is.
        "decision_point_findings": decision_point_findings,
        "prose_consistency": prose_consistency,
        "overall_ok": (
            len(structural_errors) == 0
            and not similarity_findings
            and not internal_duplication_findings
            and prose_consistency.get("consistent", True)
        ),
    }
