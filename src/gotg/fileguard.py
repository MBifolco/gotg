import fnmatch
from pathlib import Path, PurePath


class SecurityError(Exception):
    """Raised when a file operation violates safety boundaries."""
    pass


# Always blocked for writes, regardless of user config
HARD_DENY_DIRS = {".team", ".git"}

# Write check decisions (used by check_write)
WRITE_ALLOWED = "allowed"
WRITE_APPROVAL_REQUIRED = "approval_required"
WRITE_DENIED = "denied"


def _path_matches_pattern(rel_str: str, filename: str, pattern: str) -> bool:
    """Check if a relative path matches a pattern.

    Supports:
    - "dir/**" — matches anything under dir/
    - "*.ext" — matches filename with fnmatch
    """
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return rel_str.startswith(prefix + "/") or rel_str == prefix
    return fnmatch.fnmatch(filename, pattern)


class FileGuard:
    """Validates and constrains file operations to project boundaries."""

    def __init__(self, project_root: Path, config: dict, fallback_root: Path | None = None):
        self.project_root = Path(project_root).resolve()
        self.writable_paths = config.get("writable_paths", [])
        self.protected_paths = config.get("protected_paths", [])
        self.max_file_size = config.get("max_file_size_bytes", 1_048_576)
        self.max_files_per_turn = config.get("max_files_per_turn", 10)
        self.enable_approvals = config.get("enable_approvals", False)
        self.fallback_root = Path(fallback_root).resolve() if fallback_root else None

    def validate_read(self, relative_path: str) -> Path:
        """Validate a read operation. Returns resolved absolute path.

        If the file doesn't exist in project_root and fallback_root is set,
        tries resolving against fallback_root (same security checks apply).
        """
        resolved = self._resolve_and_contain(relative_path)
        rel = resolved.relative_to(self.project_root)
        if self._is_env_file(rel):
            raise SecurityError(f"Protected path: {rel}")
        if not resolved.exists() and self.fallback_root:
            fallback = self._resolve_fallback(relative_path)
            if fallback is not None:
                return fallback
        return resolved

    def validate_write(self, relative_path: str) -> Path:
        """Validate a write operation. Returns resolved absolute path."""
        resolved = self._resolve_and_contain(relative_path)
        rel = resolved.relative_to(self.project_root)

        if self._is_hard_denied(rel):
            raise SecurityError(f"Protected path: {rel}")

        if self._is_protected(rel):
            raise SecurityError(f"Protected path: {rel}")

        if not self._is_writable(rel):
            raise SecurityError(f"Path not in writable paths: {rel}")

        return resolved

    def check_write(self, relative_path: str) -> tuple:
        """Check a write without raising. Returns (decision, resolved_path, reason).

        decision: WRITE_ALLOWED, WRITE_APPROVAL_REQUIRED, or WRITE_DENIED
        """
        try:
            resolved = self._resolve_and_contain(relative_path)
        except SecurityError as e:
            return (WRITE_DENIED, None, str(e))

        rel = resolved.relative_to(self.project_root)

        if self._is_hard_denied(rel):
            return (WRITE_DENIED, resolved, f"Protected path: {rel}")

        if self._is_protected(rel):
            return (WRITE_DENIED, resolved, f"Protected path: {rel}")

        if self._is_writable(rel):
            return (WRITE_ALLOWED, resolved, "")

        # Within project but not in writable_paths
        if self.enable_approvals:
            return (WRITE_APPROVAL_REQUIRED, resolved, f"Path not in writable paths: {rel}")

        return (WRITE_DENIED, resolved, f"Path not in writable paths: {rel}")

    def validate_write_approved(self, relative_path: str) -> Path:
        """Validate a write for an approved request.

        Bypasses writable_paths check but enforces containment, hard-deny, and protected.
        """
        resolved = self._resolve_and_contain(relative_path)
        rel = resolved.relative_to(self.project_root)

        if self._is_hard_denied(rel):
            raise SecurityError(f"Protected path: {rel}")

        if self._is_protected(rel):
            raise SecurityError(f"Protected path: {rel}")

        return resolved

    def with_root(self, new_root: Path) -> "FileGuard":
        """Create a new FileGuard with same config but different project root.

        The original project_root becomes the fallback_root, so reads that
        miss in the worktree can fall back to committed code on main.
        """
        return FileGuard(new_root, {
            "writable_paths": self.writable_paths,
            "protected_paths": self.protected_paths,
            "max_file_size_bytes": self.max_file_size,
            "max_files_per_turn": self.max_files_per_turn,
            "enable_approvals": self.enable_approvals,
        }, fallback_root=self.project_root)

    def validate_list(self, relative_path: str) -> Path:
        """Validate a list/directory operation. Returns resolved absolute path.

        If the directory doesn't exist in project_root and fallback_root is set,
        tries resolving against fallback_root.
        """
        resolved = self._resolve_and_contain(relative_path)
        if not resolved.exists() and self.fallback_root:
            fallback = self._resolve_fallback(relative_path)
            if fallback is not None:
                return fallback
        return resolved

    def _resolve_and_contain(self, relative_path: str) -> Path:
        """Resolve path and verify it's within project root."""
        if not relative_path:
            return self.project_root

        if relative_path.startswith("/"):
            raise SecurityError(f"Absolute paths not allowed: {relative_path}")

        if ".." in PurePath(relative_path).parts:
            raise SecurityError(f"Path traversal not allowed: {relative_path}")

        resolved = (self.project_root / relative_path).resolve()

        if not resolved.is_relative_to(self.project_root):
            raise SecurityError(
                f"Path escapes project root: {relative_path}"
            )

        return resolved

    def _resolve_fallback(self, relative_path: str) -> Path | None:
        """Try resolving a read path against fallback_root.

        Returns the resolved path if it exists and passes security checks,
        otherwise None.
        """
        if not self.fallback_root or not relative_path:
            return None
        if relative_path.startswith("/"):
            return None
        if ".." in PurePath(relative_path).parts:
            return None
        resolved = (self.fallback_root / relative_path).resolve()
        if not resolved.is_relative_to(self.fallback_root):
            return None
        rel = resolved.relative_to(self.fallback_root)
        if self._is_env_file(rel):
            return None
        if not resolved.exists():
            return None
        return resolved

    def _is_hard_denied(self, rel: PurePath) -> bool:
        """Check non-configurable deny list."""
        parts = rel.parts
        if parts and parts[0] in HARD_DENY_DIRS:
            return True
        return self._is_env_file(rel)

    def _is_env_file(self, rel: PurePath) -> bool:
        """Check if path is a .env file (any variant)."""
        name = rel.name
        return name == ".env" or name.startswith(".env.") or name.endswith(".env")

    def _is_protected(self, rel: PurePath) -> bool:
        """Check user-configured protected_paths."""
        rel_str = str(rel)
        filename = rel.name
        return any(
            _path_matches_pattern(rel_str, filename, p)
            for p in self.protected_paths
        )

    def _is_writable(self, rel: PurePath) -> bool:
        """Check if path matches any writable_paths pattern."""
        if not self.writable_paths:
            return False
        rel_str = str(rel)
        filename = rel.name
        return any(
            _path_matches_pattern(rel_str, filename, p)
            for p in self.writable_paths
        )
