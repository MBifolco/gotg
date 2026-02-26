"""Verify session.py split: re-export parity, direct imports, no cycles, __all__ completeness."""

import ast
import importlib
from pathlib import Path

import pytest

import gotg.session as session_shim
import gotg.session_types as session_types
import gotg.session_setup as session_setup
import gotg.session_advance as session_advance
import gotg.session_review as session_review


# ── Re-export parity ──────────────────────────────────────────

SUBMODULES = [session_types, session_setup, session_advance, session_review]

# Dynamic: union of all submodule __all__ lists (single source of truth)
EXPECTED_NAMES = sorted(set().union(*(mod.__all__ for mod in SUBMODULES)))


@pytest.mark.parametrize("name", EXPECTED_NAMES)
def test_reexport_available_from_session(name):
    """Every public name is importable from gotg.session."""
    assert hasattr(session_shim, name), f"{name} not found in gotg.session"


@pytest.mark.parametrize("name", EXPECTED_NAMES)
def test_reexport_in_session_all(name):
    """Every public name is listed in gotg.session.__all__."""
    assert name in session_shim.__all__, f"{name} not in gotg.session.__all__"


def test_session_all_no_extras():
    """gotg.session.__all__ doesn't contain names beyond the expected set."""
    extras = set(session_shim.__all__) - set(EXPECTED_NAMES)
    assert not extras, f"Unexpected names in gotg.session.__all__: {extras}"


def test_session_all_equals_submodule_union():
    """gotg.session.__all__ is exactly the union of all submodule __all__ lists."""
    union = set().union(*(mod.__all__ for mod in SUBMODULES))
    shim = set(session_shim.__all__)
    missing = union - shim
    extra = shim - union
    assert not missing, f"In submodules but not in session.__all__: {missing}"
    assert not extra, f"In session.__all__ but not in any submodule: {extra}"


# ── Direct imports from specific modules ──────────────────────

def test_types_direct_import():
    from gotg.session_types import SessionSetupError, resolve_layer, ResolutionStrategy
    assert issubclass(SessionSetupError, Exception)
    assert callable(resolve_layer)
    assert hasattr(ResolutionStrategy, "OURS")


def test_setup_direct_import():
    from gotg.session_setup import prepare_session, run_and_persist, persist_event
    assert callable(prepare_session)
    assert callable(run_and_persist)
    assert callable(persist_event)


def test_advance_direct_import():
    from gotg.session_advance import validate_advance, advance_phase
    assert callable(validate_advance)
    assert callable(advance_phase)


def test_review_direct_import():
    from gotg.session_review import load_review_branches, merge_branches, finalize_merge
    assert callable(load_review_branches)
    assert callable(merge_branches)
    assert callable(finalize_merge)


# ── Shim has no definitions ───────────────────────────────────

def test_shim_has_no_definitions():
    """session.py should contain only imports and __all__, no def or class."""
    src = Path(__file__).resolve().parent.parent / "src" / "gotg" / "session.py"
    tree = ast.parse(src.read_text())
    defs = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert not defs, f"session.py contains definitions: {[d.name for d in defs]}"


# ── __all__ completeness per module ───────────────────────────

@pytest.mark.parametrize("mod", [
    session_types, session_setup, session_advance, session_review, session_shim,
])
def test_module_has_all(mod):
    """Each session module defines __all__."""
    assert hasattr(mod, "__all__"), f"{mod.__name__} missing __all__"
    assert isinstance(mod.__all__, list), f"{mod.__name__}.__all__ is not a list"
    assert len(mod.__all__) > 0, f"{mod.__name__}.__all__ is empty"


@pytest.mark.parametrize("mod", [session_types, session_setup, session_advance, session_review])
def test_all_matches_exports(mod):
    """Each module's __all__ entries are actual attributes of the module."""
    for name in mod.__all__:
        assert hasattr(mod, name), f"{mod.__name__}.__all__ contains '{name}' but it's not defined"


# ── No cycles ─────────────────────────────────────────────────

def test_no_import_cycles():
    """Importing all four modules in any order doesn't fail."""
    for mod_name in [
        "gotg.session_types",
        "gotg.session_setup",
        "gotg.session_advance",
        "gotg.session_review",
    ]:
        importlib.reload(importlib.import_module(mod_name))


# ── No cross-dependencies between bounded-context modules ────

_SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "gotg"

# Forbidden imports: each bounded-context module must not import from the other two.
_FORBIDDEN = {
    "session_setup": {"gotg.session_advance", "gotg.session_review"},
    "session_advance": {"gotg.session_setup", "gotg.session_review"},
    "session_review": {"gotg.session_setup", "gotg.session_advance"},
}


def _extract_import_sources(filepath: Path) -> set[str]:
    """Extract all imported module names from a Python file via AST."""
    tree = ast.parse(filepath.read_text())
    sources: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                sources.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                sources.add(node.module)
    return sources


@pytest.mark.parametrize("module_name,forbidden", list(_FORBIDDEN.items()))
def test_no_cross_imports(module_name, forbidden):
    """Bounded-context modules must not import from each other (AST-verified)."""
    sources = _extract_import_sources(_SRC_DIR / f"{module_name}.py")
    violations = sources & forbidden
    assert not violations, f"{module_name}.py imports forbidden modules: {violations}"


# ── Smoke test ────────────────────────────────────────────────

def test_wildcard_import_smoke():
    """from gotg.session import * doesn't raise."""
    ns = {}
    exec("from gotg.session import *", ns)
    assert "SessionSetupError" in ns
    assert "advance_phase" in ns
    assert "merge_branches" in ns
