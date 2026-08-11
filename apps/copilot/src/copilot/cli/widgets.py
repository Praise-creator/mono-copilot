"""MTN badge widget for the Textual chat TUI.

Ported from mtn-logo.js. Colors and templates match the Node CLI so the
badge looks the same whether it's shown in the raw-ANSI tool or here.

Drop this into copilot/cli/widgets.py (or import it from there).
"""

import random

from rich.style import Style
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

BRIGHT = "#fdb913"  # MTN yellow
DIM = "#bd8a0e"     # dimmer step of the same hue

TEMPLATES = {
    "wide": {
        "top": ["▟", "▀", "▀", "▀", "▀", "▀", "▙"],
        "mid": ["█", " ", "M", "T", "N", " ", "█"],
        "bottom": ["▜", "▄", "▄", "▄", "▄", "▄", "▛"],
    },
    "medium": {
        "top": ["▟", "▀", "▀", "▀", "▙"],
        "mid": ["█", "M", "T", "N", "█"],
        "bottom": ["▜", "▄", "▄", "▄", "▛"],
    },
    "sliver": {
        "top": ["▐", "▌"],
        "mid": ["▐", "▌"],
        "bottom": ["▐", "▌"],
    },
}
ROWS = ("top", "mid", "bottom")
RIM_PERIMETER = [
    (0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (0, 5), (0, 6),
    (1, 6),
    (2, 6), (2, 5), (2, 4), (2, 3), (2, 2), (2, 1), (2, 0),
    (1, 0),
]
LETTER_COLS = (2, 3, 4)
FLIP_LENGTH = 16
STATUS_VERBS = ("Dialing", "Pinging tower", "Roaming", "Connecting", "Syncing")


class MTNBadge(Static):
    """A small idling MTN medallion — speeds up while `busy` during API calls."""

    DEFAULT_CSS = """
    MTNBadge {
        width: 9;
        height: 3;
        content-align: center middle;
    }
    """

    frame: reactive[int] = reactive(0)
    busy: reactive[bool] = reactive(False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._flip_frame = -1
        self._squash_phase = 0
        self._blink_frame = 0
        self._idle_timer = 0

    def on_mount(self) -> None:
        self.set_interval(1 / 15, self._tick)

    def watch_busy(self, busy: bool) -> None:
        # A quick squash-stretch pop whenever busy starts or stops, so the
        # transition itself reads as a reaction rather than a silent flag flip.
        self._squash_phase = 6

    def _tick(self) -> None:
        if self._squash_phase > 0:
            self._squash_phase -= 1
        if self._flip_frame >= 0:
            self._flip_frame += 1
            if self._flip_frame > FLIP_LENGTH:
                self._flip_frame = -1
        if self._blink_frame > 0:
            self._blink_frame -= 1

        self._idle_timer += 1
        flip_every = 45 if self.busy else 180
        if self._flip_frame < 0 and self._squash_phase == 0 and self._idle_timer % flip_every == 0:
            self._flip_frame = 0
        blink_chance = 0.03 if self.busy else 0.01
        if self._blink_frame == 0 and random.random() < blink_chance:
            self._blink_frame = 2

        self.frame += 1  # bumping the reactive triggers a re-render

    def _template_key(self) -> str:
        if self._squash_phase > 0:
            return "medium"
        if self._flip_frame >= 0:
            half = FLIP_LENGTH / 2
            dist = abs(self._flip_frame - half)
            if dist >= half - 2:
                return "wide"
            if dist <= 2:
                return "sliver"
            return "medium"
        return "wide"

    def current_status_text(self) -> str:
        """`[MTN] ● Dialing...` — hand this to your Footer/status bar instead
        of duplicating chrome, if you'd rather not show a second status line."""
        verb_span = 60 if self.busy else 120
        dot_span = 10 if self.busy else 20
        verb = STATUS_VERBS[(self.frame // verb_span) % len(STATUS_VERBS)]
        dots = "." * ((self.frame // dot_span) % 3 + 1)
        glyph = "◆" if self.busy else "●"
        return f"[MTN] {glyph} {verb}{dots}"

    def render(self) -> Text:
        key = self._template_key()
        template = TEMPLATES[key]

        highlights = set()
        if key == "wide":
            rim_step = 2 if self.busy else 4
            rim_index = self.frame // rim_step
            highlights.add(RIM_PERIMETER[rim_index % len(RIM_PERIMETER)])

            glint_span = 80 if self.busy else 150
            glint_cycle = self.frame % glint_span
            if glint_cycle < 24:
                letter_index = glint_cycle // 8
                if 0 <= letter_index < len(LETTER_COLS):
                    highlights.add((1, LETTER_COLS[letter_index]))

            if self._blink_frame > 0:
                highlights.add((0, 0))

        text = Text()
        for row_idx, row_name in enumerate(ROWS):
            for col_idx, ch in enumerate(template[row_name]):
                color = BRIGHT if (row_idx, col_idx) in highlights else DIM
                text.append(ch, style=Style(color=color, bold=True))
            if row_idx < len(ROWS) - 1:
                text.append("\n")
        return text