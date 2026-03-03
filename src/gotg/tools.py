from gotg.events import ToolCallProgress
from gotg.fileguard import (
    FileGuard, SecurityError,
    WRITE_ALLOWED, WRITE_APPROVAL_REQUIRED, WRITE_DENIED,
)


FILE_TOOLS = [
    {
        "name": "file_read",
        "description": "Read a file's contents. Path is relative to project root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path (e.g., 'src/main.py')",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "file_write",
        "description": (
            "Write content to a file. Creates parent directories if needed. "
            "Path is relative to project root."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path (e.g., 'src/main.py')",
                },
                "content": {
                    "type": "string",
                    "description": "File content to write",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "file_list",
        "description": (
            "List files and directories at a path. "
            "Path is relative to project root. Use '.' for project root."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to directory (e.g., 'src/')",
                }
            },
            "required": ["path"],
        },
    },
]


FILE_DELETE_TOOL = {
    "name": "file_delete",
    "description": (
        "Delete a file. Always requires PM approval. "
        "Path is relative to project root."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to file to delete (e.g., 'src/old.py')",
            },
            "reason": {
                "type": "string",
                "description": "Why this file should be deleted",
            },
        },
        "required": ["path", "reason"],
    },
}


FILE_RENAME_TOOL = {
    "name": "file_rename",
    "description": (
        "Rename/move a file. Always requires PM approval. "
        "Paths are relative to project root."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Current relative path (e.g., 'src/old.py')",
            },
            "destination": {
                "type": "string",
                "description": "New relative path (e.g., 'src/new.py')",
            },
            "reason": {
                "type": "string",
                "description": "Why this file should be renamed/moved",
            },
        },
        "required": ["source", "destination", "reason"],
    },
}


APPROVAL_REQUIRED_FILE_TOOLS = [FILE_DELETE_TOOL, FILE_RENAME_TOOL]


READ_ONLY_FILE_TOOLS = [t for t in FILE_TOOLS if t["name"] != "file_write"]


def execute_file_tool(
    tool_name: str,
    tool_input: dict,
    fileguard: FileGuard,
    approval_store=None,
    agent_name: str = "",
) -> str:
    """Execute a file tool call. Always returns a string — never raises."""
    try:
        if tool_name == "file_read":
            return _do_file_read(tool_input, fileguard)
        elif tool_name == "file_write":
            return _do_file_write(tool_input, fileguard, approval_store, agent_name)
        elif tool_name == "file_list":
            return _do_file_list(tool_input, fileguard)
        elif tool_name == "file_delete":
            return _do_file_delete(tool_input, fileguard, approval_store, agent_name)
        elif tool_name == "file_rename":
            return _do_file_rename(tool_input, fileguard, approval_store, agent_name)
        else:
            return f"Error: unknown tool: {tool_name}"
    except SecurityError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


def _do_file_read(tool_input: dict, fileguard: FileGuard) -> str:
    if "path" not in tool_input:
        return "Error: malformed tool call — missing 'path' field"
    path = fileguard.validate_read(tool_input["path"])
    if not path.exists():
        return f"Error: file not found: {tool_input['path']}"
    if not path.is_file():
        return f"Error: not a file: {tool_input['path']}"
    content = path.read_text()
    if len(content.encode()) > fileguard.max_file_size:
        return f"Error: file too large ({len(content.encode())} bytes, limit {fileguard.max_file_size})"
    return content


def _do_file_write(tool_input: dict, fileguard: FileGuard, approval_store=None, agent_name: str = "") -> str:
    if "path" not in tool_input:
        return "Error: malformed tool call — missing 'path' field"
    if "content" not in tool_input:
        return "Error: malformed tool call — missing 'content' field"
    content = tool_input["content"]
    size = len(content.encode())
    if size > fileguard.max_file_size:
        return f"Error: content too large ({size} bytes, limit {fileguard.max_file_size})"

    if approval_store and fileguard.enable_approvals:
        decision, resolved, reason = fileguard.check_write(tool_input["path"])

        if decision == WRITE_ALLOWED:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content)
            return f"Written: {tool_input['path']} ({size} bytes)"
        elif decision == WRITE_APPROVAL_REQUIRED:
            req_id = approval_store.add_request(
                path=tool_input["path"],
                content=content,
                requested_by=agent_name,
                tool_input=tool_input,
            )
            return (
                f"Pending approval [{req_id}]: write to {tool_input['path']} "
                f"({size} bytes) requires PM approval. "
                f"The file will be written after approval."
            )
        else:
            return f"Error: {reason}"
    else:
        path = fileguard.validate_write(tool_input["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return f"Written: {tool_input['path']} ({size} bytes)"


def _do_file_delete(tool_input: dict, fileguard: FileGuard, approval_store=None, agent_name: str = "") -> str:
    if "path" not in tool_input:
        return "Error: malformed tool call — missing 'path' field"
    if "reason" not in tool_input:
        return "Error: malformed tool call — missing 'reason' field"

    if approval_store is None:
        return "Error: file_delete requires the approval system to be enabled"

    decision, resolved, reason = fileguard.check_delete(tool_input["path"])
    if decision == WRITE_DENIED:
        return f"Error: {reason}"

    # Preflight: verify file exists and is a file before creating approval
    if resolved is not None:
        if not resolved.exists():
            return f"Error: file not found: {tool_input['path']}"
        if not resolved.is_file():
            return f"Error: not a file: {tool_input['path']}"

    req_id = approval_store.add_request(
        path=tool_input["path"],
        content="",
        requested_by=agent_name,
        tool_input=tool_input,
        operation="delete",
    )
    return (
        f"Pending approval [{req_id}]: delete {tool_input['path']} "
        f"requires PM approval. The file will be deleted after approval."
    )


def _do_file_rename(tool_input: dict, fileguard: FileGuard, approval_store=None, agent_name: str = "") -> str:
    if "source" not in tool_input:
        return "Error: malformed tool call — missing 'source' field"
    if "destination" not in tool_input:
        return "Error: malformed tool call — missing 'destination' field"
    if "reason" not in tool_input:
        return "Error: malformed tool call — missing 'reason' field"

    if approval_store is None:
        return "Error: file_rename requires the approval system to be enabled"

    decision, resolved_src, resolved_dst, reason = fileguard.check_rename(
        tool_input["source"], tool_input["destination"],
    )
    if decision == WRITE_DENIED:
        return f"Error: {reason}"

    # Preflight: source must exist and be a file
    if resolved_src is not None:
        if not resolved_src.exists():
            return f"Error: source not found: {tool_input['source']}"
        if not resolved_src.is_file():
            return f"Error: source is not a file: {tool_input['source']}"

    # Preflight: destination must not already exist (no silent overwrite)
    if resolved_dst is not None and resolved_dst.exists():
        return f"Error: destination already exists: {tool_input['destination']}"

    req_id = approval_store.add_request(
        path=tool_input["source"],
        content="",
        requested_by=agent_name,
        tool_input=tool_input,
        operation="rename",
        destination=tool_input["destination"],
    )
    return (
        f"Pending approval [{req_id}]: rename {tool_input['source']} -> "
        f"{tool_input['destination']} requires PM approval. "
        f"The file will be renamed after approval."
    )


def _do_file_list(tool_input: dict, fileguard: FileGuard) -> str:
    if "path" not in tool_input:
        return "Error: malformed tool call — missing 'path' field"
    path = fileguard.validate_list(tool_input["path"])
    if not path.exists():
        return f"Error: directory not found: {tool_input['path']}"
    if not path.is_dir():
        return f"Error: not a directory: {tool_input['path']}"
    entries = sorted(path.iterdir(), key=lambda e: e.name)
    lines = []
    for entry in entries:
        suffix = "/" if entry.is_dir() else ""
        lines.append(f"{entry.name}{suffix}")
    return "\n".join(lines) if lines else "(empty directory)"


def format_tool_operation(op: dict) -> str:
    """Format a tool operation for the conversation log."""
    name = op["name"]
    tool_input = op["input"]
    result = op["result"]
    path = tool_input.get("path", "") or tool_input.get("source", "")

    # Build display path — rename shows src -> dst
    if name == "file_rename":
        dst = tool_input.get("destination", "")
        path_display = f"{path} -> {dst}" if dst else path
    else:
        path_display = path

    if result.startswith("Error:"):
        return f"[{name}] DENIED: {path_display} — {result}"

    if result.startswith("Pending approval"):
        return f"[{name}] PENDING APPROVAL: {path_display} — {result}"

    if name == "file_read":
        return f"[file_read] {path_display}"
    elif name == "file_write":
        size = len(tool_input.get("content", "").encode())
        return f"[file_write] {path_display} ({size} bytes)"
    elif name == "file_list":
        return f"[file_list] {path_display}"
    elif name == "file_delete":
        return f"[file_delete] {path_display}"
    elif name == "file_rename":
        return f"[file_rename] {path_display}"
    return f"[{name}] {path_display}"


def format_agent_tool_operation(agent_name: str, op: dict) -> str:
    """Format a tool operation with explicit actor attribution."""
    return f"[{agent_name}] {format_tool_operation(op)}"


def classify_tool_result(result_str: str) -> str:
    """Derive status from tool result string prefix."""
    if result_str.startswith("Error:"):
        return "error"
    if result_str.startswith("Pending approval"):
        return "pending_approval"
    return "ok"


def make_tool_progress(agent: str, tool_name: str, tool_input: dict, result: str) -> ToolCallProgress:
    """Build a ToolCallProgress event from a tool call and its result."""
    status = classify_tool_result(result)
    content_size = None
    if tool_name == "file_write":
        content_size = len(tool_input.get("content", "").encode())
    path = tool_input.get("path", "") or tool_input.get("source", "")
    if tool_name == "file_rename":
        dst = tool_input.get("destination", "")
        path = f"{path} -> {dst}" if dst else path
    return ToolCallProgress(
        agent=agent,
        tool_name=tool_name,
        path=path,
        status=status,
        bytes=content_size,
        error=result if status == "error" else None,
    )
