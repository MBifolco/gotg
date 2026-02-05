import json
from pathlib import Path

AGENT_COLORS = {
    "agent-1": "\033[36m",  # cyan
    "agent-2": "\033[33m",  # yellow
}
RESET = "\033[0m"
BOLD = "\033[1m"


def read_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    messages = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            messages.append(json.loads(line))
    return messages


def append_message(path: Path, msg: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(msg) + "\n")
        f.flush()


def render_message(msg: dict) -> str:
    name = msg["from"]
    content = msg["content"]
    color = AGENT_COLORS.get(name, "\033[37m")  # default white
    return f"{BOLD}{color}[{name}]{RESET} {content}"
