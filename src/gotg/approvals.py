import json
from datetime import datetime, timezone
from pathlib import Path

from gotg.fileguard import FileGuard, SecurityError


class ApprovalStore:
    """Manages pending/resolved approval requests in approvals.json."""

    def __init__(self, approvals_path: Path):
        self.path = approvals_path
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"requests": []}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2) + "\n")

    def add_request(
        self,
        path: str,
        content: str,
        requested_by: str,
        tool_input: dict,
        *,
        operation: str = "write",
        destination: str = "",
    ) -> str:
        """Add a pending approval request. Returns the request ID."""
        request_id = self._next_id()
        request = {
            "id": request_id,
            "status": "pending",
            "operation": operation,
            "path": path,
            "destination": destination,
            "content": content,
            "content_size": len(content.encode()),
            "requested_by": requested_by,
            "tool_input": tool_input,
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "resolved_at": None,
            "resolved_by": None,
            "denial_reason": None,
        }
        self._data["requests"].append(request)
        self._save()
        return request_id

    def approve(self, request_id: str) -> dict:
        """Mark a request as approved. Returns the request dict."""
        req = self._get(request_id)
        if req["status"] != "pending":
            raise ValueError(f"Request {request_id} is already {req['status']}")
        req["status"] = "approved"
        req["resolved_at"] = datetime.now(timezone.utc).isoformat()
        req["resolved_by"] = "pm"
        self._save()
        return req

    def deny(self, request_id: str, reason: str = "") -> dict:
        """Mark a request as denied with optional reason. Returns the request dict."""
        req = self._get(request_id)
        if req["status"] != "pending":
            raise ValueError(f"Request {request_id} is already {req['status']}")
        req["status"] = "denied"
        req["denial_reason"] = reason
        req["resolved_at"] = datetime.now(timezone.utc).isoformat()
        req["resolved_by"] = "pm"
        self._save()
        return req

    def approve_all(self) -> list:
        """Approve all pending requests. Returns list of approved requests."""
        approved = []
        for req in self._data["requests"]:
            if req["status"] == "pending":
                req["status"] = "approved"
                req["resolved_at"] = datetime.now(timezone.utc).isoformat()
                req["resolved_by"] = "pm"
                approved.append(req)
        self._save()
        return approved

    def get_pending(self) -> list:
        return [r for r in self._data["requests"] if r["status"] == "pending"]

    def get_approved_unapplied(self) -> list:
        return [
            r for r in self._data["requests"]
            if r["status"] == "approved" and not r.get("applied")
        ]

    def get_denied_uninjected(self) -> list:
        return [
            r for r in self._data["requests"]
            if r["status"] == "denied" and not r.get("injected")
        ]

    def mark_applied(self, request_id: str) -> None:
        """Mark an approved request as having been written to disk."""
        req = self._get(request_id)
        req["applied"] = True
        req["applied_at"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def mark_injected(self, request_id: str) -> None:
        """Mark a denied request as having been injected into conversation."""
        req = self._get(request_id)
        req["injected"] = True
        self._save()

    def _get(self, request_id: str) -> dict:
        for req in self._data["requests"]:
            if req["id"] == request_id:
                return req
        raise ValueError(f"Request {request_id} not found")

    def _next_id(self) -> str:
        """Generate sequential ID: a1, a2, a3...

        Based on total request count (not just pending). Safe as long as
        requests are never deleted — only status transitions.
        """
        existing = len(self._data["requests"])
        return f"a{existing + 1}"


def _apply_write(req: dict, fg: FileGuard, store: ApprovalStore) -> dict:
    """Apply an approved write request."""
    path_str = req["path"]
    content = req.get("content", "")
    resolved = fg.validate_write_approved(path_str)
    size = len(content.encode())
    if size > fg.max_file_size:
        return {
            "id": req["id"],
            "path": path_str,
            "operation": "write",
            "success": False,
            "message": f"Error: content too large ({size} bytes)",
        }
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content)
    store.mark_applied(req["id"])
    return {
        "id": req["id"],
        "path": path_str,
        "operation": "write",
        "success": True,
        "message": f"Written: {path_str} ({size} bytes) [approved]",
    }


def _apply_delete(req: dict, fg: FileGuard, store: ApprovalStore) -> dict:
    """Apply an approved delete request."""
    path_str = req["path"]
    resolved = fg.validate_delete_approved(path_str)

    if not resolved.exists():
        # Idempotent — file may have been deleted between approval and apply
        store.mark_applied(req["id"])
        return {
            "id": req["id"],
            "path": path_str,
            "operation": "delete",
            "success": True,
            "message": f"Deleted: {path_str} (already absent) [approved]",
        }

    if not resolved.is_file():
        return {
            "id": req["id"],
            "path": path_str,
            "operation": "delete",
            "success": False,
            "message": f"Error: not a file: {path_str}",
        }

    resolved.unlink()
    store.mark_applied(req["id"])
    return {
        "id": req["id"],
        "path": path_str,
        "operation": "delete",
        "success": True,
        "message": f"Deleted: {path_str} [approved]",
    }


def _apply_rename(req: dict, fg: FileGuard, store: ApprovalStore) -> dict:
    """Apply an approved rename request."""
    path_str = req["path"]
    dest_str = req.get("destination", "")
    if not dest_str:
        return {
            "id": req["id"],
            "path": path_str,
            "operation": "rename",
            "success": False,
            "message": "Error: no destination in approval request",
        }

    resolved_src = fg.validate_write_approved(path_str)
    resolved_dst = fg.validate_write_approved(dest_str)

    if not resolved_src.exists():
        return {
            "id": req["id"],
            "path": path_str,
            "operation": "rename",
            "success": False,
            "message": f"Error: source not found: {path_str}",
        }

    if not resolved_src.is_file():
        return {
            "id": req["id"],
            "path": path_str,
            "operation": "rename",
            "success": False,
            "message": f"Error: source is not a file: {path_str}",
        }

    if resolved_dst.exists():
        return {
            "id": req["id"],
            "path": path_str,
            "operation": "rename",
            "success": False,
            "message": f"Error: destination already exists: {dest_str}",
        }

    resolved_dst.parent.mkdir(parents=True, exist_ok=True)
    resolved_src.rename(resolved_dst)
    store.mark_applied(req["id"])
    return {
        "id": req["id"],
        "path": path_str,
        "operation": "rename",
        "success": True,
        "message": f"Renamed: {path_str} -> {dest_str} [approved]",
    }


def apply_approved_writes(
    store: ApprovalStore,
    fileguard: FileGuard,
    fileguard_for_agent=None,
) -> list:
    """Execute approved operations. Returns list of result dicts.

    Each result: {"id": str, "path": str, "operation": str, "success": bool, "message": str}
    Approved operations still go through containment + hard-deny checks.

    fileguard_for_agent: optional callable(agent_name) -> FileGuard.
    When provided, uses the returned FileGuard for that agent's operations
    (e.g., to resolve to agent's worktree instead of project root).
    """
    results = []
    for req in store.get_approved_unapplied():
        fg = fileguard
        if fileguard_for_agent:
            fg = fileguard_for_agent(req["requested_by"])

        operation = req.get("operation", "write")
        try:
            if operation == "delete":
                results.append(_apply_delete(req, fg, store))
            elif operation == "rename":
                results.append(_apply_rename(req, fg, store))
            else:
                results.append(_apply_write(req, fg, store))
        except SecurityError as e:
            results.append({
                "id": req["id"],
                "path": req["path"],
                "operation": operation,
                "success": False,
                "message": f"Error: {e}",
            })
    return results
