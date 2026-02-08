import json
import shutil
from datetime import datetime, timezone
from pathlib import Path



CHECKPOINT_EXCLUDE = {"debug.jsonl", "checkpoints"}


def _iter_files(iter_dir: Path) -> list[str]:
    """List all files in iter_dir, excluding debug.jsonl and checkpoints/."""
    return sorted(
        entry.name
        for entry in iter_dir.iterdir()
        if entry.is_file() and entry.name not in CHECKPOINT_EXCLUDE
    )


def _next_checkpoint_number(iter_dir: Path) -> int:
    """Return the next checkpoint number (max existing + 1, or 1)."""
    cp_dir = iter_dir / "checkpoints"
    if not cp_dir.exists():
        return 1
    numbers = []
    for entry in cp_dir.iterdir():
        if entry.is_dir():
            try:
                numbers.append(int(entry.name))
            except ValueError:
                pass
    return max(numbers) + 1 if numbers else 1


def _count_agent_turns(iter_dir: Path, coach_name: str = "coach") -> int:
    """Count engineering agent turns in conversation.jsonl."""
    log_path = iter_dir / "conversation.jsonl"
    if not log_path.exists():
        return 0
    non_agent = {"human", "system", coach_name}
    count = 0
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            if msg.get("from") not in non_agent:
                count += 1
        except (json.JSONDecodeError, AttributeError):
            pass  # skip malformed lines
    return count


def create_checkpoint(
    iter_dir: Path,
    iteration: dict,
    description: str | None = None,
    trigger: str = "auto",
    coach_name: str = "coach",
) -> int:
    """Create a checkpoint of the current iteration state. Returns checkpoint number."""
    number = _next_checkpoint_number(iter_dir)
    cp_path = iter_dir / "checkpoints" / str(number)
    cp_path.mkdir(parents=True)

    # Copy all non-excluded files
    for filename in _iter_files(iter_dir):
        shutil.copy2(iter_dir / filename, cp_path / filename)

    # Write metadata
    state = {
        "number": number,
        "phase": iteration.get("phase", "grooming"),
        "status": iteration.get("status", "in-progress"),
        "max_turns": iteration.get("max_turns", 0),
        "turn_count": _count_agent_turns(iter_dir, coach_name=coach_name),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "description": description or f"Auto after {trigger}",
        "trigger": trigger,
    }
    (cp_path / "state.json").write_text(json.dumps(state, indent=2) + "\n")

    return number


def list_checkpoints(iter_dir: Path) -> list[dict]:
    """List all checkpoints for an iteration, sorted by number."""
    cp_dir = iter_dir / "checkpoints"
    if not cp_dir.exists():
        return []
    checkpoints = []
    for entry in cp_dir.iterdir():
        if not entry.is_dir():
            continue
        state_path = entry / "state.json"
        if not state_path.exists():
            continue
        checkpoints.append(json.loads(state_path.read_text()))
    checkpoints.sort(key=lambda c: c["number"])
    return checkpoints


def restore_checkpoint(iter_dir: Path, number: int) -> dict:
    """Restore iteration to a checkpoint. Returns the checkpoint's state dict."""
    cp_path = iter_dir / "checkpoints" / str(number)
    if not cp_path.exists():
        raise ValueError(f"Checkpoint {number} does not exist")

    state = json.loads((cp_path / "state.json").read_text())

    # Remove current files (clean slate)
    for filename in _iter_files(iter_dir):
        (iter_dir / filename).unlink()

    # Copy checkpoint files back (exclude state.json)
    for entry in cp_path.iterdir():
        if entry.is_file() and entry.name != "state.json":
            shutil.copy2(entry, iter_dir / entry.name)

    return state
