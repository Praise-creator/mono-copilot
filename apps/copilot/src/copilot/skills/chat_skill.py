"""
Chat Skill: free-form Q&A that sits alongside the document pipeline rather
than inside it.

Every other skill in this package (ba_skill, pe_skill, rfc_skill) exists to
produce one specific document at one specific stage of the state machine.
This one doesn't produce anything the Orchestrator tracks: it answers a
question and returns. That's why there's no ChatAgent wrapper next to
BAAgent/PEAgent/RFCAgent. Those wrappers exist because the Orchestrator
drives them through a workflow. Nothing drives this, so cli/router.py calls
it directly and the Orchestrator never learns it exists.

HOW A QUESTION FLOWS THROUGH THIS FILE
--------------------------------------
Read answer() first; everything else is a helper it calls. The order is:

  1. Someone types "/ask what does ARPU mean?" and cli/router.py calls
     answer() with the question, plus whatever project is currently open.
  2. _gather_sources() checks the question against the approved-source list
     in config/authorized_sources.py. Asking about "churn" matches GSMA and
     Statista; asking about "regulation" in a Nigerian project matches the
     NCC. This is plain keyword matching, not a web search.
  3. _system_prompt() builds the model's instructions, with those matched
     sources embedded as the only ones it is permitted to name.
  4. _build_user_prompt() attaches the open project's BRD/PRD, so questions
     like "what does the BRD say about churn?" can actually be answered.
  5. _build_messages() replays recent Q&A as conversation history, which is
     what makes a follow-up like "what about Ghana?" understandable.
  6. The model is called, then _gather_sources() runs once more over the
     answer to catch topics the answer raised that the question didn't.
  7. A plain dict goes back to Router, which handles all display.

The one rule worth internalising before changing anything here: this file
never touches the workflow. It cannot approve a document, trigger a rework,
or change a project's stage. Asking a question must always be safe.

WHAT "SOURCE-GROUNDED" HONESTLY MEANS HERE
------------------------------------------
ResearchService is keyword-to-whitelist matching, not web search. Its own
docstring flags real search as Phase 2 work that hasn't happened. So a
source attached to an answer means "this domain is an authorized reference
for a topic this answer touches", NOT "this specific sentence was checked
against that page." Those are very different claims and conflating them is
exactly the kind of quiet dishonesty the rest of this codebase goes out of
its way to avoid.

That distinction drives two concrete choices below:

  1. The returned field is `related_sources`, not `verified_sources` —
     even though ResearchService's own payload uses the latter name. The
     rename happens at this boundary on purpose, so nothing downstream can
     accidentally render keyword hits as verified citations.
  2. The model is told the whitelist is the ONLY set of sources it may name,
     and is told plainly to say "I don't know" instead of inventing a
     statistic. An unsourced honest answer beats a confidently fabricated
     regulation every time — especially here, where a wrong regulator in an
     MNO compliance discussion is a genuinely costly error.

MODEL CHOICE
------------
gpt-4-turbo, matching ba_skill.py, pe_skill.py and rfc_skill.py.

The obvious alternative was gpt-4o-mini, which intake_agent.py uses. Intake
picked mini because it needs a quick back-and-forth: several short turns in
a row, where a slow reply is felt immediately and the actual work (pick one
of eight entry paths) is easy enough that the smaller model handles it.

The two jobs pull in different directions. A chat answer here is usually
about the BRD or PRD sitting in the prompt, so answering it well means
reading a long technical document accurately and resisting the urge to fill
gaps with plausible-sounding telecom detail. That is where a smaller model
tends to slip first, and a confident wrong answer about a document someone
is midway through approving is a costly kind of wrong.

The trade-off accepted here is real and worth stating: turbo is slower, and
this is a conversational feature where that will be noticeable. Answer
quality on long documents was judged the more important of the two. If Q&A
in practice turns out to be mostly short definitional questions rather than
document questions, revisiting this is reasonable. Change MODEL below.
"""

from datetime import datetime
from typing import Dict, List, Optional
import os

from openai import AsyncOpenAI

from ..services.research_service import ResearchService


MODEL = "gpt-4-turbo"  # matches ba_skill.py/pe_skill.py/rfc_skill.py, see module docstring

# Chat answers are meant to be read in a terminal, in the middle of doing
# something else. This ceiling keeps them at "helpful paragraph" length
# rather than letting them drift into unrequested mini-documents.
MAX_TOKENS = 900

# How many prior Q&A pairs travel with each request, so follow-ups like
# "what about Ghana?" resolve against what was just discussed. Capped
# because every retained turn is re-sent (and re-billed) on every
# subsequent question. Unbounded history quietly turns a cheap feature
# into an expensive one.
MAX_HISTORY_TURNS = 6

# Documents are pulled into the prompt as excerpts, not in full. A BRD plus
# a PRD can comfortably exceed what's reasonable to resend on every single
# question, and the truncation is announced to the model (see
# _format_excerpt) so it can say "the part I can see doesn't cover that"
# instead of confidently answering from a document half it never received.
MAX_DOC_EXCERPT_CHARS = 6000


def _format_excerpt(label: str, markdown: Optional[str]) -> Optional[str]:
    """
    One document, trimmed for the prompt, with truncation stated out loud.

    The explicit "[truncated]" marker is the load-bearing part. Silently
    cutting a document produces a model that answers "the BRD doesn't
    mention X" with total confidence when in fact X was in the half that
    got dropped — a wrong answer that reads exactly like a right one.
    """
    if not markdown:
        return None

    body = markdown.strip()
    if len(body) > MAX_DOC_EXCERPT_CHARS:
        body = (
            body[:MAX_DOC_EXCERPT_CHARS].rstrip()
            + f"\n\n[...truncated. This is the first {MAX_DOC_EXCERPT_CHARS} "
            "characters only. If the answer depends on a later section, say so "
            "rather than assuming the section is absent.]"
        )
    return f"--- {label} ---\n{body}"


class ChatSkill:
    """
    Answers one question per call. Deliberately stateless: conversation
    history is passed in by the caller rather than accumulated here.

    Router already owns "one instance per session" as its whole reason for
    existing, so keeping the transcript there means there is exactly one
    place session state lives. A skill that quietly grew its own parallel
    memory would be a second answer to "what has this user been doing",
    and two sources of truth for that is how sessions start disagreeing
    with themselves.
    """

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")
        self.client = AsyncOpenAI(api_key=self.api_key)
        self.model = MODEL
        self.research_service = ResearchService()

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _system_prompt(self, allowed_sources: List[Dict]) -> str:
        """
        The whitelist is injected into the system prompt rather than merely
        appended to the answer afterwards. Listing sources after the fact
        would decorate whatever the model already said; putting them here
        constrains what it's willing to assert in the first place, which is
        the only version of this that actually reduces fabrication.
        """
        if allowed_sources:
            source_lines = "\n".join(
                f"- {s['source_url']} ({s.get('source_type', 'unknown')} source"
                + (f", {s['country']}" if s.get("country") else "")
                + ")"
                for s in allowed_sources
            )
            sources_block = (
                "AUTHORIZED SOURCES RELEVANT TO THIS TOPIC:\n"
                f"{source_lines}\n\n"
                "You may reference these by name. You may NOT cite any other "
                "source, URL, report, or publication — not even a real and "
                "well-known one. If the answer needs evidence that isn't "
                "available from the list above, say that plainly instead."
            )
        else:
            sources_block = (
                "NO AUTHORIZED SOURCES matched this topic. Answer from general "
                "knowledge and say so. Do not cite any URL, report, or "
                "publication. There is nothing verified to cite here."
            )

        return f"""You are the assistant inside Mono-Copilot, a product-development tool for \
enterprise mobile network operators (MNOs) in Nigeria, Ghana, Kenya, South Africa and Egypt.

The tool's pipeline is: business idea -> BRD (business analyst) -> PRD (product engineer) \
-> five role RFCs (system design, UI/UX, security, QA, DevOps) -> PDF export. A human \
reviews and approves at each stage.

You are answering a question asked mid-workflow. Treat it as a colleague leaning over \
and asking something, not as a request for a document.

HOW TO ANSWER:
- Lead with the answer. No preamble, no restating the question.
- Markdown, and keep it tight: a short paragraph or a few bullets. Only go longer if \
the question genuinely needs it.
- If project context is provided below, prefer it for anything asking about "we", "this \
project", "the BRD", or "the PRD". Quote the document rather than paraphrasing when the \
exact wording matters.
- For questions about the tool itself (what a stage does, what happens next), answer from \
the pipeline description above.

WHAT YOU MUST NOT DO:
- Do not invent statistics, percentages, dates, or monetary figures. An unsourced "I don't \
have a verified figure for that" is correct and useful; a plausible invented number is a \
serious error that could end up in a real document.
- Do not name a regulator unless the country is actually established. Nigeria is the NCC, \
Ghana the NCA, Kenya the CA, South Africa ICASA, Egypt the NTRA. Never default to one out \
of habit when no country was stated.
- Do not claim a document says something you cannot see in the provided context.
- Say "I don't know" when you don't know. That is an acceptable, expected answer here.

{sources_block}"""

    def _build_user_prompt(self, question: str, project_context: Optional[Dict]) -> str:
        """Question plus whatever project state the caller chose to share."""
        if not project_context:
            return question

        parts: List[str] = []

        project_name = project_context.get("project_name")
        stage = project_context.get("stage")
        if project_name:
            stage_note = f", currently at stage '{stage}'" if stage else ""
            parts.append(f"[Active project: '{project_name}'{stage_note}]")

        problem_statement = project_context.get("problem_statement")
        if problem_statement:
            parts.append(f"--- ORIGINAL PROBLEM STATEMENT ---\n{problem_statement.strip()}")

        for label, key in (("BRD (business requirements)", "brd"), ("PRD (product requirements)", "prd")):
            excerpt = _format_excerpt(label, project_context.get(key))
            if excerpt:
                parts.append(excerpt)

        if not parts:
            return question

        context_block = "\n\n".join(parts)
        return (
            "Context from the project currently open (use it only where relevant "
            f"to the question):\n\n{context_block}\n\n--- QUESTION ---\n{question}"
        )

    def _build_messages(
        self,
        question: str,
        project_context: Optional[Dict],
        history: Optional[List[Dict]],
        allowed_sources: List[Dict],
    ) -> List[Dict]:
        """
        Prior turns are replayed as real user/assistant messages rather than
        pasted into one blob of text. The model was trained on conversations
        shaped this way, so "what about Ghana?" resolves against the previous
        turn naturally instead of needing to be re-explained.

        Only the current turn carries project context. Re-attaching document
        excerpts to every historical turn would multiply the prompt by the
        number of questions asked, for context the model can already see once.
        """
        messages: List[Dict] = [{"role": "system", "content": self._system_prompt(allowed_sources)}]

        for turn in (history or [])[-MAX_HISTORY_TURNS:]:
            question_text = turn.get("question")
            answer_text = turn.get("answer")
            if question_text and answer_text:
                messages.append({"role": "user", "content": question_text})
                messages.append({"role": "assistant", "content": answer_text})

        messages.append({"role": "user", "content": self._build_user_prompt(question, project_context)})
        return messages

    # ------------------------------------------------------------------
    # Source gathering
    # ------------------------------------------------------------------

    async def _gather_sources(self, *texts: Optional[str]) -> List[Dict]:
        """
        Whitelist hits across every supplied text, deduplicated by URL.

        Cheap enough to call more than once per question: search_and_verify
        is local regex matching over a static config with no network call
        behind it, despite the name suggesting otherwise.

        Dedup matters for the same reason research_service.py dedups
        internally. A telecom answer naturally repeats "regulation",
        "regulatory" and "compliance", and without this the same two URLs
        would be listed five times and read as far more corroboration than
        actually exists.
        """
        seen_urls: set = set()
        collected: List[Dict] = []

        for text in texts:
            if not text:
                continue
            result = await self.research_service.search_and_verify(text)
            for source in result.get("verified_sources", []):
                url = source.get("source_url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    collected.append(source)

        return collected

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def answer(
        self,
        question: str,
        project_context: Optional[Dict] = None,
        history: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        Answer one question.

        Args:
            question: Raw user question, already stripped of any '/ask' prefix.
            project_context: Optional dict with any of project_name, stage,
                problem_statement, brd, prd. Router assembles this from live
                session state; absent entirely when no project is open.
            history: Prior [{"question": ..., "answer": ...}] pairs, oldest
                first. Caller owns storage and trimming.

        Returns:
            {
                "status": "success" | "error",
                "answer_id": "CHAT-20260810-143022",
                "markdown": "...",            # the answer itself, no sources appended
                "related_sources": [...],     # whitelist hits, NOT per-claim verification
                "error": "..."                # only when status == "error"
            }

        The answer markdown deliberately excludes any rendered source list.
        Sources come back structured so each caller formats them for its own
        surface. A terminal footer and a TUI side panel want very different
        things, and baking one into the text would force the other to parse
        it back out.
        """
        question = (question or "").strip()
        if not question:
            return {
                "status": "error",
                "error": "No question provided.",
                "markdown": None,
                "related_sources": [],
            }

        answer_id = f"CHAT-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        try:
            # Pass 1, before generation: what is the QUESTION about? These
            # sources constrain the prompt, so they have to be resolved first.
            topic_sources = await self._gather_sources(question)

            response = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                messages=self._build_messages(question, project_context, history, topic_sources),
            )

            markdown = (response.choices[0].message.content or "").strip()
            if not markdown:
                return {
                    "status": "error",
                    "answer_id": answer_id,
                    "error": "Model returned an empty answer.",
                    "markdown": None,
                    "related_sources": [],
                }

            # Pass 2, after generation: the answer may have raised topics the
            # question never named (asking about churn, getting an answer that
            # discusses ARPU). Re-running over the answer catches those, and
            # the dedup inside _gather_sources means pass 1's hits aren't
            # duplicated.
            related_sources = await self._gather_sources(question, markdown)

            return {
                "status": "success",
                "answer_id": answer_id,
                "markdown": markdown,
                "related_sources": related_sources,
            }

        except Exception as e:
            # A failed question must never take down the session around it.
            # Router surfaces this as an ordinary message and the user carries
            # on with whatever workflow they were in the middle of. An
            # unavailable side feature is an inconvenience; losing an
            # in-progress BRD review to an unhandled exception is not.
            return {
                "status": "error",
                "answer_id": answer_id,
                "error": f"Could not answer that: {e}",
                "markdown": None,
                "related_sources": [],
            }
