import json

import pytest

from gotg.approvals import ApprovalStore, apply_approved_writes
from gotg.fileguard import FileGuard


@pytest.fixture
def project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / ".team").mkdir()
    return tmp_path


@pytest.fixture
def store(tmp_path):
    return ApprovalStore(tmp_path / "approvals.json")


@pytest.fixture
def guard(project):
    return FileGuard(project, {
        "writable_paths": ["src/**"],
        "enable_approvals": True,
    })


# --- ApprovalStore: add_request ---

def test_add_request_creates_file(tmp_path):
    path = tmp_path / "approvals.json"
    store = ApprovalStore(path)
    store.add_request("Dockerfile", "FROM python", "agent-1", {"path": "Dockerfile", "content": "FROM python"})
    assert path.exists()
    data = json.loads(path.read_text())
    assert len(data["requests"]) == 1


def test_add_request_generates_sequential_ids(store):
    id1 = store.add_request("f1.txt", "a", "agent-1", {})
    id2 = store.add_request("f2.txt", "b", "agent-1", {})
    id3 = store.add_request("f3.txt", "c", "agent-2", {})
    assert id1 == "a1"
    assert id2 == "a2"
    assert id3 == "a3"


def test_add_request_stores_content(store):
    store.add_request("Dockerfile", "FROM python:3.12", "agent-1", {"path": "Dockerfile", "content": "FROM python:3.12"})
    req = store.get_pending()[0]
    assert req["content"] == "FROM python:3.12"
    assert req["content_size"] == len("FROM python:3.12".encode())
    assert req["requested_by"] == "agent-1"
    assert req["status"] == "pending"


def test_add_request_stores_tool_input(store):
    tool_input = {"path": "Dockerfile", "content": "FROM python"}
    store.add_request("Dockerfile", "FROM python", "agent-1", tool_input)
    req = store.get_pending()[0]
    assert req["tool_input"] == tool_input


# --- get_pending ---

def test_get_pending_returns_only_pending(store):
    store.add_request("f1.txt", "a", "agent-1", {})
    store.add_request("f2.txt", "b", "agent-1", {})
    store.approve("a1")
    pending = store.get_pending()
    assert len(pending) == 1
    assert pending[0]["id"] == "a2"


# --- approve ---

def test_approve_changes_status(store):
    store.add_request("f1.txt", "a", "agent-1", {})
    req = store.approve("a1")
    assert req["status"] == "approved"
    assert req["resolved_at"] is not None
    assert req["resolved_by"] == "pm"


def test_approve_already_resolved_raises(store):
    store.add_request("f1.txt", "a", "agent-1", {})
    store.approve("a1")
    with pytest.raises(ValueError, match="already approved"):
        store.approve("a1")


# --- deny ---

def test_deny_changes_status(store):
    store.add_request("f1.txt", "a", "agent-1", {})
    req = store.deny("a1", "Use src/ instead")
    assert req["status"] == "denied"
    assert req["denial_reason"] == "Use src/ instead"
    assert req["resolved_at"] is not None
    assert req["resolved_by"] == "pm"


def test_deny_already_resolved_raises(store):
    store.add_request("f1.txt", "a", "agent-1", {})
    store.deny("a1", "no")
    with pytest.raises(ValueError, match="already denied"):
        store.deny("a1", "no again")


# --- approve_all ---

def test_approve_all_approves_pending_only(store):
    store.add_request("f1.txt", "a", "agent-1", {})
    store.add_request("f2.txt", "b", "agent-1", {})
    store.add_request("f3.txt", "c", "agent-1", {})
    store.deny("a2", "no")
    approved = store.approve_all()
    assert len(approved) == 2
    assert {r["id"] for r in approved} == {"a1", "a3"}


def test_approve_all_empty_when_nothing_pending(store):
    assert store.approve_all() == []


# --- get_approved_unapplied ---

def test_get_approved_unapplied(store):
    store.add_request("f1.txt", "a", "agent-1", {})
    store.add_request("f2.txt", "b", "agent-1", {})
    store.approve("a1")
    store.approve("a2")
    store.mark_applied("a1")
    unapplied = store.get_approved_unapplied()
    assert len(unapplied) == 1
    assert unapplied[0]["id"] == "a2"


# --- get_denied_uninjected ---

def test_get_denied_uninjected(store):
    store.add_request("f1.txt", "a", "agent-1", {})
    store.add_request("f2.txt", "b", "agent-1", {})
    store.deny("a1", "no")
    store.deny("a2", "no")
    store.mark_injected("a1")
    uninjected = store.get_denied_uninjected()
    assert len(uninjected) == 1
    assert uninjected[0]["id"] == "a2"


# --- mark_applied ---

def test_mark_applied_sets_flags(store):
    store.add_request("f1.txt", "a", "agent-1", {})
    store.approve("a1")
    store.mark_applied("a1")
    req = store._get("a1")
    assert req["applied"] is True
    assert req["applied_at"] is not None


# --- mark_injected ---

def test_mark_injected_sets_flag(store):
    store.add_request("f1.txt", "a", "agent-1", {})
    store.deny("a1", "no")
    store.mark_injected("a1")
    req = store._get("a1")
    assert req["injected"] is True


# --- error cases ---

def test_nonexistent_request_raises(store):
    with pytest.raises(ValueError, match="not found"):
        store.approve("a999")


def test_nonexistent_request_deny_raises(store):
    with pytest.raises(ValueError, match="not found"):
        store.deny("a999", "no")


# --- persistence ---

def test_persists_across_instances(tmp_path):
    path = tmp_path / "approvals.json"
    store1 = ApprovalStore(path)
    store1.add_request("f1.txt", "hello", "agent-1", {})
    store2 = ApprovalStore(path)
    assert len(store2.get_pending()) == 1
    assert store2.get_pending()[0]["content"] == "hello"


def test_empty_file_loads_clean(tmp_path):
    path = tmp_path / "nonexistent" / "approvals.json"
    store = ApprovalStore(path)
    assert store.get_pending() == []


# --- apply_approved_writes ---

def test_apply_writes_file_to_disk(project, guard):
    store = ApprovalStore(project / ".team" / "approvals.json")
    store.add_request("Dockerfile", "FROM python:3.12", "agent-1", {})
    store.approve("a1")
    results = apply_approved_writes(store, guard)
    assert len(results) == 1
    assert results[0]["success"] is True
    assert (project / "Dockerfile").read_text() == "FROM python:3.12"


def test_apply_marks_applied(project, guard):
    store = ApprovalStore(project / ".team" / "approvals.json")
    store.add_request("Dockerfile", "FROM python", "agent-1", {})
    store.approve("a1")
    apply_approved_writes(store, guard)
    assert store._get("a1").get("applied") is True


def test_apply_skips_already_applied(project, guard):
    store = ApprovalStore(project / ".team" / "approvals.json")
    store.add_request("Dockerfile", "FROM python", "agent-1", {})
    store.approve("a1")
    apply_approved_writes(store, guard)
    (project / "Dockerfile").write_text("overwritten")
    results = apply_approved_writes(store, guard)
    assert len(results) == 0
    assert (project / "Dockerfile").read_text() == "overwritten"


def test_apply_checks_hard_deny(project, guard):
    store = ApprovalStore(project / ".team" / "approvals.json")
    store.add_request(".team/hack.json", "evil", "agent-1", {})
    store.approve("a1")
    results = apply_approved_writes(store, guard)
    assert len(results) == 1
    assert results[0]["success"] is False
    assert "Protected path" in results[0]["message"]


def test_apply_creates_parent_dirs(project, guard):
    store = ApprovalStore(project / ".team" / "approvals.json")
    store.add_request("newdir/subdir/file.txt", "hello", "agent-1", {})
    store.approve("a1")
    results = apply_approved_writes(store, guard)
    assert results[0]["success"] is True
    assert (project / "newdir" / "subdir" / "file.txt").read_text() == "hello"


def test_apply_checks_file_size(project):
    guard = FileGuard(project, {
        "writable_paths": ["src/**"],
        "enable_approvals": True,
        "max_file_size_bytes": 10,
    })
    store = ApprovalStore(project / ".team" / "approvals.json")
    store.add_request("big.txt", "x" * 100, "agent-1", {})
    store.approve("a1")
    results = apply_approved_writes(store, guard)
    assert results[0]["success"] is False
    assert "too large" in results[0]["message"]


def test_apply_with_fileguard_for_agent(tmp_path):
    """fileguard_for_agent callback routes writes to per-agent directories."""
    # Set up two "worktree" directories
    wt1 = tmp_path / "wt-agent-1"
    wt1.mkdir()
    wt2 = tmp_path / "wt-agent-2"
    wt2.mkdir()

    guard = FileGuard(tmp_path, {"writable_paths": ["src/**"], "enable_approvals": True})
    store = ApprovalStore(tmp_path / "approvals.json")
    store.add_request("README.md", "agent 1 readme", "agent-1", {})
    store.add_request("README.md", "agent 2 readme", "agent-2", {})
    store.approve("a1")
    store.approve("a2")

    def resolver(agent_name):
        if agent_name == "agent-1":
            return guard.with_root(wt1)
        return guard.with_root(wt2)

    results = apply_approved_writes(store, guard, fileguard_for_agent=resolver)
    assert all(r["success"] for r in results)
    assert (wt1 / "README.md").read_text() == "agent 1 readme"
    assert (wt2 / "README.md").read_text() == "agent 2 readme"
    # Main project root should NOT have the file
    assert not (tmp_path / "README.md").exists()
