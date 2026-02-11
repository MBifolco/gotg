"""Tests for DecisionModal and decision-mode ask_pm integration."""

import pytest

from textual.app import App
from textual.widgets import Checkbox, Input, RadioButton

from gotg.tui.modals.decision import DecisionModal


# ── Helper ───────────────────────────────────────────────────────


OPTIONS = ("Focus on performance", "Add feature tests", "Refactor modules")


def _make_app(question, options, result_holder):
    """Create a plain App that pushes DecisionModal on mount."""
    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                DecisionModal(question, options),
                callback=lambda v: result_holder.__setitem__(0, v),
            )
    return TestApp()


# ── DecisionModal unit tests ────────────────────────────────────


@pytest.mark.asyncio
async def test_decision_submit_option_only():
    """Selecting an option and submitting returns 'Selected: <text>'."""
    result = [None]
    app = _make_app("Which approach?", OPTIONS, result)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DecisionModal)

        # Select first radio button
        radios = app.screen.query(RadioButton)
        radios[0].toggle()
        await pilot.pause()

        app.screen.query_one("#btn-submit").press()
        await pilot.pause()

    assert result[0] == "Selected: Focus on performance"


@pytest.mark.asyncio
async def test_decision_submit_option_with_message():
    """Option + checked message box + text returns combined format."""
    result = [None]
    app = _make_app("Which?", OPTIONS, result)
    async with app.run_test() as pilot:
        await pilot.pause()

        # Select second option
        radios = app.screen.query(RadioButton)
        radios[1].toggle()
        await pilot.pause()

        # Check the message checkbox
        cb = app.screen.query_one("#cb-message", Checkbox)
        cb.toggle()
        await pilot.pause()

        # Type a message
        inp = app.screen.query_one("#decision-input", Input)
        inp.value = "But skip DB module"
        await pilot.pause()

        app.screen.query_one("#btn-submit").press()
        await pilot.pause()

    assert result[0] == "Selected: Add feature tests\n\nMessage: But skip DB module"


@pytest.mark.asyncio
async def test_decision_none_requires_message():
    """Selecting 'None of these' and submitting empty shows notification."""
    result = [None]
    app = _make_app("Which?", OPTIONS, result)
    async with app.run_test() as pilot:
        await pilot.pause()

        # Select "None of these" (last radio button)
        radios = app.screen.query(RadioButton)
        radios[-1].toggle()
        await pilot.pause()

        # Submit without typing a message
        app.screen.query_one("#btn-submit").press()
        await pilot.pause()

        # Modal should still be showing (not dismissed)
        assert isinstance(app.screen, DecisionModal)
        assert result[0] is None


@pytest.mark.asyncio
async def test_decision_none_with_message():
    """Selecting 'None of these' + message returns 'Message: <text>'."""
    result = [None]
    app = _make_app("Which?", OPTIONS, result)
    async with app.run_test() as pilot:
        await pilot.pause()

        # Select "None of these"
        radios = app.screen.query(RadioButton)
        radios[-1].toggle()
        await pilot.pause()

        # Type a message
        inp = app.screen.query_one("#decision-input", Input)
        inp.value = "Different approach entirely"
        await pilot.pause()

        app.screen.query_one("#btn-submit").press()
        await pilot.pause()

    assert result[0] == "Message: Different approach entirely"


@pytest.mark.asyncio
async def test_decision_cancel():
    """Pressing Cancel dismisses with None."""
    result = ["sentinel"]
    app = _make_app("Which?", OPTIONS, result)
    async with app.run_test() as pilot:
        await pilot.pause()

        app.screen.query_one("#btn-cancel").press()
        await pilot.pause()

    assert result[0] is None


@pytest.mark.asyncio
async def test_decision_none_forces_checkbox():
    """Selecting 'None of these' auto-checks and disables the checkbox."""
    result = [None]
    app = _make_app("Which?", OPTIONS, result)
    async with app.run_test() as pilot:
        await pilot.pause()

        cb = app.screen.query_one("#cb-message", Checkbox)
        assert cb.value is False
        assert cb.disabled is False

        # Select "None of these"
        radios = app.screen.query(RadioButton)
        radios[-1].toggle()
        await pilot.pause()

        assert cb.value is True
        assert cb.disabled is True

        # Input should be visible
        inp = app.screen.query_one("#decision-input", Input)
        assert inp.display is True


@pytest.mark.asyncio
async def test_decision_no_selection_shows_warning():
    """Submitting without selecting shows notification."""
    result = [None]
    app = _make_app("Which?", OPTIONS, result)
    async with app.run_test() as pilot:
        await pilot.pause()

        # Submit without selecting anything
        app.screen.query_one("#btn-submit").press()
        await pilot.pause()

        # Modal still showing
        assert isinstance(app.screen, DecisionModal)
        assert result[0] is None


# ── Event backward compatibility ─────────────────────────────────


def test_coach_asked_pm_defaults():
    """CoachAskedPM with only question preserves backward compat."""
    from gotg.events import CoachAskedPM

    event = CoachAskedPM(question="What color?")
    assert event.response_type == "feedback"
    assert event.options == ()


def test_coach_asked_pm_with_decision():
    """CoachAskedPM with decision fields."""
    from gotg.events import CoachAskedPM

    event = CoachAskedPM(
        question="Which approach?",
        response_type="decision",
        options=("A", "B", "C"),
    )
    assert event.response_type == "decision"
    assert event.options == ("A", "B", "C")


# ── Tool schema ──────────────────────────────────────────────────


def test_ask_pm_schema_has_response_type():
    """ask_pm tool schema includes response_type enum."""
    from gotg.prompts import COACH_TOOLS

    ask_pm = [t for t in COACH_TOOLS if t["name"] == "ask_pm"][0]
    props = ask_pm["input_schema"]["properties"]
    assert "response_type" in props
    assert props["response_type"]["enum"] == ["feedback", "decision"]


def test_ask_pm_schema_has_options():
    """ask_pm tool schema includes options array."""
    from gotg.prompts import COACH_TOOLS

    ask_pm = [t for t in COACH_TOOLS if t["name"] == "ask_pm"][0]
    props = ask_pm["input_schema"]["properties"]
    assert "options" in props
    assert props["options"]["type"] == "array"


def test_ask_pm_question_still_required():
    """question remains the only required field."""
    from gotg.prompts import COACH_TOOLS

    ask_pm = [t for t in COACH_TOOLS if t["name"] == "ask_pm"][0]
    assert ask_pm["input_schema"]["required"] == ["question"]
