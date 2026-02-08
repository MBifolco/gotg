from gotg.fileguard import FileGuard, SecurityError


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


def execute_file_tool(tool_name: str, tool_input: dict, fileguard: FileGuard) -> str:
    """Execute a file tool call. Always returns a string — never raises."""
    try:
        if tool_name == "file_read":
            return _do_file_read(tool_input, fileguard)
        elif tool_name == "file_write":
            return _do_file_write(tool_input, fileguard)
        elif tool_name == "file_list":
            return _do_file_list(tool_input, fileguard)
        else:
            return f"Error: unknown tool: {tool_name}"
    except SecurityError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


def _do_file_read(tool_input: dict, fileguard: FileGuard) -> str:
    path = fileguard.validate_read(tool_input["path"])
    if not path.exists():
        return f"Error: file not found: {tool_input['path']}"
    if not path.is_file():
        return f"Error: not a file: {tool_input['path']}"
    content = path.read_text()
    if len(content.encode()) > fileguard.max_file_size:
        return f"Error: file too large ({len(content.encode())} bytes, limit {fileguard.max_file_size})"
    return content


def _do_file_write(tool_input: dict, fileguard: FileGuard) -> str:
    path = fileguard.validate_write(tool_input["path"])
    content = tool_input["content"]
    size = len(content.encode())
    if size > fileguard.max_file_size:
        return f"Error: content too large ({size} bytes, limit {fileguard.max_file_size})"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f"Written: {tool_input['path']} ({size} bytes)"


def _do_file_list(tool_input: dict, fileguard: FileGuard) -> str:
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

    if name == "file_read":
        return f"[file_read] {path}"
    elif name == "file_write":
        size = len(tool_input.get("content", "").encode())
        return f"[file_write] {path} ({size} bytes)"
    elif name == "file_list":
        return f"[file_list] {path}"
    return f"[{name}] {path}"
