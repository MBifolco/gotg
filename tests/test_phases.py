"""Tests for gotg.phases — PhaseCapabilities table and accessors."""

import logging

import pytest

from gotg.config import PHASE_ORDER
from gotg.phases import (
    PHASE_CAPS,
    PhaseCapabilities,
    _EMPTY,
    get_phase_caps,
    get_phase_caps_safe,
)


# ── Drift guard ──────────────────────────────────────────────

def test_phase_caps_keys_match_phase_order():
    """PHASE_CAPS must cover exactly the same phases as PHASE_ORDER."""
    assert set(PHASE_CAPS.keys()) == set(PHASE_ORDER)


def test_all_five_phases_present():
    expected = {"refinement", "planning", "pre-code-review", "implementation", "code-review"}
    assert set(PHASE_CAPS.keys()) == expected


# ── get_phase_caps (strict) ──────────────────────────────────

def test_strict_none_returns_empty():
    caps = get_phase_caps(None)
    assert caps == _EMPTY
    assert not any(
        getattr(caps, f.name)
        for f in caps.__dataclass_fields__.values()
    )


def test_strict_unknown_raises_value_error():
    with pytest.raises(ValueError, match="Unknown phase 'typo'"):
        get_phase_caps("typo")


def test_strict_unknown_includes_valid_phases():
    with pytest.raises(ValueError, match="refinement"):
        get_phase_caps("bogus")


def test_strict_known_phase_returns_caps():
    caps = get_phase_caps("implementation")
    assert isinstance(caps, PhaseCapabilities)
    assert caps.use_implementation_executor is True


# ── get_phase_caps_safe (lenient) ────────────────────────────

def test_safe_none_returns_empty():
    assert get_phase_caps_safe(None) == _EMPTY


def test_safe_unknown_returns_empty_no_raise():
    caps = get_phase_caps_safe("bogus")
    assert caps == _EMPTY


def test_safe_unknown_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="gotg.phases"):
        get_phase_caps_safe("bogus")
    assert "Unknown phase 'bogus'" in caplog.text


def test_safe_known_phase_returns_caps():
    caps = get_phase_caps_safe("code-review")
    assert caps.phase_complete_shows_review_hint is True


# ── Immutability ─────────────────────────────────────────────

def test_frozen_dataclass():
    caps = get_phase_caps("implementation")
    with pytest.raises(AttributeError):
        caps.use_implementation_executor = False  # type: ignore[misc]


# ── Phase-specific capability values ─────────────────────────

def test_refinement_all_false():
    caps = get_phase_caps("refinement")
    assert caps == PhaseCapabilities()


def test_planning_all_false():
    caps = get_phase_caps("planning")
    assert caps == PhaseCapabilities()


def test_pre_code_review_caps():
    caps = get_phase_caps("pre-code-review")
    assert caps.requires_tasks is True
    assert caps.requires_task_assignment is True
    assert caps.include_task_assignments_kickoff is True
    assert caps.show_task_status_bar is True
    assert caps.auto_open_task_assign_on_advance is True
    # Should NOT have these:
    assert caps.filter_tasks_by_layer is False
    assert caps.enable_worktrees is False
    assert caps.use_implementation_executor is False
    assert caps.can_open_review_screen is False


def test_implementation_caps():
    caps = get_phase_caps("implementation")
    assert caps.requires_tasks is True
    assert caps.requires_task_assignment is True
    assert caps.filter_tasks_by_layer is True
    assert caps.inject_file_access_prompt is True
    assert caps.inject_writable_paths_kickoff is True
    assert caps.include_task_assignments_kickoff is True
    assert caps.scope_kickoff_to_layer is True
    assert caps.enable_worktrees is True
    assert caps.filter_worktree_agents_by_tasks is True
    assert caps.use_implementation_executor is True
    assert caps.supports_next_layer is True
    assert caps.can_open_review_screen is True
    assert caps.show_task_status_bar is True
    # Should NOT have these:
    assert caps.phase_complete_shows_review_hint is False
    assert caps.auto_open_task_assign_on_advance is False


def test_code_review_caps():
    caps = get_phase_caps("code-review")
    assert caps.inject_file_access_prompt is True
    assert caps.inject_writable_paths_kickoff is True
    assert caps.include_task_assignments_kickoff is True
    assert caps.scope_kickoff_to_layer is True
    assert caps.enable_worktrees is True
    assert caps.supports_next_layer is True
    assert caps.phase_complete_shows_review_hint is True
    assert caps.can_open_review_screen is True
    # Should NOT have these:
    assert caps.requires_tasks is False
    assert caps.filter_tasks_by_layer is False
    assert caps.use_implementation_executor is False
    assert caps.show_task_status_bar is False
    assert caps.filter_worktree_agents_by_tasks is False


# ── Semantic split regression tests ──────────────────────────

def test_auto_open_task_assign_only_pre_code_review():
    """auto_open_task_assign_on_advance is True only for pre-code-review."""
    for phase_name, caps in PHASE_CAPS.items():
        if phase_name == "pre-code-review":
            assert caps.auto_open_task_assign_on_advance is True
        else:
            assert caps.auto_open_task_assign_on_advance is False, phase_name


def test_scope_kickoff_to_layer_impl_and_code_review():
    """scope_kickoff_to_layer is True for implementation + code-review."""
    assert PHASE_CAPS["implementation"].scope_kickoff_to_layer is True
    assert PHASE_CAPS["code-review"].scope_kickoff_to_layer is True
    assert PHASE_CAPS["pre-code-review"].scope_kickoff_to_layer is False


def test_review_hint_vs_review_screen_split():
    """phase_complete_shows_review_hint (code-review only) vs
    can_open_review_screen (impl + code-review) are distinct."""
    assert PHASE_CAPS["code-review"].phase_complete_shows_review_hint is True
    assert PHASE_CAPS["implementation"].phase_complete_shows_review_hint is False
    assert PHASE_CAPS["code-review"].can_open_review_screen is True
    assert PHASE_CAPS["implementation"].can_open_review_screen is True


def test_supports_next_layer_dedicated():
    """supports_next_layer is its own field, not aliased to enable_worktrees."""
    # Both are True for impl + code-review, but they're distinct fields
    impl = PHASE_CAPS["implementation"]
    assert impl.supports_next_layer is True
    assert impl.enable_worktrees is True
    # Verify they're separate fields
    assert "supports_next_layer" in PhaseCapabilities.__dataclass_fields__
    assert "enable_worktrees" in PhaseCapabilities.__dataclass_fields__
