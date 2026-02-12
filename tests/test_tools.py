from pathlib import Path

import pytest

from gotg.fileguard import FileGuard
from gotg.tools import execute_file_tool, format_tool_operation


@pytest.fixture
def project(tmp_path):
    """Create a minimal project with writable dirs."""
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".team").mkdir()
    (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.fixture
def guard(project):
    return FileGuard(project, {
        "writable_paths": ["src/**", "tests/**", "docs/**"],
        "max_file_size_bytes": 1_048_576,
        "max_files_per_turn": 10,
    })


# --- file_read ---

def test_read_existing_file(project, guard):
    (project / "src" / "main.py").write_text("print('hello')")
    result = execute_file_tool("file_read", {"path": "src/main.py"}, guard)
    assert result == "print('hello')"


def test_read_missing_file(project, guard):
    result = execute_file_tool("file_read", {"path": "src/missing.py"}, guard)
    assert result.startswith("Error: file not found")


def test_read_directory_not_file(project, guard):
    result = execute_file_tool("file_read", {"path": "src"}, guard)
    assert result.startswith("Error: not a file")


def test_read_too_large(project, guard):
    small_guard = FileGuard(project, {
        "writable_paths": ["src/**"],
        "max_file_size_bytes": 10,
    })
    (project / "src" / "big.py").write_text("x" * 50)
    result = execute_file_tool("file_read", {"path": "src/big.py"}, small_guard)
    assert result.startswith("Error: file too large")


def test_read_security_error_returns_string(project, guard):
    """SecurityError should be caught and returned as error string."""
    result = execute_file_tool("file_read", {"path": "/etc/passwd"}, guard)
    assert result.startswith("Error:")
    assert "Absolute paths" in result


# --- file_write ---

def test_write_creates_file(project, guard):
    result = execute_file_tool("file_write", {
        "path": "src/new.py",
        "content": "# new file",
    }, guard)
    assert result.startswith("Written:")
    assert (project / "src" / "new.py").read_text() == "# new file"


def test_write_creates_parent_dirs(project, guard):
    result = execute_file_tool("file_write", {
        "path": "docs/api/readme.md",
        "content": "# API docs",
    }, guard)
    assert result.startswith("Written:")
    assert (project / "docs" / "api" / "readme.md").read_text() == "# API docs"


def test_write_overwrites_existing(project, guard):
    (project / "src" / "main.py").write_text("old content")
    execute_file_tool("file_write", {
        "path": "src/main.py",
        "content": "new content",
    }, guard)
    assert (project / "src" / "main.py").read_text() == "new content"


def test_write_content_too_large(project, guard):
    small_guard = FileGuard(project, {
        "writable_paths": ["src/**"],
        "max_file_size_bytes": 10,
    })
    result = execute_file_tool("file_write", {
        "path": "src/big.py",
        "content": "x" * 50,
    }, small_guard)
    assert result.startswith("Error: content too large")
    assert not (project / "src" / "big.py").exists()


def test_write_protected_returns_error_string(project, guard):
    """SecurityError caught, returned as string, not raised."""
    result = execute_file_tool("file_write", {
        "path": ".team/team.json",
        "content": "hacked",
    }, guard)
    assert result.startswith("Error:")
    assert "Protected path" in result


def test_write_outside_writable_returns_error(project, guard):
    result = execute_file_tool("file_write", {
        "path": "README.md",
        "content": "hello",
    }, guard)
    assert result.startswith("Error:")
    assert "not in writable paths" in result


def test_write_reports_byte_count(project, guard):
    result = execute_file_tool("file_write", {
        "path": "src/main.py",
        "content": "hello",
    }, guard)
    assert "5 bytes" in result


# --- file_list ---

def test_list_directory(project, guard):
    (project / "src" / "a.py").touch()
    (project / "src" / "b.py").touch()
    (project / "src" / "sub").mkdir()
    result = execute_file_tool("file_list", {"path": "src"}, guard)
    lines = result.split("\n")
    assert "a.py" in lines
    assert "b.py" in lines
    assert "sub/" in lines


def test_list_sorted(project, guard):
    (project / "src" / "z.py").touch()
    (project / "src" / "a.py").touch()
    (project / "src" / "m.py").touch()
    result = execute_file_tool("file_list", {"path": "src"}, guard)
    lines = result.split("\n")
    assert lines == ["a.py", "m.py", "z.py"]


def test_list_empty_directory(project, guard):
    (project / "src" / "empty").mkdir()
    result = execute_file_tool("file_list", {"path": "src/empty"}, guard)
    assert result == "(empty directory)"


def test_list_missing_directory(project, guard):
    result = execute_file_tool("file_list", {"path": "nonexistent"}, guard)
    assert result.startswith("Error: directory not found")


def test_list_file_not_dir(project, guard):
    (project / "src" / "main.py").touch()
    result = execute_file_tool("file_list", {"path": "src/main.py"}, guard)
    assert result.startswith("Error: not a directory")


def test_list_includes_hidden_files(project, guard):
    (project / "src" / ".gitignore").touch()
    (project / "src" / "main.py").touch()
    result = execute_file_tool("file_list", {"path": "src"}, guard)
    assert ".gitignore" in result
    assert "main.py" in result


# --- Unknown tool ---

def test_unknown_tool_returns_error(project, guard):
    result = execute_file_tool("bash_exec", {"cmd": "ls"}, guard)
    assert result.startswith("Error: unknown tool")


# --- format_tool_operation ---

def test_format_read():
    op = {"name": "file_read", "input": {"path": "src/main.py"}, "result": "content"}
    assert format_tool_operation(op) == "[file_read] src/main.py"


def test_format_write():
    op = {"name": "file_write", "input": {"path": "src/main.py", "content": "hello"}, "result": "Written: src/main.py (5 bytes)"}
    assert format_tool_operation(op) == "[file_write] src/main.py (5 bytes)"


def test_format_list():
    op = {"name": "file_list", "input": {"path": "src/"}, "result": "a.py\nb.py"}
    assert format_tool_operation(op) == "[file_list] src/"


def test_format_denied():
    op = {"name": "file_write", "input": {"path": ".team/team.json", "content": "x"}, "result": "Error: Protected path: .team/team.json"}
    result = format_tool_operation(op)
    assert result.startswith("[file_write] DENIED:")
    assert ".team/team.json" in result


def test_format_pending():
    op = {"name": "file_write", "input": {"path": "Dockerfile", "content": "FROM python"}, "result": "Pending approval [a1]: write to Dockerfile"}
    result = format_tool_operation(op)
    assert result.startswith("[file_write] PENDING APPROVAL:")
    assert "Dockerfile" in result


# --- Missing key validation ---

def test_read_missing_path_key(project, guard):
    result = execute_file_tool("file_read", {}, guard)
    assert result.startswith("Error: malformed tool call")
    assert "path" in result


def test_write_missing_path_key(project, guard):
    result = execute_file_tool("file_write", {"content": "hello"}, guard)
    assert result.startswith("Error: malformed tool call")
    assert "path" in result


def test_write_missing_content_key(project, guard):
    result = execute_file_tool("file_write", {"path": "src/main.py"}, guard)
    assert result.startswith("Error: malformed tool call")
    assert "content" in result


def test_list_missing_path_key(project, guard):
    result = execute_file_tool("file_list", {}, guard)
    assert result.startswith("Error: malformed tool call")
    assert "path" in result


# --- Approval-aware writes ---

def test_write_with_approval_store_writable_succeeds(project):
    """Writable path writes immediately even with approval store present."""
    from gotg.approvals import ApprovalStore
    guard = FileGuard(project, {"writable_paths": ["src/**"], "enable_approvals": True})
    store = ApprovalStore(project / "approvals.json")
    result = execute_file_tool("file_write", {"path": "src/main.py", "content": "hello"}, guard, approval_store=store, agent_name="agent-1")
    assert result.startswith("Written:")
    assert (project / "src" / "main.py").read_text() == "hello"
    assert len(store.get_pending()) == 0


def test_write_with_approval_store_non_writable_creates_pending(project):
    """Non-writable path creates pending request."""
    from gotg.approvals import ApprovalStore
    guard = FileGuard(project, {"writable_paths": ["src/**"], "enable_approvals": True})
    store = ApprovalStore(project / "approvals.json")
    result = execute_file_tool("file_write", {"path": "Dockerfile", "content": "FROM python"}, guard, approval_store=store, agent_name="agent-1")
    assert "Pending approval" in result
    assert "[a1]" in result
    assert not (project / "Dockerfile").exists()
    pending = store.get_pending()
    assert len(pending) == 1
    assert pending[0]["path"] == "Dockerfile"
    assert pending[0]["requested_by"] == "agent-1"


def test_write_with_approval_store_hard_denied_returns_error(project):
    """Hard-denied path still returns error, not pending."""
    from gotg.approvals import ApprovalStore
    guard = FileGuard(project, {"writable_paths": ["src/**"], "enable_approvals": True})
    store = ApprovalStore(project / "approvals.json")
    result = execute_file_tool("file_write", {"path": ".team/hack.json", "content": "evil"}, guard, approval_store=store, agent_name="agent-1")
    assert result.startswith("Error:")
    assert len(store.get_pending()) == 0


def test_write_without_approval_store_unchanged(project):
    """Without approval_store, non-writable writes fail as before."""
    guard = FileGuard(project, {"writable_paths": ["src/**"]})
    result = execute_file_tool("file_write", {"path": "Dockerfile", "content": "FROM python"}, guard)
    assert result.startswith("Error:")
    assert not (project / "Dockerfile").exists()
