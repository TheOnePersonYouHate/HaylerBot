"""The shared ship state the whole crew reasons from.

Kept deliberately small: heading, speed, alert level, and freeform notes.
Persisted to a JSON file so the ship's situation survives restarts.
"""
import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class ShipState:
    name: str = "USS Hayler (CG-126)"
    heading: int = 0          # current ordered course, 0-359 degrees
    speed: int = 0            # current ordered speed, knots
    alert: str = "normal"     # "normal" | "alert" | "general quarters"
    notes: str = ""           # freeform situational notes (contacts, damage)

    def summary(self) -> str:
        line = (
            f"Ship: {self.name} | Course: {self.heading:03d}\u00b0 | "
            f"Speed: {self.speed} kts | Alert: {self.alert}"
        )
        if self.notes:
            line += f"\nNotes: {self.notes}"
        return line


def _atomic_write(path: str, content: str) -> None:
    """Write to a temp file then rename over the target, so a crash or kill
    mid-write can never leave a half-written (corrupt) file behind."""
    p = Path(path)
    directory = p.parent if str(p.parent) else Path(".")
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(directory), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # atomic on the same filesystem
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_json(path: str):
    """Parse a JSON file. Missing -> None. Corrupt -> move it aside (so it can't
    break startup) and return None, rather than crashing the bot on boot."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        try:
            os.replace(path, str(p) + ".corrupt")  # keep the bad copy for inspection
        except OSError:
            pass
        return None


def load_states(path: str) -> dict:
    """Load {channel_id: ShipState} from disk -- one ship per RP channel."""
    raw = _load_json(path)
    if not isinstance(raw, dict):
        return {}
    known = {f.name for f in fields(ShipState)}
    states = {}
    for cid, data in raw.items():
        # Skip legacy single-ship files / malformed entries.
        if not str(cid).lstrip("-").isdigit() or not isinstance(data, dict):
            continue
        states[int(cid)] = ShipState(**{k: v for k, v in data.items() if k in known})
    return states


def save_states(states: dict, path: str) -> None:
    raw = {str(cid): asdict(s) for cid, s in states.items()}
    _atomic_write(path, json.dumps(raw, indent=2))


def load_texts(path: str) -> dict:
    """Load {channel_id: text} -- used for the persistent per-channel ship's log."""
    raw = _load_json(path)
    if not isinstance(raw, dict):
        return {}
    return {int(k): str(v) for k, v in raw.items() if str(k).lstrip("-").isdigit()}


def save_texts(texts: dict, path: str) -> None:
    raw = {str(cid): text for cid, text in texts.items()}
    _atomic_write(path, json.dumps(raw, indent=2))
