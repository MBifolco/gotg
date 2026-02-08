import os
from pathlib import Path

import pytest

from gotg.fileguard import FileGuard, SecurityError, _path_matches_pattern


@pytest.fixture
def project(tmp_path):
    """Create a minimal project directory."""
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".team").mkdir()
    (tmp_path / ".git").mkdir()
    return tmp_path


def _guard(project, **overrides):
    config = {"writable_paths": ["src/**", "tests/**", "docs/**"]}
    config.update(overrides)
    return FileGuard(project, config)


# --- _path_matches_pattern ---

def test_pattern_dir_glob_matches():
    assert _path_matches_pattern("src/main.py", "main.py", "src/**") is True


def test_pattern_dir_glob_nested():
    assert _path_matches_pattern("src/sub/deep/file.py", "file.py", "src/**") is True


def test_pattern_dir_glob_no_match():
    assert _path_matches_pattern("lib/main.py", "main.py", "src/**") is False


def test_pattern_filename_glob():
    assert _path_matches_pattern("anything/foo.py", "foo.py", "*.py") is True


def test_pattern_filename_glob_no_match():
    assert _path_matches_pattern("anything/foo.js", "foo.js", "*.py") is False


# --- _resolve_and_contain ---

def test_resolve_relative_path(project):
    guard = _guard(project)
    result = guard._resolve_and_contain("src/main.py")
    assert result == (project / "src" / "main.py").resolve()


def test_resolve_dot_path(project):
    guard = _guard(project)
    result = guard._resolve_and_contain(".")
    assert result == project.resolve()


def test_resolve_empty_path(project):
    guard = _guard(project)
    result = guard._resolve_and_contain("")
    assert result == project.resolve()


def test_reject_absolute_path(project):
    guard = _guard(project)
    with pytest.raises(SecurityError, match="Absolute paths not allowed"):
        guard._resolve_and_contain("/etc/passwd")


def test_reject_dotdot_path(project):
    guard = _guard(project)
    with pytest.raises(SecurityError, match="Path traversal not allowed"):
        guard._resolve_and_contain("../../../etc/passwd")


def test_reject_embedded_dotdot(project):
    guard = _guard(project)
    with pytest.raises(SecurityError, match="Path traversal not allowed"):
        guard._resolve_and_contain("src/../../etc/passwd")


def test_reject_symlink_escape(project):
    """Symlink that resolves outside project root should be rejected."""
    link = project / "escape"
    try:
        link.symlink_to("/tmp")
    except OSError:
        pytest.skip("Cannot create symlinks")
    guard = _guard(project)
    with pytest.raises(SecurityError, match="Path escapes project root"):
        guard._resolve_and_contain("escape/something")


def test_deeply_nested_path(project):
    guard = _guard(project)
    result = guard._resolve_and_contain("a/b/c/d/e/f.py")
    assert result == (project / "a/b/c/d/e/f.py").resolve()


# --- validate_read ---

def test_read_within_project(project):
    guard = _guard(project)
    result = guard.validate_read("src/main.py")
    assert result == (project / "src" / "main.py").resolve()


def test_read_team_dir_allowed(project):
    """Reads are allowed in .team/ — agents need context."""
    guard = _guard(project)
    result = guard.validate_read(".team/team.json")
    assert result == (project / ".team" / "team.json").resolve()


def test_read_outside_project_rejected(project):
    guard = _guard(project)
    with pytest.raises(SecurityError):
        guard.validate_read("/etc/passwd")


# --- validate_list ---

def test_list_within_project(project):
    guard = _guard(project)
    result = guard.validate_list("src")
    assert result == (project / "src").resolve()


def test_list_project_root(project):
    guard = _guard(project)
    result = guard.validate_list(".")
    assert result == project.resolve()


def test_list_outside_project_rejected(project):
    guard = _guard(project)
    with pytest.raises(SecurityError):
        guard.validate_list("/etc")


# --- Hard-deny (writes) ---

def test_write_team_dir_blocked(project):
    guard = _guard(project)
    with pytest.raises(SecurityError, match="Protected path"):
        guard.validate_write(".team/team.json")


def test_write_team_nested_blocked(project):
    guard = _guard(project)
    with pytest.raises(SecurityError, match="Protected path"):
        guard.validate_write(".team/iterations/iter-1/conversation.jsonl")


def test_write_git_dir_blocked(project):
    guard = _guard(project)
    with pytest.raises(SecurityError, match="Protected path"):
        guard.validate_write(".git/config")


def test_write_git_hooks_blocked(project):
    guard = _guard(project)
    with pytest.raises(SecurityError, match="Protected path"):
        guard.validate_write(".git/hooks/pre-commit")


def test_write_dotenv_blocked(project):
    guard = _guard(project)
    with pytest.raises(SecurityError, match="Protected path"):
        guard.validate_write(".env")


def test_write_dotenv_local_blocked(project):
    guard = _guard(project)
    with pytest.raises(SecurityError, match="Protected path"):
        guard.validate_write(".env.local")


def test_write_dotenv_production_blocked(project):
    guard = _guard(project)
    with pytest.raises(SecurityError, match="Protected path"):
        guard.validate_write(".env.production")


def test_write_suffix_env_blocked(project):
    guard = _guard(project)
    with pytest.raises(SecurityError, match="Protected path"):
        guard.validate_write("config.env")


def test_hard_deny_overrides_writable(project):
    """Even if .team/** is in writable_paths, hard-deny still blocks."""
    guard = _guard(project, writable_paths=[".team/**", "src/**"])
    with pytest.raises(SecurityError, match="Protected path"):
        guard.validate_write(".team/team.json")


# --- User-configured protected_paths ---

def test_protected_paths_dir_pattern(project):
    guard = _guard(project, protected_paths=["vendor/**"])
    with pytest.raises(SecurityError, match="Protected path"):
        guard.validate_write("vendor/lib.py")


def test_protected_paths_ext_pattern(project):
    guard = _guard(project, protected_paths=["*.lock"], writable_paths=["*"])
    with pytest.raises(SecurityError, match="Protected path"):
        guard.validate_write("package.lock")


def test_protected_paths_layer_on_hard_deny(project):
    """protected_paths adds on top of hard-deny — both are checked."""
    guard = _guard(project, protected_paths=["config/**"])
    # Hard-deny still works
    with pytest.raises(SecurityError, match="Protected path"):
        guard.validate_write(".team/team.json")
    # User-configured also works
    with pytest.raises(SecurityError, match="Protected path"):
        guard.validate_write("config/settings.py")


# --- Writable paths ---

def test_write_src_allowed(project):
    guard = _guard(project)
    result = guard.validate_write("src/main.py")
    assert result == (project / "src" / "main.py").resolve()


def test_write_src_nested_allowed(project):
    guard = _guard(project)
    result = guard.validate_write("src/sub/deep/file.py")
    assert result == (project / "src/sub/deep/file.py").resolve()


def test_write_tests_allowed(project):
    guard = _guard(project)
    result = guard.validate_write("tests/test_foo.py")
    assert result == (project / "tests/test_foo.py").resolve()


def test_write_outside_writable_denied(project):
    guard = _guard(project)
    with pytest.raises(SecurityError, match="not in writable paths"):
        guard.validate_write("README.md")


def test_write_ext_pattern(project):
    guard = _guard(project, writable_paths=["*.py"])
    result = guard.validate_write("anything.py")
    assert result == (project / "anything.py").resolve()


def test_write_empty_writable_denies_all(project):
    guard = _guard(project, writable_paths=[])
    with pytest.raises(SecurityError, match="not in writable paths"):
        guard.validate_write("src/main.py")


def test_write_multiple_patterns(project):
    guard = _guard(project, writable_paths=["src/**", "*.md"])
    # src/** matches
    guard.validate_write("src/main.py")
    # *.md matches
    guard.validate_write("README.md")
    # Neither matches
    with pytest.raises(SecurityError, match="not in writable paths"):
        guard.validate_write("data.csv")


# --- Edge cases ---

def test_path_with_spaces(project):
    guard = _guard(project)
    result = guard.validate_write("src/my file.py")
    assert result == (project / "src" / "my file.py").resolve()


def test_path_with_special_chars(project):
    guard = _guard(project)
    result = guard.validate_write("src/foo-bar_baz.py")
    assert result == (project / "src" / "foo-bar_baz.py").resolve()


# --- Config defaults ---

def test_default_max_file_size(project):
    guard = FileGuard(project, {})
    assert guard.max_file_size == 1_048_576


def test_default_max_files_per_turn(project):
    guard = FileGuard(project, {})
    assert guard.max_files_per_turn == 10


def test_custom_limits(project):
    guard = FileGuard(project, {
        "max_file_size_bytes": 500_000,
        "max_files_per_turn": 5,
    })
    assert guard.max_file_size == 500_000
    assert guard.max_files_per_turn == 5
