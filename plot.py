"""Live CIC plot: contacts and last facts the crew must not forget.

Separate from chat history. A fight fills 60 lines in minutes; the plot is the
picture that still wins after the scroll. Player narration and officer notes
write it. Banter and junior-enlisted model notes do not invent tracks.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from ship import _atomic_write, _load_json

MAX_CONTACTS = 8
MAX_FACTS = 3

_KIND_PATTERNS = (
    (re.compile(r"\b(?:aircraft|airborne|fighters?|helos?|helicopters?|bogeys?|bogies|bandits?)\b", re.I), "air"),
    (re.compile(r"\b(?:surface|skunks?|vessels?|ships?(?:\s+contact)?)\b", re.I), "surface"),
    (re.compile(r"\b(?:sub(?:marine)?s?|periscope|torpedoes?)\b", re.I), "sub"),
)
_IFF_PATTERNS = (
    (re.compile(r"\b(?:friendly|friendlies|friend|iff\s+sweet|iff\s+good)\b", re.I), "friendly"),
    (re.compile(r"\b(?:hostile|hostiles|enemy|bandits?|iff\s+sour)\b", re.I), "hostile"),
    (re.compile(r"\b(?:unknown|unidentified|unid|bogeys?|bogies)\b", re.I), "unknown"),
)
_BEARING = re.compile(r"\b(?:bearing|brg)\s+(\d{1,3})\b", re.I)
_RANGE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(nm|nmi|yards|yds|kyd|miles|mi)\b", re.I)
_COUNT = re.compile(
    r"\b(a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)\b",
    re.I,
)
_WORD_NUM = {
    "a": "1", "an": "1", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12",
}
_CLEAR_ALL = re.compile(
    r"\b(?:no contacts|plot is clear|clear the plot|picture is clean|"
    r"nothing out there|all contacts gone)\b",
    re.I,
)
_CLEAR_AIR = re.compile(
    r"\b(?:spy is clean|nothing on spy|air picture(?: is)? clear|no air contacts)\b",
    re.I,
)
_CONTACT_HINT = re.compile(
    r"\b(?:contact|contacts|aircraft|bogey|bogies|bandit|skunk|surface|sub(?:marine)?|"
    r"bearing|brg|iff|friendlies|hostile|hostiles)\b",
    re.I,
)
_QUESTION = re.compile(r"\?\s*$")
_PREFIX = {"air": "A", "surface": "S", "sub": "B", "unknown": "U"}


@dataclass
class Contact:
    id: str
    kind: str = "unknown"
    iff: str = "unknown"
    bearing: str = ""
    range: str = ""
    note: str = ""
    source: str = "player"

    def line(self) -> str:
        bits = [self.id, self.kind, self.iff]
        if self.bearing:
            bits.append(f"brg {self.bearing}")
        if self.range:
            bits.append(self.range)
        if self.note:
            bits.append(f'"{self.note}"')
        bits.append(f"({self.source})")
        return "  " + "  ".join(bits)


@dataclass
class Plot:
    contacts: list = field(default_factory=list)
    facts: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "contacts": [asdict(c) for c in self.contacts],
            "facts": list(self.facts),
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "Plot":
        if not isinstance(data, dict):
            return cls()
        contacts = []
        for raw in data.get("contacts") or []:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            contacts.append(Contact(
                id=str(raw["id"]),
                kind=str(raw.get("kind") or "unknown"),
                iff=str(raw.get("iff") or "unknown"),
                bearing=str(raw.get("bearing") or ""),
                range=str(raw.get("range") or ""),
                note=str(raw.get("note") or ""),
                source=str(raw.get("source") or "player"),
            ))
        facts = [str(f) for f in (data.get("facts") or []) if str(f).strip()]
        return cls(contacts=contacts[:MAX_CONTACTS], facts=facts[:MAX_FACTS])

    def render(self, alert: str = "") -> str:
        lines = ["PLOT (current -- treat as fact; do not invent a different picture):"]
        if alert:
            lines.append(f"Alert: {alert}")
        if self.contacts:
            lines.append("Contacts:")
            lines.extend(c.line() for c in self.contacts)
        else:
            lines.append("Contacts: none held.")
        if self.facts:
            lines.append("Last:")
            lines.extend(f"  - {f}" for f in self.facts)
        return "\n".join(lines)

    def display(self, alert: str = "") -> str:
        """Human /status text (no prompt instructions)."""
        lines = []
        if alert:
            lines.append(f"Alert: {alert}")
        if self.contacts:
            lines.append("Contacts:")
            lines.extend(c.line() for c in self.contacts)
        else:
            lines.append("Contacts: none")
        if self.facts:
            lines.append("Last:")
            lines.extend(f"  - {f}" for f in self.facts)
        return "\n".join(lines) if lines else "(empty plot)"

    def clear(self, kind: str | None = None) -> bool:
        before = len(self.contacts)
        if kind:
            self.contacts = [c for c in self.contacts if c.kind != kind]
        else:
            self.contacts = []
        return len(self.contacts) != before or kind is None

    def add_fact(self, text: str) -> None:
        text = _clip(text, 80)
        if not text:
            return
        self.facts = [f for f in self.facts if f.lower() != text.lower()]
        self.facts.append(text)
        self.facts = self.facts[-MAX_FACTS:]

    def ingest(self, text: str, source: str = "player") -> bool:
        """Update from a line of player narration or an officer note. True if changed."""
        text = (text or "").strip()
        if not text:
            return False
        changed = False
        if _CLEAR_ALL.search(text):
            if self.contacts:
                self.contacts = []
                changed = True
            self.add_fact("plot cleared")
            return True
        if _CLEAR_AIR.search(text):
            if self.clear("air"):
                changed = True
            self.add_fact("air picture clear")
            return True
        parsed = parse_contact(text)
        if parsed:
            self._upsert(parsed, source)
            self.add_fact(parsed.note or parsed.line().strip())
            return True
        return changed

    def _upsert(self, incoming: Contact, source: str) -> None:
        incoming.source = source
        for i, c in enumerate(self.contacts):
            if c.kind == incoming.kind and incoming.bearing and c.bearing == incoming.bearing:
                incoming.id = c.id
                if not incoming.range:
                    incoming.range = c.range
                self.contacts[i] = incoming
                return
            if c.kind == incoming.kind and not c.bearing and not incoming.bearing:
                incoming.id = c.id
                self.contacts[i] = incoming
                return
        incoming.id = self._next_id(incoming.kind)
        self.contacts.append(incoming)
        self.contacts = self.contacts[-MAX_CONTACTS:]

    def _next_id(self, kind: str) -> str:
        prefix = _PREFIX.get(kind, "U")
        used = {c.id for c in self.contacts}
        n = 1
        while f"{prefix}{n}" in used:
            n += 1
        return f"{prefix}{n}"


def parse_contact(text: str) -> Contact | None:
    """Pull one contact out of a report. Questions and location-only lines return None."""
    raw = (text or "").strip()
    if not raw or _QUESTION.search(raw):
        return None
    if not _CONTACT_HINT.search(raw):
        return None
    kind = "unknown"
    for pat, name in _KIND_PATTERNS:
        if pat.search(raw):
            kind = name
            break
    iff = "unknown"
    for pat, name in _IFF_PATTERNS:
        if pat.search(raw):
            iff = name
            break
    if kind == "air" and iff == "unknown" and re.search(r"\bbandits?\b", raw, re.I):
        iff = "hostile"
    if kind == "air" and iff == "unknown" and re.search(r"\bbogeys?\b", raw, re.I):
        iff = "unknown"
    bm = _BEARING.search(raw)
    bearing = f"{int(bm.group(1)):03d}" if bm else ""
    rm = _RANGE.search(raw)
    rng = f"{rm.group(1)}{rm.group(2).lower()}" if rm else ""
    if kind == "unknown" and iff == "unknown" and not bearing:
        return None
    count = ""
    # Prefer a count sitting next to a kind/iff word.
    cm = re.search(
        r"\b(a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)\s+"
        r"(?:friendly|hostile|unknown|aircraft|fighters?|helos?|contacts?|skunks?|subs?)\b",
        raw, re.I,
    )
    if cm:
        token = cm.group(1).lower()
        count = _WORD_NUM.get(token, token)
    note = _clip(re.sub(r"\s+", " ", raw), 72)
    if count and count not in note.split()[:3]:
        note = f"{count} {note}"
    return Contact(
        id="?",
        kind=kind,
        iff=iff,
        bearing=bearing,
        range=rng,
        note=note,
        source="player",
    )


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    text = re.sub(r"^\*+|\*+$", "", text).strip()
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


def load_plots(path: str) -> dict:
    """{channel_id: Plot}."""
    raw = _load_json(path)
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in raw.items():
        if not str(k).lstrip("-").isdigit():
            continue
        out[int(k)] = Plot.from_dict(v if isinstance(v, dict) else {})
    return out


def save_plots(plots: dict, path: str) -> None:
    raw = {str(cid): p.to_dict() for cid, p in plots.items() if p.contacts or p.facts}
    _atomic_write(path, json.dumps(raw, indent=2))
