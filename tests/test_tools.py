from pathlib import Path

import pytest

from gotg.fileguard import FileGuard
from gotg.tools import (
    classify_tool_result,
    execute_file_tool,
    format_agent_tool_operation,
    format_tool_operation,
    make_tool_progress,
)


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


def test_format_agent_operation():
    op = {"name": "file_read", "input": {"path": "src/main.py"}, "result": "content"}
    result = format_agent_tool_operation("agent-1", op)
    assert result == "[agent-1] [file_read] src/main.py"


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


# --- classify_tool_result ---

def test_classify_ok():
    assert classify_tool_result("File content here") == "ok"

def test_classify_error():
    assert classify_tool_result("Error: file not found") == "error"

def test_classify_pending():
    assert classify_tool_result("Pending approval [a1]: write to Dockerfile") == "pending_approval"


# --- make_tool_progress ---

def test_make_tool_progress_file_write():
    p = make_tool_progress("agent-1", "file_write", {"path": "src/main.py", "content": "hello"}, "Written: src/main.py (5 bytes)")
    assert p.agent == "agent-1"
    assert p.tool_name == "file_write"
    assert p.path == "src/main.py"
    assert p.status == "ok"
    assert p.bytes == 5
    assert p.error is None

def test_make_tool_progress_file_read():
    p = make_tool_progress("agent-1", "file_read", {"path": "src/main.py"}, "print('hello')")
    assert p.status == "ok"
    assert p.bytes is None
    assert p.error is None

def test_make_tool_progress_error():
    p = make_tool_progress("agent-1", "file_write", {"path": "bad.py", "content": "x"}, "Error: not in writable paths")
    assert p.status == "error"
    assert p.error == "Error: not in writable paths"
    assert p.bytes == 1


# --- file_delete ---


@pytest.fixture
def approval_project(tmp_path):
    """Project with approvals enabled."""
    (tmp_path / "src").mkdir()
    (tmp_path / ".team").mkdir()
    (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.fixture
def approval_guard(approval_project):
    return FileGuard(approval_project, {
        "writable_paths": ["src/**"],
        "enable_approvals": True,
        "max_file_size_bytes": 1_048_576,
        "max_files_per_turn": 10,
    })


@pytest.fixture
def approval_store(approval_project):
    from gotg.approvals import ApprovalStore
    return ApprovalStore(approval_project / "approvals.json")


def test_delete_creates_pending_approval(approval_project, approval_guard, approval_store):
    (approval_project / "src" / "old.py").write_text("old code")
    result = execute_file_tool(
        "file_delete",
        {"path": "src/old.py", "reason": "replaced by new.py"},
        approval_guard,
        approval_store=approval_store,
        agent_name="agent-1",
    )
    assert "Pending approval" in result
    assert len(approval_store.get_pending()) == 1
    assert (approval_project / "src" / "old.py").exists()  # not yet deleted


def test_delete_hard_denied_returns_error(approval_project, approval_guard, approval_store):
    result = execute_file_tool(
        "file_delete",
        {"path": ".team/config.json", "reason": "cleanup"},
        approval_guard,
        approval_store=approval_store,
        agent_name="agent-1",
    )
    assert result.startswith("Error:")
    assert "Protected path" in result
    assert len(approval_store.get_pending()) == 0


def test_delete_missing_path_key(approval_project, approval_guard, approval_store):
    result = execute_file_tool(
        "file_delete",
        {"reason": "no path"},
        approval_guard,
        approval_store=approval_store,
        agent_name="agent-1",
    )
    assert "missing 'path'" in result


def test_delete_missing_reason_key(approval_project, approval_guard, approval_store):
    result = execute_file_tool(
        "file_delete",
        {"path": "src/old.py"},
        approval_guard,
        approval_store=approval_store,
        agent_name="agent-1",
    )
    assert "missing 'reason'" in result


def test_delete_no_approval_store(approval_project, approval_guard):
    result = execute_file_tool(
        "file_delete",
        {"path": "src/old.py", "reason": "cleanup"},
        approval_guard,
        approval_store=None,
        agent_name="agent-1",
    )
    assert "approval system" in result


def test_delete_nonexistent_file_rejected(approval_project, approval_guard, approval_store):
    result = execute_file_tool(
        "file_delete",
        {"path": "src/nonexistent.py", "reason": "cleanup"},
        approval_guard,
        approval_store=approval_store,
        agent_name="agent-1",
    )
    assert result.startswith("Error:")
    assert "file not found" in result
    assert len(approval_store.get_pending()) == 0


def test_delete_directory_rejected(approval_project, approval_guard, approval_store):
    result = execute_file_tool(
        "file_delete",
        {"path": "src", "reason": "cleanup"},
        approval_guard,
        approval_store=approval_store,
        agent_name="agent-1",
    )
    assert result.startswith("Error:")
    assert "not a file" in result
    assert len(approval_store.get_pending()) == 0


# --- file_rename ---


def test_rename_creates_pending_approval(approval_project, approval_guard, approval_store):
    (approval_project / "src" / "old.py").write_text("code")
    result = execute_file_tool(
        "file_rename",
        {"source": "src/old.py", "destination": "src/new.py", "reason": "better name"},
        approval_guard,
        approval_store=approval_store,
        agent_name="agent-1",
    )
    assert "Pending approval" in result
    assert len(approval_store.get_pending()) == 1
    assert (approval_project / "src" / "old.py").exists()  # not yet renamed


def test_rename_hard_denied_returns_error(approval_project, approval_guard, approval_store):
    result = execute_file_tool(
        "file_rename",
        {"source": ".team/config.json", "destination": "src/config.json", "reason": "move"},
        approval_guard,
        approval_store=approval_store,
        agent_name="agent-1",
    )
    assert result.startswith("Error:")
    assert "Protected path" in result
    assert len(approval_store.get_pending()) == 0


def test_rename_missing_source_key(approval_project, approval_guard, approval_store):
    result = execute_file_tool(
        "file_rename",
        {"destination": "src/new.py", "reason": "move"},
        approval_guard,
        approval_store=approval_store,
        agent_name="agent-1",
    )
    assert "missing 'source'" in result


def test_rename_missing_destination_key(approval_project, approval_guard, approval_store):
    result = execute_file_tool(
        "file_rename",
        {"source": "src/old.py", "reason": "move"},
        approval_guard,
        approval_store=approval_store,
        agent_name="agent-1",
    )
    assert "missing 'destination'" in result


def test_rename_missing_reason_key(approval_project, approval_guard, approval_store):
    result = execute_file_tool(
        "file_rename",
        {"source": "src/old.py", "destination": "src/new.py"},
        approval_guard,
        approval_store=approval_store,
        agent_name="agent-1",
    )
    assert "missing 'reason'" in result


def test_rename_no_approval_store(approval_project, approval_guard):
    result = execute_file_tool(
        "file_rename",
        {"source": "src/old.py", "destination": "src/new.py", "reason": "move"},
        approval_guard,
        approval_store=None,
        agent_name="agent-1",
    )
    assert "approval system" in result


def test_rename_nonexistent_source_rejected(approval_project, approval_guard, approval_store):
    result = execute_file_tool(
        "file_rename",
        {"source": "src/nonexistent.py", "destination": "src/new.py", "reason": "move"},
        approval_guard,
        approval_store=approval_store,
        agent_name="agent-1",
    )
    assert result.startswith("Error:")
    assert "source not found" in result
    assert len(approval_store.get_pending()) == 0


def test_rename_source_is_directory_rejected(approval_project, approval_guard, approval_store):
    result = execute_file_tool(
        "file_rename",
        {"source": "src", "destination": "src2", "reason": "move"},
        approval_guard,
        approval_store=approval_store,
        agent_name="agent-1",
    )
    assert result.startswith("Error:")
    assert "not a file" in result
    assert len(approval_store.get_pending()) == 0


def test_rename_destination_exists_rejected(approval_project, approval_guard, approval_store):
    (approval_project / "src" / "old.py").write_text("old")
    (approval_project / "src" / "new.py").write_text("new")
    result = execute_file_tool(
        "file_rename",
        {"source": "src/old.py", "destination": "src/new.py", "reason": "move"},
        approval_guard,
        approval_store=approval_store,
        agent_name="agent-1",
    )
    assert result.startswith("Error:")
    assert "destination already exists" in result
    assert len(approval_store.get_pending()) == 0


def test_rename_request_stores_destination(approval_project, approval_guard, approval_store):
    (approval_project / "src" / "old.py").write_text("code")
    execute_file_tool(
        "file_rename",
        {"source": "src/old.py", "destination": "src/new.py", "reason": "better name"},
        approval_guard,
        approval_store=approval_store,
        agent_name="agent-1",
    )
    pending = approval_store.get_pending()
    assert len(pending) == 1
    assert pending[0]["destination"] == "src/new.py"
    assert pending[0]["operation"] == "rename"


# --- format_tool_operation: delete and rename ---


def test_format_tool_operation_delete():
    op = {"name": "file_delete", "input": {"path": "src/old.py", "reason": "cleanup"}, "result": "Pending approval [a1]: ..."}
    result = format_tool_operation(op)
    assert "[file_delete]" in result
    assert "src/old.py" in result
    assert "PENDING APPROVAL" in result


def test_format_tool_operation_rename():
    op = {"name": "file_rename", "input": {"source": "src/old.py", "destination": "src/new.py", "reason": "rename"}, "result": "Pending approval [a1]: ..."}
    result = format_tool_operation(op)
    assert "[file_rename]" in result
    assert "src/old.py -> src/new.py" in result
    assert "PENDING APPROVAL" in result


def test_format_tool_operation_rename_denied():
    op = {"name": "file_rename", "input": {"source": "src/old.py", "destination": ".team/bad.py", "reason": "move"}, "result": "Error: Protected path"}
    result = format_tool_operation(op)
    assert "[file_rename]" in result
    assert "src/old.py -> .team/bad.py" in result
    assert "DENIED" in result


def test_format_tool_operation_rename_pending():
    op = {"name": "file_rename", "input": {"source": "a.py", "destination": "b.py", "reason": "r"}, "result": "Pending approval [a1]: rename"}
    result = format_tool_operation(op)
    assert "a.py -> b.py" in result
    assert "PENDING APPROVAL" in result


# --- make_tool_progress: file_rename ---


def test_make_tool_progress_file_rename_shows_src_dst():
    p = make_tool_progress("agent-1", "file_rename", {"source": "src/old.py", "destination": "src/new.py", "reason": "r"}, "Pending approval [a1]: rename")
    assert p.path == "src/old.py -> src/new.py"
    assert p.status == "pending_approval"
