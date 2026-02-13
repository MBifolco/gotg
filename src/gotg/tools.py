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
    path = tool_input.get("path", "")

    if result.startswith("Error:"):
        return f"[{name}] DENIED: {path} — {result}"

    if result.startswith("Pending approval"):
        return f"[{name}] PENDING APPROVAL: {path} — {result}"

    if name == "file_read":
        return f"[file_read] {path}"
    elif name == "file_write":
        size = len(tool_input.get("content", "").encode())
        return f"[file_write] {path} ({size} bytes)"
    elif name == "file_list":
        return f"[file_list] {path}"
    return f"[{name}] {path}"


def format_agent_tool_operation(agent_name: str, op: dict) -> str:
    """Format a tool operation with explicit actor attribution."""
    return f"[{agent_name}] {format_tool_operation(op)}"
