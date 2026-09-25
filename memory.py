"""Small structured memory that is not chat scrollback.

Pins and the scene seed are per channel, written like the other JSON state
(atomic replace). The prompt sees a handful of lines, not the channel history.
"""
from __future__ import annotations

import json
import re

from ship import _atomic_write, _load_json

MAX_PINS = 12
MAX_PIN_CHARS = 200
# Idle recap and shutdown keep the tail of RAM history so the next boot is not
# a cold open. Short on purpose: voice, not a transcript.
SCENE_SEED_LINES = 32

# Bookkeeping the model must not learn as scene fact. OOC and commands are
# already dropped before history; this catches residue that still gets stored
# ("plot cleared") or replayed from an old seed.
_NOISY = re.compile(
    r"(?:"
    r"\bplot\s+cleared\b"
    r"|\bpins?\s+(?:cleared|added|removed|updated)\b"
    r"|\bchronicle\s+(?:cleared|wiped|reset)\b"
    r"|\bship'?s\s+log\s+(?:cleared|wiped|reset|updated)\b"
    r"|\blog\s+(?:cleared|wiped)\b"
    r")",
    re.I,
)
_OOC_PREFIXES = ("//", "((", "(", "[", "{", "ooc:", "ooc ", "ooc-")


def is_noisy_residue(text: str) -> bool:
    """True for OOC, commands, and meta about the bot's own bookkeeping."""
    raw = (text or "").strip()
    if not raw:
        return True
    body = raw
    # History lines are "Rank Name: speech". Only split a short speaker prefix.
    if ":" in raw[:48]:
        head, tail = raw.split(":", 1)
        if tail.strip() and len(head.split()) <= 6:
            body = tail.strip()
    for chunk in (raw, body):
        low = chunk.strip().lower()
        if low.startswith(_OOC_PREFIXES) or low.startswith("!") or low.startswith("/"):
            return True
    return bool(_NOISY.search(raw))


def history_for_recap(lines) -> str:
    """Scene text for an LLM recap or pin extract, without OOC/command/meta lines."""
    kept = []
    for line in lines or []:
        text = str(line).strip()
        if not text or is_noisy_residue(text):
            continue
        kept.append(text)
    return "\n".join(kept)


def _clip_pin(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text[:MAX_PIN_CHARS].strip()


def parse_pin_lines(text: str) -> list[str]:
    """Turn a model's pin-extract reply into clean in-world lines."""
    raw = (text or "").strip()
    if not raw or raw.upper() == "NONE":
        return []
    out = []
    for line in raw.splitlines():
        line = re.sub(r"^\s*(?:[-*]|[\d]+[.)])\s*", "", line).strip().strip("\"'")
        if not line or line.upper() == "NONE" or is_noisy_residue(line):
            continue
        line = _clip_pin(line)
        if line and line.lower() not in {p.lower() for p in out}:
            out.append(line)
    return out


class Pinboard:
    """Capped episodic facts for one channel."""

    def __init__(self, items: list | None = None):
        self.items = []
        for raw in items or []:
            text = _clip_pin(str(raw))
            if text and not is_noisy_residue(text):
                self.items.append(text)
        self.items = self.items[:MAX_PINS]

    def add(self, text: str) -> tuple[bool, str]:
        if is_noisy_residue(text):
            return False, "That is OOC, a command, or bookkeeping, not a scene fact."
        text = _clip_pin(text)
        if not text:
            return False, "Empty pin."
        if any(p.lower() == text.lower() for p in self.items):
            return False, "Already pinned."
        if len(self.items) >= MAX_PINS:
            return False, f"This channel already has {MAX_PINS} pins. Remove one first."
        self.items.append(text)
        return True, text

    def remove(self, which: str) -> tuple[bool, str]:
        which = (which or "").strip()
        if not which:
            return False, "Say which pin to remove (a number or a few words)."
        if which.isdigit():
            i = int(which)
            if 1 <= i <= len(self.items):
                return True, self.items.pop(i - 1)
            return False, "No pin with that number."
        low = which.lower()
        for i, item in enumerate(self.items):
            if low in item.lower():
                return True, self.items.pop(i)
        return False, "No matching pin."

    def clear(self) -> None:
        self.items.clear()

    def render(self) -> str:
        """Prompt block (after the chronicle). Empty is explicit."""
        if not self.items:
            return "(none pinned)"
        return "\n".join(f"- {p}" for p in self.items)

    def display(self) -> str:
        if not self.items:
            return "No pins on this channel."
        body = "\n".join(f"{i}. {p}" for i, p in enumerate(self.items, 1))
        if len(body) > 1800:
            body = body[:1800].rstrip() + "\n…"
        return body


def load_pinboards(path: str) -> dict:
    """{channel_id: Pinboard}."""
    raw = _load_json(path)
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in raw.items():
        if not str(k).lstrip("-").isdigit():
            continue
        rows = v if isinstance(v, list) else []
        board = Pinboard(rows)
        if board.items:
            out[int(k)] = board
    return out


def save_pinboards(boards: dict, path: str) -> None:
    raw = {}
    for cid, board in boards.items():
        items = list(getattr(board, "items", []) or [])
        if items:
            raw[str(cid)] = items
    _atomic_write(path, json.dumps(raw, indent=2))


def scene_blob(history, limit: int = SCENE_SEED_LINES) -> str:
    """Last in-world lines of RAM history, for the next process to restore."""
    lines = []
    for line in list(history or []):
        text = str(line).strip()
        if text and not is_noisy_residue(text):
            lines.append(text)
    return "\n".join(lines[-limit:])


def scene_lines(blob: str, limit: int = SCENE_SEED_LINES) -> list[str]:
    lines = [ln for ln in (blob or "").splitlines() if ln.strip() and not is_noisy_residue(ln)]
    return lines[-limit:]
