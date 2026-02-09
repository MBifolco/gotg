import json
from pathlib import Path

AGENT_COLORS = {
    "agent-1": "\033[36m",  # cyan
    "agent-2": "\033[33m",  # yellow
    "human": "\033[32m",    # green
    "system": "\033[35m",  # magenta
    "coach": "\033[38;5;208m",  # orange
}
RESET = "\033[0m"
BOLD = "\033[1m"


def read_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    messages = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # skip malformed lines
    return messages


def append_message(path: Path, msg: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(msg) + "\n")
        f.flush()


def append_debug(path: Path, entry: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")
        f.flush()


def read_phase_history(path: Path) -> list[dict]:
    """Read conversation log, returning only messages after the last boundary."""
    all_msgs = read_log(path)
    for i in range(len(all_msgs) - 1, -1, -1):
        if all_msgs[i].get("phase_boundary"):
            return all_msgs[i + 1:]
    return all_msgs  # No boundary — return full history


def render_message(msg: dict) -> str:
    name = msg["from"]
    content = msg["content"]
    color = AGENT_COLORS.get(name, "\033[37m")  # default white
    return f"{BOLD}{color}[{name}]{RESET} {content}"
