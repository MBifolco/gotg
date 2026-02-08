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
    ) -> str:
        """Add a pending approval request. Returns the request ID."""
        request_id = self._next_id()
        request = {
            "id": request_id,
            "status": "pending",
            "path": path,
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


def apply_approved_writes(store: ApprovalStore, fileguard: FileGuard) -> list:
    """Execute approved writes. Returns list of result dicts.

    Each result: {"id": str, "path": str, "success": bool, "message": str}
    Approved writes still go through containment + hard-deny checks.
    """
    results = []
    for req in store.get_approved_unapplied():
        path_str = req["path"]
        content = req["content"]
        try:
            resolved = fileguard.validate_write_approved(path_str)
            size = len(content.encode())
            if size > fileguard.max_file_size:
                results.append({
                    "id": req["id"],
                    "path": path_str,
                    "success": False,
                    "message": f"Error: content too large ({size} bytes)",
                })
                continue
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content)
            store.mark_applied(req["id"])
            results.append({
                "id": req["id"],
                "path": path_str,
                "success": True,
                "message": f"Written: {path_str} ({size} bytes) [approved]",
            })
        except SecurityError as e:
            results.append({
                "id": req["id"],
                "path": path_str,
                "success": False,
                "message": f"Error: {e}",
            })
    return results
