"""
Shared Mermaid diagram validation, used by ba_skill.py, pe_skill.py, and
rfc_skill.py.

Consolidated into one function rather than three near-identical copies —
duplicated validation logic is exactly the kind of thing that silently
drifts, the same reasoning research_service.py's own docstring already
gives for why RFC roles share one module instead of five.

This exists because prompt-level guidance alone has already been observed,
on real runs, to not be followed 100% of the time:
- PE's Observability diagram used `--|Alert|` (no arrowhead) inconsistently
  with `-->|Metrics|` elsewhere in the same diagram, even with no
  contradicting guidance at all in that prompt (a real gap, since it turned
  out pe_skill.py's prompt had never gotten this guidance in the first
  place).
- Software Architect's diagram used unquoted parentheses in node labels
  (`CRM[CRM System (Extended)]`), breaking the whole diagram's parsing.
- DevOps has needed the same dotted/solid arrow-consistency guidance before.

Prompt guidance stays in place in every relevant system prompt (it does
help, and costs nothing) — but a quality gate that only checks "does this
look roughly like a diagram" doesn't catch any of these three, so the gate
can pass while the PDF silently falls back to raw code. This function
checks for the three specific known-bad patterns directly, so the gate
means something real when it says a diagram is present and valid, not just
that a ```mermaid fence exists somewhere in the text.

Each regex was tested against all three real bug patterns above AND every
real, confirmed-working diagram generated this session (BA, DevOps, UI/UX,
Software Architect) before being adopted, specifically to rule out false
positives on legitimate syntax:
- `id[(text)]` (the reserved cylinder/database shape) is correctly NOT
  flagged by _UNQUOTED_PAREN_LABEL_RE.
- `A ---|label| B` (the valid 3-dash "open link with label" form) is
  correctly NOT flagged by _BAD_ARROW_RE.
- `A -.->|label| B` (a correctly-closed dotted arrow) is correctly NOT
  flagged by _DOTTED_SOLID_MISMATCH_RE.
"""

import re
from typing import List

# Catches `--|` (exactly two dashes then a pipe, no arrowhead) without
# false-flagging the valid 3-dash open-link form `---|` -- the negative
# lookbehind specifically excludes being preceded by a third dash.
_BAD_ARROW_RE = re.compile(r"(?<!-)--\|")

# Catches a bracketed node label containing an unquoted `(...)` pair, e.g.
# CRM[CRM System (Extended)] -- without false-flagging the legitimate
# cylinder-shape syntax id[(text)] (excluded via the negative lookahead
# right after the opening bracket) or an already-quoted label (the
# character class excludes `"`, so a quoted label never starts matching).
_UNQUOTED_PAREN_LABEL_RE = re.compile(r'\[(?!\()([^\[\]"]*\([^\[\]]*\)[^\[\]]*)\]')

# Catches a dotted connector (`-.`) not immediately closed with `->` --
# e.g. `A -. "label" --> B` mixing a dotted start with a solid arrowhead.
# Does not flag a correctly-formed `-.->` since `->` follows immediately.
_DOTTED_SOLID_MISMATCH_RE = re.compile(r"-\.(?!->)")

# Catches the specific malformed variant actually seen on a real run:
# `A -. "label" .-> B` -- a bare quoted label sandwiched between two
# separate dotted-connector fragments, instead of the correct
# `A -.->|label| B` (single dotted arrow, label in pipes). This is a
# distinct, fixable case of the dotted/solid mismatch above -- kept
# separate so it can be rewritten into correct syntax, not just detected.
_DOTTED_LABEL_MALFORMED_RE = re.compile(r'-\.\s*"([^"]+)"\s*\.->')

# Catches a malformed shape mixing rhombus braces with a different
# bracket type inside -- e.g. `Config{["Config Management"]}` (square
# brackets) or `CI{("CI/CD Pipeline")}` (round parens). Neither is a valid
# Mermaid shape (real shapes: [text], (text), {text}, {{text}}, [[text]],
# [(text)], never a brace wrapping a different bracket type inside).
# Normalized to a plain quoted square-bracket label rather than guessing
# which real shape was intended.
#
# Quoted-content tried first, same principle mermaid_structure.py's
# _SHAPE_PATTERNS already uses and for the same reason: a real bug was
# found and fixed here because the label's own text contained a SECOND,
# nested paren -- `Rollback{("Rollback Trigger (Error > 0.1%)")}` -- and
# the original single restrictive character class excluded parens
# entirely, so it could never span past that inner "(Error > 0.1%)" to
# find the closing quote. That diagram silently failed to render in
# production (PDF fell back to showing raw code) because this exact node
# went un-fixed. The quoted pattern below allows ANY character between the
# quotes except another literal quote, so nested punctuation inside a
# properly quoted label no longer breaks the match; the unquoted fallback
# stays restrictive for the same reason mermaid_structure.py's does.
_MALFORMED_BRACE_BRACKET_RE = re.compile(r'\{[\[\(]\s*"([^"]*)"\s*[\]\)]\}')
_MALFORMED_BRACE_BRACKET_UNQUOTED_RE = re.compile(r'\{[\[\(]([^\[\]{}()"]*)[\]\)]\}')


def _fix_malformed_brace_bracket(block: str) -> str:
    fixed = _MALFORMED_BRACE_BRACKET_RE.sub(lambda m: f'["{m.group(1)}"]', block)
    return _MALFORMED_BRACE_BRACKET_UNQUOTED_RE.sub(lambda m: f'["{m.group(1)}"]', fixed)

# Catches a genuinely new failure class, confirmed on a real run appearing
# independently in three separate documents in the same run (BA, PE, and
# Software Architect all separately produced it for a Yes/No decision
# branch): mixing Mermaid's two DIFFERENT valid ways to label an edge on
# the SAME edge -- `A -- text --> B` (dash form) and `A -->|text| B` (pipe
# form) are each individually correct, but `A -- text -->|text2| B`
# combines both, which is not valid syntax and breaks the whole diagram's
# parsing (confirmed: the exact real broken line, isolated from everything
# else in its document, still failed to render in the final PDF). Fixed by
# merging both labels into one valid pipe label rather than arbitrarily
# discarding either one -- `C -- Yes -->|Send Data| D` becomes
# `C -->|Yes: Send Data| D`, preserving both pieces of information the
# model was trying to convey. Deliberately does NOT touch a dash-labeled
# edge with no trailing pipe (`C -- No --> F`) -- that form is already
# completely valid Mermaid on its own and must be left alone.
_MIXED_DASH_AND_PIPE_LABEL_RE = re.compile(r'--\s*([^-|>]+?)\s*-->\s*\|\s*([^|]*?)\s*\|')


def _fix_mixed_dash_and_pipe_label(block: str) -> str:
    return _MIXED_DASH_AND_PIPE_LABEL_RE.sub(
        lambda m: f'-->|{m.group(1).strip()}: {m.group(2).strip()}|', block
    )

# Catches a shape whose content mixes unquoted prefix text with an
# internal quoted suffix -- e.g. `C{Decision Node: "Risk Level High?"}`,
# confirmed on a real run alongside the mixed-label bug above, in the same
# diagram. A label is either quoted or not; a partial quote like this is
# ambiguous to a real Mermaid parser (where does the "real" label start?)
# and was still failing to render even after the mixed-label fix resolved
# everything else in that diagram. Fixed by normalizing to one fully-quoted
# label, covering the two shapes actually seen using this pattern
# (rhombus `{}` and rectangle `[]`) -- scoped to what's been observed
# rather than guessed at for every possible shape delimiter.
def _make_partial_quote_fixer(open_delim: str, close_delim: str):
    pattern = re.compile(
        re.escape(open_delim) + r'([^' + re.escape(open_delim) + re.escape(close_delim) + r'"]+)"([^"]*)"' + re.escape(close_delim)
    )
    def fix(text: str) -> str:
        return pattern.sub(lambda m: f'{open_delim}"{m.group(1).strip()} {m.group(2).strip()}"{close_delim}', text)
    return fix


_fix_partial_quote_rhombus = _make_partial_quote_fixer('{', '}')
_fix_partial_quote_rectangle = _make_partial_quote_fixer('[', ']')

# Catches a QUOTED string sitting in the dash-label position on a FORWARD
# arrow -- e.g. `A -- "REST API" --> B`. The dotted variant of this exact
# mistake (`A -. "label" .-> B`) was already fixed above; this is the same
# underlying error (a literal quote character isn't valid in that
# grammatical slot, for any of the three arrow styles) just never
# generalized past the one style it happened to be first observed on.
# Confirmed on a real run: a Software Architect diagram used this pattern
# on every single forward edge (solid arrows throughout), and none of them
# were caught by the dotted-only regex, which is why the whole diagram
# failed to render even though the dotted-label fix had already shipped.
# Fixed the same way as the dotted case: merge into the one proven-safe
# form, `A -->|label| B`.
_QUOTED_DASH_LABEL_FORWARD_RE = re.compile(
    r'(?<!<)(?P<pre>-\.|--|==)\s*"(?P<label>[^"]+)"\s*(?P<post>\.->|-->|==>)'
)
_QUOTED_DASH_LABEL_FORWARD_EXPECTED_POST = {'-.': '.->', '--': '-->', '==': '==>'}
_QUOTED_DASH_LABEL_FORWARD_CANONICAL = {'-.': '-.->', '--': '-->', '==': '==>'}


def _fix_quoted_dash_label_forward(block: str) -> str:
    def _repl(m: "re.Match") -> str:
        pre, post, label = m.group('pre'), m.group('post'), m.group('label').strip()
        if _QUOTED_DASH_LABEL_FORWARD_EXPECTED_POST.get(pre) != post:
            return m.group(0)
        return f'{_QUOTED_DASH_LABEL_FORWARD_CANONICAL[pre]}|{label}|'
    return _QUOTED_DASH_LABEL_FORWARD_RE.sub(_repl, block)


# The same quoted-dash-label mistake, but on a REVERSED arrow -- arrowhead
# at the START instead of the end, e.g. `A <-- "text" -- B`. Found on the
# same real run, in the same diagram, as the forward case above. Fixed
# differently and more conservatively than the forward case: rather than
# guess whether a reversed pipe-label form like `<--|label|--` is even
# valid Mermaid (genuinely uncertain, with no way to check against a real
# renderer), the entire statement is rewritten into the forward form
# instead, swapping which side is written first -- `A <-- "text" -- B`
# becomes `B -->|text| A`, the same relationship and the same label,
# expressed the one way every other fix in this file already trusts.
# Matches per-line (not per-block) since it needs the whole statement on
# one side of the reversed arrow, not just the punctuation immediately
# around it.
_REVERSED_QUOTED_DASH_LABEL_LINE_RE = re.compile(
    r'^(?P<indent>\s*)(?P<left>.+?)\s*<(?P<arrow>--|-\.|==)\s*"(?P<label>[^"]+)"\s*(?P<post>--|-\.|==)(?!>)\s*(?P<right>.+?)\s*$'
)
_REVERSED_QUOTED_DASH_LABEL_CANONICAL_FORWARD = {'--': '-->', '-.': '-.->', '==': '==>'}


def _fix_reversed_quoted_dash_label(block: str) -> str:
    fixed_lines = []
    for line in block.split("\n"):
        m = _REVERSED_QUOTED_DASH_LABEL_LINE_RE.match(line)
        if m and m.group('arrow') == m.group('post'):
            indent = m.group('indent')
            left, label, right = m.group('left').strip(), m.group('label').strip(), m.group('right').strip()
            arrow = _REVERSED_QUOTED_DASH_LABEL_CANONICAL_FORWARD[m.group('arrow')]
            fixed_lines.append(f'{indent}{right} {arrow}|{label}| {left}')
        else:
            fixed_lines.append(line)
    return "\n".join(fixed_lines)


# Catches a rhombus shape used as a bare node REFERENCE with no node id in
# front of it at all -- e.g. `--> {"Decision Point: Action Needed?"}` or a
# line that starts directly with `{"..."}`. Every real Mermaid shape needs
# an id attached (`NodeId{"text"}`, the same way `NodeId["text"]` needs
# one) -- a bare shape with nothing before it isn't a valid node reference,
# it's a syntax error, and it breaks the whole diagram's parsing the same
# way every other pattern in this file does. Confirmed on a real run this
# was likely caused by this project's own prompt guidance showing the
# shape syntax alone (`a rhombus {"text"} for a decision point`) without
# making the id-prefix requirement explicit -- the model correctly copied
# the shape punctuation but dropped the id. The prompt has been corrected
# too (see rfc_skill.py's UI/UX prompt), but this stays here as the real
# backstop: prompt guidance has already been proven, repeatedly in this
# file's own history, to not be followed 100% of the time on its own.
# Fixed by assigning each unique anonymous shape text a synthesized id
# (derived from its own words, e.g. "Decision Point: Action Needed?" ->
# "DecisionPointAction") and rewriting every occurrence of that exact text
# to use the same id consistently -- the same decision point is typically
# referenced multiple times in one diagram (once to reach it, once per
# outgoing branch), and all of them need to resolve to the same node.
_ANONYMOUS_RHOMBUS_RE = re.compile(r'(?<![A-Za-z0-9_])\{("(?:[^"\\]|\\.)*")\}')


def _slugify_for_node_id(text: str, existing_ids: set) -> str:
    words = re.findall(r'[A-Za-z0-9]+', text)[:3]
    base = ''.join(w.capitalize() for w in words) or 'Decision'
    candidate = base
    n = 1
    while candidate in existing_ids:
        n += 1
        candidate = f'{base}{n}'
    return candidate


def _fix_anonymous_rhombus_nodes(block: str) -> str:
    existing_ids = set(re.findall(r'\b([A-Za-z][A-Za-z0-9_]*)\b', block))
    text_to_id: dict = {}

    def _repl(m: "re.Match") -> str:
        quoted_text = m.group(1)
        if quoted_text not in text_to_id:
            label_text = quoted_text.strip('"')
            new_id = _slugify_for_node_id(label_text, existing_ids)
            existing_ids.add(new_id)
            text_to_id[quoted_text] = new_id
        return f'{text_to_id[quoted_text]}{{{quoted_text}}}'

    return _ANONYMOUS_RHOMBUS_RE.sub(_repl, block)


# Catches a `subgraph ... end` block closed with the wrong case -- `End`,
# `END`, etc. -- instead of lowercase `end`. Mermaid's reserved keywords
# are case-sensitive the same way `graph`/`subgraph` themselves are; a
# capitalized closer isn't recognized as closing the block at all, which
# breaks the whole diagram's parsing, not just that one subgraph.
# Confirmed on a real run: a diagram had two subgraph blocks, the first
# correctly closed with lowercase `end`, the second closed with `End` --
# same diagram, same author, just a typo on the second one, and the whole
# diagram failed to render as a result. Scoped narrowly to a line whose
# ENTIRE stripped content is the word "end" in any case -- this can't
# false-positive on a real node named something like "Legend" or
# "Weekend", since those have other letters on the same line, not just
# whitespace around the bare word.
_SUBGRAPH_END_CASE_RE = re.compile(r'^(\s*)end(\s*)$', re.IGNORECASE)


def _fix_subgraph_end_case(block: str) -> str:
    fixed_lines = []
    for line in block.split("\n"):
        m = _SUBGRAPH_END_CASE_RE.match(line)
        if m and line.strip() != "end":
            fixed_lines.append(f"{m.group(1)}end{m.group(2)}")
        else:
            fixed_lines.append(line)
    return "\n".join(fixed_lines)


# Catches a node whose rhombus shape content is itself another complete
# node declaration nested inside -- e.g.
# `Subscriber{Subscriber2{"Subscriber"}}`, a node named Subscriber whose
# shape content is a second, whole id+shape pair rather than plain label
# text. A shape's content is only ever meant to be a label, never another
# node declaration -- this looks like a generation glitch (two overlapping
# attempts at the same node reference) rather than any deliberate syntax
# choice, and it isn't valid Mermaid on either read. Fixed by collapsing to
# the OUTER id (the one the edge actually points at) with just the
# INNERMOST quoted text as a plain rectangle label, discarding the
# spurious nested id entirely -- the same "normalize to the safe generic
# form rather than guess which shape was really intended" approach
# already used for the malformed-brace-bracket fix. Scoped to a rhombus
# outer shape specifically, since that's the one real case seen; the inner
# shape is left flexible (rhombus, rectangle, or cylinder) since the
# nested id's own shape type isn't actually meaningful here regardless.
_NESTED_NODE_IN_RHOMBUS_RE = re.compile(
    r'(?P<outer_id>[A-Za-z0-9_]+)\{[A-Za-z0-9_]+(\{"(?P<label1>[^"]*)"\}|\["(?P<label2>[^"]*)"\]|\("(?P<label3>[^"]*)"\))\}'
)


def _fix_nested_node_in_rhombus(block: str) -> str:
    def _repl(m: "re.Match") -> str:
        label = m.group('label1') or m.group('label2') or m.group('label3')
        return f'{m.group("outer_id")}["{label}"]'
    return _NESTED_NODE_IN_RHOMBUS_RE.sub(_repl, block)

# Matches a pipe-delimited edge label so its contents can be cleaned --
# raw '>' or '<' inside a label is a real risk (those characters are
# themselves meaningful in arrow syntax), decorative leading/trailing
# dashes (seen on a real run: '|-Rollback Trigger: Error Rate >1%-|') add
# nothing and add risk, and unquoted parentheses inside a pipe label are a
# genuinely new failure class confirmed on a real run: a PRD's diagram had
# two pipe labels reading "REST API Call (Payment Data)" and "REST API
# Response (Transaction Status)", and the whole diagram fell back to raw
# code in the exported PDF. Confirmed against a second diagram in the same
# document that used no parentheses in any pipe label and rendered
# correctly -- the parens were the only difference between the one that
# failed and the one that didn't. Every other paren-related fix in this
# file has been about parens inside a BRACKETED node label, never a pipe
# label, so this is a distinct case rather than a duplicate of an existing
# one. Fixed by dropping the parenthesis characters themselves rather than
# wrapping in quotes -- unlike bracket labels, there's no confirmed
# evidence a pipe label supports quote-wrapping at all, so removing the
# punctuation is the safer fix: it can't introduce a new invalid pattern,
# and the label reads perfectly clearly without it ("REST API Call
# (Payment Data)" becomes "REST API Call Payment Data").
_PIPE_LABEL_RE = re.compile(r"\|([^|]*)\|")


def _clean_pipe_label(match: "re.Match") -> str:
    text = match.group(1).strip("-").strip()
    text = text.replace(">", "over ").replace("<", "under ")
    text = text.replace("(", "").replace(")", "")
    text = re.sub(r"\s+", " ", text).strip()
    return f"|{text}|"


def sanitize_mermaid_block(block: str) -> str:
    """Deterministically rewrites known-bad syntax patterns into their
    correct form. Applied AFTER the model has already decided everything
    about content -- what to draw, how many nodes, what the labels say --
    so this never touches structure, wording, or the model's actual design
    decisions, only punctuation:
    1. '--|label|' (missing arrowhead) -> '-->|label|'
    2. A raw '>'/'<' or decorative leading/trailing '-' inside a pipe
       label -> cleaned, meaning preserved (">1%" becomes "over 1%", not
       deleted).
    3. An unquoted parenthetical inside a bracketed node label -> wrapped
       in quotes.
    4. 'A -. "label" .-> B' (bare quoted label between two dotted
       fragments) -> 'A -.->|label| B' (the correct single dotted arrow
       with a piped label).
    5. A malformed '{["text"]}' or '{("text")}' shape (rhombus braces
       wrapping a different bracket type inside, not a real Mermaid shape)
       -> normalized to '["text"]'.
    Confirmed safe against every already-correct diagram generated this
    session (zero unwanted changes) and confirmed to fix every real broken
    diagram found on a live run (BA, PE, Software Architect, DevOps --
    twice now, since DevOps has hit three distinct syntax failure classes
    across different runs).
    One known pattern this does NOT fix, by design: a different bracket
    type nested inside a round-paren node's text (e.g.
    'Stage(Text [Extra])') -- rare enough (seen once) and structurally
    different enough that a safe general rewrite isn't confident yet;
    flagged in the DevOps prompt instead of silently rewritten.
    """
    block = _BAD_ARROW_RE.sub("-->|", block)
    block = _DOTTED_LABEL_MALFORMED_RE.sub(lambda m: f'-.->|{m.group(1)}|', block)
    block = _PIPE_LABEL_RE.sub(_clean_pipe_label, block)
    block = _UNQUOTED_PAREN_LABEL_RE.sub(lambda m: f'["{m.group(1)}"]', block)
    block = _fix_malformed_brace_bracket(block)
    block = _fix_mixed_dash_and_pipe_label(block)
    block = _fix_partial_quote_rhombus(block)
    block = _fix_partial_quote_rectangle(block)
    block = _fix_reversed_quoted_dash_label(block)
    block = _fix_quoted_dash_label_forward(block)
    block = _fix_anonymous_rhombus_nodes(block)
    block = _fix_subgraph_end_case(block)
    block = _fix_nested_node_in_rhombus(block)
    return block


def sanitize_mermaid_diagrams(markdown: str) -> str:
    """Applies sanitize_mermaid_block to every ```mermaid fence in `markdown`
    and returns the full document with each block replaced in place. Text
    outside mermaid fences is untouched. Safe to call on documents with zero
    mermaid blocks (returns the input unchanged)."""
    def _replace(match: "re.Match") -> str:
        return "```mermaid\n" + sanitize_mermaid_block(match.group(1)) + "\n```"
    return re.sub(r"```mermaid\n(.*?)\n```", _replace, markdown, flags=re.DOTALL)


def find_mermaid_syntax_risks(block: str) -> List[str]:
    """Returns a list of human-readable problem descriptions for one
    mermaid code block's content (no fence markers), or an empty list if
    none of the known patterns are present. Callers needing a plain
    bool should use validate_mermaid_diagrams() below instead."""
    risks = []
    if _BAD_ARROW_RE.search(block):
        risks.append("an edge uses '--|label|' with no arrowhead (should be '-->|label|' or '---|label|') -- this breaks the whole diagram's rendering, not just that edge")
    if _UNQUOTED_PAREN_LABEL_RE.search(block):
        risks.append("a node label has unquoted parentheses, e.g. Name[Text (Extra)] -- wrap the whole label in quotes, e.g. Name[\"Text (Extra)\"]")
    if _DOTTED_SOLID_MISMATCH_RE.search(block):
        risks.append("a dotted connector ('-.') isn't closed with '->' -- a dotted start mixed with a solid arrowhead, or a bare quoted label between two dotted fragments, is invalid syntax")
    if _MALFORMED_BRACE_BRACKET_RE.search(block) or _MALFORMED_BRACE_BRACKET_UNQUOTED_RE.search(block):
        risks.append("a node uses a malformed '{[text]}' or '{(text)}' shape (rhombus braces wrapping a different bracket type inside) -- not a real Mermaid shape")
    if _MIXED_DASH_AND_PIPE_LABEL_RE.search(block):
        risks.append("an edge mixes the dash-label style ('-- text -->') with a trailing pipe label ('|text|') on the same edge -- pick one labeling style, not both")
    if _QUOTED_DASH_LABEL_FORWARD_RE.search(block) or _REVERSED_QUOTED_DASH_LABEL_LINE_RE.search(block):
        risks.append("an edge has a quoted string sitting in the dash-label position (e.g. '-- \"text\" -->' or '<-- \"text\" --') -- not valid Mermaid; the label belongs in pipes on a single arrow token")
    if _ANONYMOUS_RHOMBUS_RE.search(block):
        risks.append("a rhombus shape like {\"text\"} is used as a node reference with no node id in front of it -- every shape needs an id, e.g. NodeId{\"text\"}, not a bare shape on its own")
    if any(_SUBGRAPH_END_CASE_RE.match(line) and line.strip() != "end" for line in block.split("\n")):
        risks.append("a subgraph is closed with the wrong case (e.g. 'End' or 'END' instead of lowercase 'end') -- Mermaid's 'end' keyword is case-sensitive, and a wrong-case closer breaks the whole diagram's parsing, not just that subgraph")
    if _NESTED_NODE_IN_RHOMBUS_RE.search(block):
        risks.append("a node's shape contains another complete node declaration nested inside it (e.g. Outer{Inner{\"text\"}}) -- a shape's content must be plain label text, never another id+shape pair")
    return risks


def validate_mermaid_diagrams(markdown: str, min_lines: int = 4) -> bool:
    """True if every ```mermaid block in `markdown` has real content and
    matches none of the three known failure patterns above. False (never
    an exception) on any problem -- this is a quality-gate signal, not
    something calling code should crash on. False also if there are no
    mermaid blocks at all -- callers that don't require one should check
    for that separately rather than relying on this function's return
    value alone."""
    blocks = re.findall(r"```mermaid\n(.*?)\n```", markdown, re.DOTALL)
    if not blocks:
        return False

    for block in blocks:
        lines = [l for l in block.strip().split("\n") if l.strip()]
        if len(lines) < min_lines:
            return False
        if not any(sym in block for sym in ["->", "-->", "|"]):
            return False
        if find_mermaid_syntax_risks(block):
            return False

    return True
