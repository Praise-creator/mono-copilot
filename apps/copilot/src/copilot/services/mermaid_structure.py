import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class ParsedNode:
    node_id: str
    label: Optional[str] = None
    declared: bool = False
    shape_attempted: bool = False
    first_line_no: int = 0


@dataclass
class ParsedEdge:
    source: str
    target: str
    label: Optional[str]
    style: str
    line_no: int
    raw_line: str


@dataclass
class ParsedFlowchart:
    diagram_type: str = "flowchart"
    nodes: Dict[str, ParsedNode] = field(default_factory=dict)
    edges: List[ParsedEdge] = field(default_factory=list)
    parse_ok: bool = True


@dataclass
class SequenceMessage:
    source: str
    target: str
    text: str
    activates: Optional[str]
    deactivates: Optional[str]
    line_no: int
    raw_line: str


@dataclass
class ParsedSequenceDiagram:
    diagram_type: str = "sequence"
    participants: Dict[str, str] = field(default_factory=dict)
    messages: List[SequenceMessage] = field(default_factory=list)
    parse_ok: bool = True


@dataclass
class StructuralFinding:
    check: str
    severity: str
    message: str
    evidence: str


_NODE_ID = r'[A-Za-z0-9_]+'

_SHAPE_PATTERNS = [
    ("cylinder", re.compile(r'\[\(\s*"(?P<label>[^"]*)"\s*\)\]')),
    ("cylinder", re.compile(r'\[\(\s*(?P<label>[^"\[\]()]*)\s*\)\]')),
    ("circle", re.compile(r'\(\(\s*"(?P<label>[^"]*)"\s*\)\)')),
    ("circle", re.compile(r'\(\(\s*(?P<label>[^"()]*)\s*\)\)')),
    ("hexagon", re.compile(r'\{\{\s*"(?P<label>[^"]*)"\s*\}\}')),
    ("hexagon", re.compile(r'\{\{\s*(?P<label>[^"{}]*)\s*\}\}')),
    ("subroutine", re.compile(r'\[\[\s*"(?P<label>[^"]*)"\s*\]\]')),
    ("subroutine", re.compile(r'\[\[\s*(?P<label>[^"\[\]]*)\s*\]\]')),
    ("rhombus", re.compile(r'\{\s*"(?P<label>[^"]*)"\s*\}')),
    ("rhombus", re.compile(r'\{\s*(?P<label>[^"{}]*)\s*\}')),
    ("rectangle", re.compile(r'\[\s*"(?P<label>[^"]*)"\s*\]')),
    ("rectangle", re.compile(r'\[\s*(?P<label>[^"\[\]]*)\s*\]')),
    ("rounded", re.compile(r'\(\s*"(?P<label>[^"]*)"\s*\)')),
    ("rounded", re.compile(r'\(\s*(?P<label>[^"()]*)\s*\)')),
]

_NODE_WITH_OPTIONAL_SHAPE_RE = re.compile(
    r'(?P<id>' + _NODE_ID + r')'
    r'(?P<shape>'
    r'\[\(\s*"[^"]*"\s*\)\]|\[\([^)]*\)\]'
    r'|\(\(\s*"[^"]*"\s*\)\)|\(\([^)]*\)\)'
    r'|\{\{\s*"[^"]*"\s*\}\}|\{\{[^}]*\}\}'
    r'|\[\[\s*"[^"]*"\s*\]\]|\[\[[^\]]*\]\]'
    r'|\{\s*"[^"]*"\s*\}|\{[^{}]*\}'
    r'|\[\s*"[^"]*"\s*\]|\[[^\[\]]*\]'
    r'|\(\s*"[^"]*"\s*\)|\([^()]*\)'
    r')?'
)

_ARROW_RE = re.compile(
    r'(?P<style>-\.->|-\.-|==>|===|-->|---)'
    r'(?:\s*\|\s*(?P<label>[^|]*?)\s*\|)?'
)

# subgraph/end are real Mermaid grammar for grouping nodes into a visual
# boundary (e.g. a deployment region) -- now actively encouraged by
# rfc_skill.py's Software Architect prompt (see that file's own comment on
# why: showing deployment boundaries is the concrete way that RFC's diagram
# adds real structure beyond the PRD's, not just richer labels on the same
# graph). Skipped here the same way style/classDef lines already are:
# nodes and edges INSIDE a subgraph use identical syntax to nodes outside
# one, so this parser already reads them correctly -- it only needed to
# stop treating the `subgraph "..."` and `end` lines themselves as if they
# were declaring bare nodes named "subgraph" and "end". Confirmed this was
# a real gap before shipping the prompt encouraging subgraphs: without this
# skip, a single `subgraph "Cloud (Nigeria region)"` line registered FOUR
# phantom undeclared nodes ("subgraph", "Cloud", "Nigeria", "region").
_STYLE_LINE_RE = re.compile(r'^\s*(style|classDef|class|click|linkStyle|subgraph)\b')
# Case-sensitive on purpose, unlike most other patterns in this file --
# Mermaid's `end` keyword is case-sensitive the same way `graph`/
# `subgraph` themselves are, so a capitalized `End` genuinely isn't
# recognized as closing the block by a real renderer. This was
# case-insensitive here once, which meant this checker was silently MORE
# lenient than the actual renderer -- accepting `End` as a valid closer
# when real Mermaid wouldn't, which is worse than not checking at all,
# since it gives false confidence. The sanitizer in mermaid_validation.py
# now fixes a wrong-case closer before this checker ever sees it in the
# real pipeline; this tightening keeps this file's own understanding
# honest even when called on unsanitized content directly.
_SUBGRAPH_END_RE = re.compile(r'^\s*end\s*$')
_HEADER_RE = re.compile(r'^\s*(graph|flowchart)\s+(TD|TB|LR|RL|BT)\b', re.IGNORECASE)

_DASH_LABEL_NORMALIZE_RE = re.compile(
    r'(?P<pre>-\.|--|==)\s+(?P<label>[^\-.=|>{}\[\]()]+?)\s+(?P<post>\.->|-->|==>)'
)
_DASH_LABEL_CANONICAL_STYLE = {'-.': '-.->', '--': '-->', '==': '==>'}
_DASH_LABEL_EXPECTED_POST = {'-.': '.->', '--': '-->', '==': '==>'}


def _normalize_dash_labels(line: str) -> str:
    def _repl(m: "re.Match") -> str:
        pre, post, label = m.group('pre'), m.group('post'), m.group('label').strip()
        if _DASH_LABEL_EXPECTED_POST.get(pre) != post:
            return m.group(0)
        return f'{_DASH_LABEL_CANONICAL_STYLE[pre]}|{label}|'
    return _DASH_LABEL_NORMALIZE_RE.sub(_repl, line)


def _split_respecting_quotes(text: str, sep: str = '&') -> List[str]:
    parts: List[str] = []
    current: List[str] = []
    in_quotes = False
    for ch in text:
        if ch == '"':
            in_quotes = not in_quotes
            current.append(ch)
        elif ch == sep and not in_quotes:
            parts.append(''.join(current))
            current = []
        else:
            current.append(ch)
    parts.append(''.join(current))
    return parts


def _extract_shape_label(shape_text: str) -> Optional[str]:
    if not shape_text:
        return None
    for _name, pattern in _SHAPE_PATTERNS:
        m = pattern.fullmatch(shape_text)
        if m:
            label = m.group("label").strip()
            return label or None
    return None


def _register_node(fc: ParsedFlowchart, node_id: str, shape_text: Optional[str], line_no: int) -> None:
    label = _extract_shape_label(shape_text) if shape_text else None
    attempted = bool(shape_text)
    existing = fc.nodes.get(node_id)
    if existing is None:
        fc.nodes[node_id] = ParsedNode(
            node_id=node_id,
            label=label,
            declared=label is not None,
            shape_attempted=attempted,
            first_line_no=line_no,
        )
    else:
        if attempted and not existing.shape_attempted:
            existing.shape_attempted = True
        if label is not None and not existing.declared:
            existing.label = label
            existing.declared = True


def parse_flowchart(body: str) -> ParsedFlowchart:
    fc = ParsedFlowchart()
    lines = body.split("\n")

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if _HEADER_RE.match(line):
            continue
        if _STYLE_LINE_RE.match(line):
            continue
        if _SUBGRAPH_END_RE.match(line):
            continue

        line = _normalize_dash_labels(line)

        arrow_matches = list(_ARROW_RE.finditer(line))
        arrow_spans = [(m.start(), m.end()) for m in arrow_matches]

        def _inside_an_arrow(pos: int) -> bool:
            return any(start <= pos < end for start, end in arrow_spans)

        node_occurrences: List[Tuple[str, Optional[str], int]] = []
        for m in _NODE_WITH_OPTIONAL_SHAPE_RE.finditer(line):
            if _inside_an_arrow(m.start()):
                continue
            node_occurrences.append((m.group("id"), m.group("shape"), m.start()))
            _register_node(fc, m.group("id"), m.group("shape"), line_no)

        if not arrow_matches:
            continue

        positions = sorted(node_occurrences, key=lambda t: t[2])
        for i, arrow_m in enumerate(arrow_matches):
            before = [p for p in positions if p[2] < arrow_m.start()]
            if not before:
                continue
            source_id = before[-1][0]

            seg_end = arrow_matches[i + 1].start() if i + 1 < len(arrow_matches) else len(line)
            segment = line[arrow_m.end():seg_end]
            for target_part in _split_respecting_quotes(segment, '&'):
                target_m = _NODE_WITH_OPTIONAL_SHAPE_RE.search(target_part)
                if not target_m:
                    continue
                target_id = target_m.group("id")
                _register_node(fc, target_id, target_m.group("shape"), line_no)
                style = arrow_m.group("style")
                edge_style = (
                    "dotted" if style.startswith("-.") else
                    "thick" if style.startswith("=") else
                    "solid"
                )
                label = arrow_m.group("label")
                fc.edges.append(ParsedEdge(
                    source=source_id,
                    target=target_id,
                    label=label.strip() if label else None,
                    style=edge_style,
                    line_no=line_no,
                    raw_line=line,
                ))

    return fc


_PARTICIPANT_RE = re.compile(r'^\s*(participant|actor)\s+(?P<id>\S+)(?:\s+as\s+(?P<alias>.+))?\s*$', re.IGNORECASE)
_ACTIVATE_STMT_RE = re.compile(r'^\s*activate\s+(?P<id>\S+)\s*$', re.IGNORECASE)
_DEACTIVATE_STMT_RE = re.compile(r'^\s*deactivate\s+(?P<id>\S+)\s*$', re.IGNORECASE)
_MESSAGE_RE = re.compile(
    r'^\s*(?P<source>[A-Za-z0-9_]+)\s*'
    r'(?P<arrow>-->>|->>|--x|-x|-->|->)'
    r'(?P<sign>[+-])?\s*'
    r'(?P<target>[A-Za-z0-9_]+)\s*:\s*(?P<text>.*)$'
)
_SEQ_HEADER_RE = re.compile(r'^\s*sequenceDiagram\b', re.IGNORECASE)


def parse_sequence_diagram(body: str) -> ParsedSequenceDiagram:
    seq = ParsedSequenceDiagram()
    lines = body.split("\n")

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if _SEQ_HEADER_RE.match(line):
            continue

        p_match = _PARTICIPANT_RE.match(line)
        if p_match:
            pid = p_match.group("id")
            alias = p_match.group("alias")
            seq.participants[pid] = (alias or pid).strip()
            continue

        act_match = _ACTIVATE_STMT_RE.match(line)
        if act_match:
            seq.messages.append(SequenceMessage(
                source=act_match.group("id"), target=act_match.group("id"),
                text="(activate)", activates=act_match.group("id"), deactivates=None,
                line_no=line_no, raw_line=line,
            ))
            continue

        deact_match = _DEACTIVATE_STMT_RE.match(line)
        if deact_match:
            seq.messages.append(SequenceMessage(
                source=deact_match.group("id"), target=deact_match.group("id"),
                text="(deactivate)", activates=None, deactivates=deact_match.group("id"),
                line_no=line_no, raw_line=line,
            ))
            continue

        msg_match = _MESSAGE_RE.match(line)
        if msg_match:
            source = msg_match.group("source")
            target = msg_match.group("target")
            sign = msg_match.group("sign")
            seq.participants.setdefault(source, source)
            seq.participants.setdefault(target, target)
            activates = target if sign == "+" else None
            deactivates = source if sign == "-" else None
            seq.messages.append(SequenceMessage(
                source=source, target=target, text=msg_match.group("text"),
                activates=activates, deactivates=deactivates,
                line_no=line_no, raw_line=line,
            ))
            continue

    return seq


def _is_sequence_diagram(body: str) -> bool:
    return bool(_SEQ_HEADER_RE.search(body))


def parse_mermaid_block(body: str):
    if _is_sequence_diagram(body):
        return parse_sequence_diagram(body)
    return parse_flowchart(body)


# A pipe label must be opened AND closed on the same line -- `A -->|label| B`.
# An odd number of pipes on a line that has an arrow means the label was
# never closed, which breaks the whole diagram's parsing.
#
# Confirmed on a real run, and deliberately DETECTED-ONLY rather than
# auto-repaired, unlike almost everything in mermaid_validation.py. The
# real case was one logical statement torn across a line break mid-label:
#
#   Subscriber_Detail -->|Decision{"Assess Offers Based on Churn Risk"}
#   Decision: Retention Offer| Send_Offer[("Send Retention Offer")]
#
# The model started writing an edge with the pipe label "Decision:
# Retention Offer", switched mid-label into emitting a node declaration
# (`Decision{"Assess Offers..."}`), broke the line, then resumed with the
# rest of the original label and the real target. The result has two
# genuinely different readings -- was the decision node meant to be
# declared separately and the edge labeled "Retention Offer", or was the
# whole thing meant to be one edge? -- and there is no way to recover the
# intent unambiguously from the text. Every auto-fix in this codebase so
# far had exactly one safe normalization; this one does not, so guessing
# would risk silently shipping a diagram that says something the model
# never meant. Reported as an "error" so the quality gate fails and the
# document regenerates instead.
_UNBALANCED_PIPE_SKIP_RE = re.compile(
    r'^\s*(style|classDef|class|click|linkStyle|subgraph|graph|flowchart|end)\b',
    re.IGNORECASE,
)


def _check_unbalanced_pipe_labels(body: str) -> List[StructuralFinding]:
    findings = []
    for line_no, raw_line in enumerate(body.split("\n"), start=1):
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if _UNBALANCED_PIPE_SKIP_RE.match(line):
            continue
        if line.count("|") % 2 != 0:
            findings.append(StructuralFinding(
                check="unbalanced_pipe_label",
                severity="error",
                message=(
                    f"Line {line_no} has an odd number of '|' characters -- a pipe edge "
                    f"label must be opened and closed on the same line (`A -->|label| B`). "
                    f"An unclosed pipe label breaks the whole diagram's parsing, not just "
                    f"this line. This usually means one statement got split across a line "
                    f"break mid-label, which has no single safe automatic repair -- the "
                    f"diagram needs regenerating rather than patching."
                ),
                evidence=f"line {line_no}: {line}",
            ))
    return findings


def _check_undeclared_nodes(fc: ParsedFlowchart) -> List[StructuralFinding]:
    findings = []
    for node in fc.nodes.values():
        if node.declared:
            continue
        if node.shape_attempted:
            findings.append(StructuralFinding(
                check="malformed_shape_syntax",
                severity="error",
                message=(
                    f"Node '{node.node_id}' has shape syntax that isn't valid Mermaid -- "
                    f"most likely mixing two different delimiter types in one shape "
                    f"(e.g. a rhombus {{ combined with round parens ( ). A real Mermaid "
                    f"shape uses exactly one delimiter pair. This is very likely to break "
                    f"this node's rendering, not just look plain."
                ),
                evidence=f"line {node.first_line_no}: attempted shape syntax didn't match any valid Mermaid shape",
            ))
        else:
            findings.append(StructuralFinding(
                check="undeclared_node",
                severity="warning",
                message=(
                    f"Node '{node.node_id}' is used in an edge but never given a real "
                    f"label anywhere in this diagram -- it will render showing the raw "
                    f"id '{node.node_id}', not a readable name."
                ),
                evidence=f"line {node.first_line_no}: first referenced without a label here",
            ))
    return findings


def _check_disconnected_components(fc: ParsedFlowchart) -> List[StructuralFinding]:
    if len(fc.nodes) <= 1:
        return []

    parent = {node_id: node_id for node_id in fc.nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for edge in fc.edges:
        if edge.source in parent and edge.target in parent:
            union(edge.source, edge.target)

    components: Dict[str, List[str]] = {}
    for node_id in fc.nodes:
        components.setdefault(find(node_id), []).append(node_id)

    if len(components) <= 1:
        return []

    groups = sorted(components.values(), key=len, reverse=True)
    groups_desc = "; ".join("{" + ", ".join(sorted(g)) + "}" for g in groups)
    return [StructuralFinding(
        check="disconnected_components",
        severity="error",
        message=(
            f"This diagram draws {len(groups)} separate, never-connected groups of "
            f"nodes instead of one connected diagram -- likely a missing edge between "
            f"them, not an intentional design."
        ),
        evidence=groups_desc,
    )]


def _check_multiple_unlinked_entry_points(fc: ParsedFlowchart) -> List[StructuralFinding]:
    if len(fc.nodes) <= 1:
        return []

    in_degree: Dict[str, int] = {node_id: 0 for node_id in fc.nodes}
    for edge in fc.edges:
        if edge.target in in_degree:
            in_degree[edge.target] += 1

    roots = sorted(node_id for node_id, count in in_degree.items() if count == 0)
    if len(roots) <= 1:
        return []

    return [StructuralFinding(
        check="multiple_unlinked_entry_points",
        severity="warning",
        message=(
            f"{len(roots)} nodes have no incoming edge at all ({', '.join(roots)}) -- "
            f"each one is a place the diagram just starts, with nothing shown "
            f"triggering it. If these are meant to be one pipeline, one of them "
            f"is probably missing the edge that actually connects it to the rest; "
            f"if they're genuinely independent starting points, that's fine as is."
        ),
        evidence=f"nodes with in-degree 0: {', '.join(roots)}",
    )]


def _check_conflicting_duplicate_edges(fc: ParsedFlowchart) -> List[StructuralFinding]:
    by_pair: Dict[Tuple[str, str], List[ParsedEdge]] = {}
    for edge in fc.edges:
        by_pair.setdefault((edge.source, edge.target), []).append(edge)

    findings = []
    for (source, target), edges in by_pair.items():
        if len(edges) < 2:
            continue
        signatures = {(e.style, e.label) for e in edges}
        if len(signatures) < 2:
            continue
        lines = ", ".join(f"line {e.line_no} ({e.style}, label={e.label!r})" for e in edges)
        findings.append(StructuralFinding(
            check="conflicting_duplicate_edge",
            severity="error",
            message=(
                f"'{source}' -> '{target}' is drawn {len(edges)} different ways in the "
                f"same diagram, with different style or label each time -- pick one "
                f"relationship, not several disagreeing ones."
            ),
            evidence=lines,
        ))
    return findings


def _check_unbalanced_activations(seq: ParsedSequenceDiagram) -> List[StructuralFinding]:
    counts: Dict[str, int] = {}
    first_activation_line: Dict[str, int] = {}
    findings = []

    for msg in seq.messages:
        if msg.activates:
            counts[msg.activates] = counts.get(msg.activates, 0) + 1
            first_activation_line.setdefault(msg.activates, msg.line_no)
        if msg.deactivates:
            current = counts.get(msg.deactivates, 0)
            if current <= 0:
                findings.append(StructuralFinding(
                    check="deactivation_without_activation",
                    severity="error",
                    message=(
                        f"'{msg.deactivates}' is deactivated at line {msg.line_no} but was "
                        f"never activated first."
                    ),
                    evidence=msg.raw_line,
                ))
            else:
                counts[msg.deactivates] = current - 1

    for participant, remaining in counts.items():
        if remaining > 0:
            findings.append(StructuralFinding(
                check="unclosed_activation",
                severity="error",
                message=(
                    f"'{participant}' is activated (line {first_activation_line.get(participant)}) "
                    f"but never deactivated anywhere in this diagram -- it will show a "
                    f"dangling activation bar with no matching close."
                ),
                evidence=f"activated at line {first_activation_line.get(participant)}, never closed",
            ))
    return findings


_MAX_COMFORTABLE_NODES = 12
_MAX_COMFORTABLE_LABEL_LENGTH = 55
_MAX_COMFORTABLE_NODE_DEGREE = 6
_MAX_COMFORTABLE_PARTICIPANTS = 8
# A left-to-right diagram lays its longest chain out horizontally, so the
# rendered image gets wider with every node in that chain -- and when it's
# scaled down to fit a PDF page width, everything shrinks with it. Grounded
# in real measured output rather than picked arbitrarily: the one real
# diagram that came out genuinely too small to read was `graph LR` with a
# 9-node longest chain, while every real diagram that rendered comfortably
# was `graph TD` with a longest chain of 6 or fewer (measured: DevOps 6,
# BA 5, PE architecture 4). 7 sits just above every known-good case and
# below the one known-bad case. Only applies to LR/RL diagrams -- a long
# chain in a TD/TB diagram grows the image DOWNWARD, which doesn't compete
# with page width and hasn't caused a readability problem in any real run.
_MAX_COMFORTABLE_HORIZONTAL_CHAIN = 7

_HORIZONTAL_DIRECTION_RE = re.compile(r'^\s*(graph|flowchart)\s+(LR|RL)\b', re.IGNORECASE)


def _longest_chain_length(fc: ParsedFlowchart) -> int:
    """Longest simple directed path through the flowchart, in node count.
    Cycle-safe: a node already on the current path is never revisited, so a
    feedback edge (very common in these pipeline diagrams -- e.g. a rollback
    edge pointing back upstream) can't cause infinite recursion."""
    if not fc.edges:
        return len(fc.nodes)
    adjacency: Dict[str, List[str]] = {}
    for edge in fc.edges:
        adjacency.setdefault(edge.source, []).append(edge.target)

    def walk(node_id: str, on_path: Set[str]) -> int:
        best = 1
        for nxt in adjacency.get(node_id, []):
            if nxt in on_path:
                continue
            best = max(best, 1 + walk(nxt, on_path | {nxt}))
        return best

    return max(walk(n, {n}) for n in fc.nodes) if fc.nodes else 0


def _check_horizontal_chain_too_long(body: str, fc: ParsedFlowchart) -> List[StructuralFinding]:
    if not _HORIZONTAL_DIRECTION_RE.match(body.strip().split("\n")[0] if body.strip() else ""):
        return []
    chain = _longest_chain_length(fc)
    if chain <= _MAX_COMFORTABLE_HORIZONTAL_CHAIN:
        return []
    return [StructuralFinding(
        check="horizontal_chain_too_long",
        severity="warning",
        message=(
            f"This is a left-to-right diagram whose longest chain is {chain} nodes, so it "
            f"renders as one very wide row -- when scaled to fit a page width the text "
            f"becomes too small to read (this happened for real at {chain} nodes). Either "
            f"switch to top-down (`graph TD`), which grows downward instead of competing "
            f"with page width, or split the pipeline into two smaller diagrams. Real "
            f"diagrams in this project that rendered comfortably were top-down with a "
            f"longest chain of 6 or fewer."
        ),
        evidence=f"left-to-right direction with a {chain}-node longest chain",
    )]


def _check_diagram_complexity(fc: ParsedFlowchart) -> List[StructuralFinding]:
    if len(fc.nodes) <= _MAX_COMFORTABLE_NODES:
        return []
    return [StructuralFinding(
        check="diagram_too_large",
        severity="warning",
        message=(
            f"This diagram has {len(fc.nodes)} nodes -- comfortably readable diagrams "
            f"in this project's own real output have stayed under {_MAX_COMFORTABLE_NODES}. "
            f"Consider splitting this into two smaller, focused diagrams (e.g. one "
            f"showing the main flow, one showing a sub-flow or exception path) rather "
            f"than one diagram trying to show everything at once."
        ),
        evidence=f"{len(fc.nodes)} nodes: {', '.join(sorted(fc.nodes.keys()))}",
    )]


def _check_long_labels(fc: ParsedFlowchart) -> List[StructuralFinding]:
    findings = []
    for node in fc.nodes.values():
        if node.label and len(node.label) > _MAX_COMFORTABLE_LABEL_LENGTH:
            findings.append(StructuralFinding(
                check="label_too_long",
                severity="warning",
                message=(
                    f"Node '{node.node_id}' has a {len(node.label)}-character label -- "
                    f"likely to wrap awkwardly or overflow its box when rendered. "
                    f"Consider a shorter label, moving detail into the surrounding prose instead."
                ),
                evidence=f"line {node.first_line_no}: \"{node.label}\"",
            ))
    for edge in fc.edges:
        if edge.label and len(edge.label) > _MAX_COMFORTABLE_LABEL_LENGTH:
            findings.append(StructuralFinding(
                check="label_too_long",
                severity="warning",
                message=(
                    f"The edge '{edge.source}' -> '{edge.target}' has a "
                    f"{len(edge.label)}-character label -- likely to render as a long "
                    f"floating strip of text that's hard to associate with its arrow. "
                    f"Consider a shorter label."
                ),
                evidence=f"line {edge.line_no}: \"{edge.label}\"",
            ))
    return findings


def _check_high_degree_nodes(fc: ParsedFlowchart) -> List[StructuralFinding]:
    if not fc.edges:
        return []
    degree: Dict[str, int] = {node_id: 0 for node_id in fc.nodes}
    for edge in fc.edges:
        if edge.source in degree:
            degree[edge.source] += 1
        if edge.target in degree:
            degree[edge.target] += 1

    findings = []
    for node_id, count in degree.items():
        if count > _MAX_COMFORTABLE_NODE_DEGREE:
            findings.append(StructuralFinding(
                check="node_too_highly_connected",
                severity="warning",
                message=(
                    f"'{node_id}' has {count} edges connected to it -- likely to render "
                    f"as a hub with many crossing lines. If this is a genuine central "
                    f"component that's fine, but consider whether some of these "
                    f"relationships belong in a separate, more focused diagram instead."
                ),
                evidence=f"'{node_id}': {count} connected edges",
            ))
    return findings


def _check_sequence_diagram_size(seq: ParsedSequenceDiagram) -> List[StructuralFinding]:
    if len(seq.participants) <= _MAX_COMFORTABLE_PARTICIPANTS:
        return []
    return [StructuralFinding(
        check="sequence_diagram_too_many_participants",
        severity="warning",
        message=(
            f"This sequence diagram has {len(seq.participants)} participants -- a "
            f"real past example at 13 participants in one diagram was already "
            f"identified as genuinely hard to read. Consider splitting this into "
            f"one focused diagram per role or per journey instead."
        ),
        evidence=f"{len(seq.participants)} participants: {', '.join(sorted(seq.participants.keys()))}",
    )]


def find_structural_issues(mermaid_body: str) -> List[StructuralFinding]:
    parsed = parse_mermaid_block(mermaid_body)
    if isinstance(parsed, ParsedSequenceDiagram):
        findings: List[StructuralFinding] = []
        findings.extend(_check_unbalanced_activations(parsed))
        findings.extend(_check_sequence_diagram_size(parsed))
        return findings

    findings: List[StructuralFinding] = []
    findings.extend(_check_unbalanced_pipe_labels(mermaid_body))
    findings.extend(_check_undeclared_nodes(parsed))
    findings.extend(_check_disconnected_components(parsed))
    findings.extend(_check_multiple_unlinked_entry_points(parsed))
    findings.extend(_check_conflicting_duplicate_edges(parsed))
    findings.extend(_check_diagram_complexity(parsed))
    findings.extend(_check_long_labels(parsed))
    findings.extend(_check_high_degree_nodes(parsed))
    findings.extend(_check_horizontal_chain_too_long(mermaid_body, parsed))
    return findings


# ---------------------------------------------------------------------------
# Layer 3 -- structural similarity between two diagrams. No LLM, but no
# longer pure literal-string matching either -- see _labels_equivalent for
# why: a real run showed an id-based (and later a plain normalized-label-
# based) comparison completely miss a genuine near-duplicate, because the
# downstream document renamed every node id AND expanded every abbreviation
# ("CDP" -> "Customer Data Platform (Extended)") at the same time. Neither
# rename alone would have evaded a smarter check; both together evaded the
# original one entirely, which is exactly why this was rewritten to compare
# by fuzzy-matched LABEL rather than by literal id.
# ---------------------------------------------------------------------------

_TRAILING_PAREN_ANNOTATION_RE = re.compile(r'\s*\([^()]*\)\s*$')


def _normalize_label_for_comparison(text: str) -> str:
    """Strips a status/annotation suffix like "(Extended)" or "(Built)"
    (repeatedly, in case of more than one), lowercases, and collapses
    whitespace. This alone catches the "(Extended)"/"(Built)" tagging
    pattern seen across BA/PE/system-design's real diagrams, but NOT an
    abbreviation expanding into a full name -- that's what
    _labels_equivalent below is for."""
    text = text.strip().strip('"').strip()
    prev = None
    while prev != text:
        prev = text
        text = _TRAILING_PAREN_ANNOTATION_RE.sub('', text).strip()
    return re.sub(r'\s+', ' ', text).lower()


def _labels_equivalent(a: str, b: str) -> bool:
    """Two already-normalized labels are treated as the same real-world
    component if they're identical, OR if the shorter one is a plausible
    acronym of the longer one's word-initials (e.g. "cdp" vs "customer
    data platform" -> "c"+"d"+"p"), OR if every word in the shorter phrase
    also appears in the longer one (e.g. "analytics engine" vs
    "predictive analytics engine"). Confirmed against the real case that
    motivated it: of system-design's five real node labels compared
    against PE's five, four matched correctly this way (Subscriber, CDP,
    Analytics Engine, MyMTN App Backend); the fifth ("CSR Desktop
    Application" vs "CRM System") correctly did NOT match, since neither
    heuristic applies and they may genuinely be different things -- this
    function is deliberately conservative rather than guessing."""
    if a == b:
        return True
    if not a or not b:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    longer_words = longer.split()
    if " " not in shorter and len(shorter) >= 2:
        initials = "".join(w[0] for w in longer_words if w)
        if shorter == initials:
            return True
    shorter_words = shorter.split()
    if shorter_words and all(w in longer_words for w in shorter_words):
        return True
    return False


def _diagram_keys(fc: ParsedFlowchart) -> Set[Tuple[str, object]]:
    """Every node and edge in a flowchart, keyed by normalized LABEL
    (falling back to node id when a node was never given a real label) --
    not by raw id, so renaming ids doesn't change what this compares."""
    node_key_by_id: Dict[str, str] = {}
    for node_id, node in fc.nodes.items():
        text = node.label if node.label else node_id
        node_key_by_id[node_id] = _normalize_label_for_comparison(text)

    keys: Set[Tuple[str, object]] = {("node", k) for k in node_key_by_id.values()}
    for edge in fc.edges:
        src_key = node_key_by_id.get(edge.source, edge.source)
        tgt_key = node_key_by_id.get(edge.target, edge.target)
        keys.add(("edge", (src_key, tgt_key)))
    return keys


def _key_matches_any(key: Tuple[str, object], other_keys: Set[Tuple[str, object]]) -> bool:
    kind, val = key
    for other_kind, other_val in other_keys:
        if kind != other_kind:
            continue
        if kind == "node":
            if _labels_equivalent(val, other_val):
                return True
        else:  # edge: (source_key, target_key) tuple
            if _labels_equivalent(val[0], other_val[0]) and _labels_equivalent(val[1], other_val[1]):
                return True
    return False


def diagram_similarity(body_a: str, body_b: str) -> Optional[float]:
    """Symmetric overlap fraction between two flowchart diagrams, using
    fuzzy label matching (see _labels_equivalent) rather than exact id or
    exact-string comparison. Returns None if either body isn't a flowchart
    or both are empty. 1.0 means every node/edge on each side has a match
    on the other; 0.0 means no overlap at all. Not a strict Jaccard index
    (fuzzy equivalence isn't guaranteed transitive the way exact equality
    is) -- defined instead as the average of "fraction of A's keys matched
    in B" and "fraction of B's keys matched in A", which degrades the same
    sensible way when the two diagrams are different sizes.
    """
    parsed_a = parse_mermaid_block(body_a)
    parsed_b = parse_mermaid_block(body_b)
    if not isinstance(parsed_a, ParsedFlowchart) or not isinstance(parsed_b, ParsedFlowchart):
        return None
    if not parsed_a.nodes and not parsed_b.nodes:
        return None

    keys_a = _diagram_keys(parsed_a)
    keys_b = _diagram_keys(parsed_b)
    if not keys_a and not keys_b:
        return None

    matched_a = sum(1 for k in keys_a if _key_matches_any(k, keys_b))
    matched_b = sum(1 for k in keys_b if _key_matches_any(k, keys_a))
    frac_a = matched_a / len(keys_a) if keys_a else 0.0
    frac_b = matched_b / len(keys_b) if keys_b else 0.0
    return (frac_a + frac_b) / 2


def find_diagrams_in_markdown(markdown: str) -> List[str]:
    return re.findall(r"```mermaid\n(.*?)\n```", markdown, re.DOTALL)


def check_all_diagrams_structurally(markdown: str) -> List[Dict]:
    results: List[Dict] = []
    for i, body in enumerate(find_diagrams_in_markdown(markdown), start=1):
        for finding in find_structural_issues(body):
            results.append({
                "diagram_index": i,
                "check": finding.check,
                "severity": finding.severity,
                "message": finding.message,
                "evidence": finding.evidence,
            })
    return results


_HIGH_SIMILARITY_THRESHOLD = 0.8


def check_diagram_similarity_against(markdown: str, other_markdown: str) -> List[Dict]:
    """Compares every flowchart diagram in `markdown` against every
    flowchart diagram in `other_markdown` (see diagram_similarity for the
    fuzzy-label matching this now uses). Purely structural, no opinion
    about whether high similarity is actually a problem for a given pair
    of documents -- that judgment belongs to whichever caller decides this
    comparison is worth making."""
    own_diagrams = find_diagrams_in_markdown(markdown)
    other_diagrams = find_diagrams_in_markdown(other_markdown)
    findings: List[Dict] = []
    for i, own in enumerate(own_diagrams, start=1):
        for j, other in enumerate(other_diagrams, start=1):
            similarity = diagram_similarity(own, other)
            if similarity is not None and similarity >= _HIGH_SIMILARITY_THRESHOLD:
                findings.append({
                    "own_diagram_index": i,
                    "compared_diagram_index": j,
                    "similarity": round(similarity, 2),
                    "message": (
                        f"This document's diagram {i} is {similarity:.0%} structurally "
                        f"identical (same components, same connections, allowing for "
                        f"renamed ids and expanded abbreviations) to diagram {j} in the "
                        f"document it was given as cross-reference context -- consider "
                        f"whether it should add real detail (deployment specifics, "
                        f"scale, trust boundaries) rather than restate the same "
                        f"components and connections under a new heading."
                    ),
                })
    return findings


def check_internal_diagram_duplication(markdown: str) -> List[Dict]:
    """Same fuzzy-label similarity check as check_diagram_similarity_against,
    but between every pair of diagrams WITHIN one document, rather than
    against a separate upstream document. Built after a real run showed a
    PRD draw its own "Integration Map" and "System Architecture Diagram" as
    two separate Mermaid blocks that were, structurally, the same diagram
    twice -- one styled with colors, one plain."""
    diagrams = find_diagrams_in_markdown(markdown)
    findings: List[Dict] = []
    for i in range(len(diagrams)):
        for j in range(i + 1, len(diagrams)):
            similarity = diagram_similarity(diagrams[i], diagrams[j])
            if similarity is not None and similarity >= _HIGH_SIMILARITY_THRESHOLD:
                findings.append({
                    "diagram_index_a": i + 1,
                    "diagram_index_b": j + 1,
                    "similarity": round(similarity, 2),
                    "message": (
                        f"Diagrams {i + 1} and {j + 1} in this same document are "
                        f"{similarity:.0%} structurally identical -- likely the same "
                        f"diagram drawn twice under two different headings rather than "
                        f"two genuinely different views of the system."
                    ),
                })
    return findings


# ---------------------------------------------------------------------------
# Decision-point-vs-branching: if this document's own prose declares a
# "Decision Point" for a role/journey, that role's own diagram should
# actually show a branch (a node with 2+ outgoing edges) -- a decision with
# only one possible next step in the diagram isn't really shown as a
# decision. When the count of "Decision Point" mentions matches the count
# of diagrams exactly (the normal case: one role, one stated decision
# point, one diagram, in the same document order -- true for every real
# UI/UX RFC this project generates), each is paired to the diagram at the
# same ordinal position and checked independently, so a fix in ONE role's
# diagram is never allowed to mask a genuinely unfixed problem in another
# role's. A real run exposed exactly this gap: three roles each stated a
# decision point, only the first role's diagram actually branched, and the
# original per-document "does ANY diagram branch" check let the other two
# silently pass because the first one branching was enough to satisfy it.
# When the counts don't match 1:1 (mixed documents, a diagram with no
# stated decision point, etc.), pairing isn't safely inferable from
# structure alone, so this falls back to the coarser "does at least one
# diagram branch anywhere" signal rather than guessing a pairing the
# document's own structure doesn't actually support.
# ---------------------------------------------------------------------------

_DECISION_POINT_MENTION_RE = re.compile(r'decision\s+points?\**\s*:', re.IGNORECASE)


def _diagram_has_branch_point(body: str) -> bool:
    parsed = parse_mermaid_block(body)
    if not isinstance(parsed, ParsedFlowchart):
        return True  # not a flowchart -- this check doesn't meaningfully apply, don't flag
    out_degree: Dict[str, int] = {}
    for edge in parsed.edges:
        out_degree[edge.source] = out_degree.get(edge.source, 0) + 1
    return any(count >= 2 for count in out_degree.values())


def check_decision_points_reflected(markdown: str) -> List[Dict]:
    prose_only = re.sub(r"```mermaid\n.*?\n```", "", markdown, flags=re.DOTALL)
    decision_mentions = len(_DECISION_POINT_MENTION_RE.findall(prose_only))
    if decision_mentions == 0:
        return []

    diagrams = find_diagrams_in_markdown(markdown)
    if not diagrams:
        return []

    if decision_mentions == len(diagrams):
        findings: List[Dict] = []
        for i, body in enumerate(diagrams, start=1):
            if not _diagram_has_branch_point(body):
                findings.append({
                    "diagram_index": i,
                    "message": (
                        f"Diagram {i} corresponds to a role whose own section states a "
                        f"Decision Point, but diagram {i} itself is a straight chain with "
                        f"no branch (no node with two or more outgoing edges) -- the "
                        f"decision described in the prose isn't actually shown here."
                    ),
                })
        return findings

    if any(_diagram_has_branch_point(body) for body in diagrams):
        return []

    return [{
        "decision_point_mentions": decision_mentions,
        "diagram_count": len(diagrams),
        "message": (
            f"This document's prose states {decision_mentions} \"Decision Point\" "
            f"section(s), but none of its {len(diagrams)} diagram(s) show a branch "
            f"(a node with two or more outgoing edges) -- every diagram is a "
            f"straight chain. A described decision with only one path forward in "
            f"the diagram isn't actually shown as a decision."
        ),
    }]
