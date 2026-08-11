"""Smoke tests for the MTN badge widget. Fits the "Textual Pilot smoke test
for app boot" item in Phase 4 of the CLI plan.

Requires pytest-asyncio (added as a dev dependency in pyproject.toml).
"""

import pytest
from textual.app import App, ComposeResult

from copilot.cli.widgets import MTNBadge


class _Harness(App):
    def compose(self) -> ComposeResult:
        yield MTNBadge(id="badge")


@pytest.mark.asyncio
async def test_badge_boots_and_renders_three_rows():
    app = _Harness()
    async with app.run_test() as pilot:
        badge = app.query_one(MTNBadge)
        await pilot.pause(0.1)
        text = badge.render().plain
        assert "MTN" in text
        assert text.count("\n") == 2


@pytest.mark.asyncio
async def test_idle_ticks_advance_frame_without_error():
    app = _Harness()
    async with app.run_test() as pilot:
        badge = app.query_one(MTNBadge)
        for _ in range(10):
            await pilot.pause(0.05)
        assert badge.frame > 0
        assert badge.render().plain.count("\n") == 2


@pytest.mark.asyncio
async def test_busy_mode_toggles_cleanly():
    app = _Harness()
    async with app.run_test() as pilot:
        badge = app.query_one(MTNBadge)
        badge.busy = True
        for _ in range(10):
            await pilot.pause(0.05)
        assert "MTN" in badge.render().plain
        assert badge.current_status_text().startswith("[MTN]")
        badge.busy = False
        await pilot.pause(0.1)
        assert "MTN" in badge.render().plain


@pytest.mark.asyncio
async def test_busy_toggle_triggers_squash_pop():
    """Regression test: toggling `busy` must actually trigger the
    squash-stretch frame, not just flip the flag with no visible reaction."""
    app = _Harness()
    async with app.run_test() as pilot:
        badge = app.query_one(MTNBadge)
        await pilot.pause(0.05)

        badge.busy = True
        assert badge._squash_phase > 0
        assert badge._template_key() == "medium"

        for _ in range(10):
            await pilot.pause(0.05)
        assert badge._squash_phase == 0