"""The NPC crew, loaded from the character reference sheet (characters.yaml).

Keeping every crew member's identity -- name, rank, rate, billet, personality --
in one data file gives consistent, in-character behaviour and lets you add or
edit crew without touching code. Each NPC's model persona is *generated* from
these fields, so the sheet is the single source of truth.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import config


@dataclass
class NPC:
    key: str                      # stable id (referenced in code; rename with care)
    name: str                     # character's name, e.g. "Elias Cole"
    rank: str = ""                # e.g. "Petty Officer 2nd Class"
    rate: str = ""                # rating / specialty, e.g. "Quartermaster"
    billet: str = ""              # shipboard station, e.g. "Helmsman"
    display: str = ""             # optional chat-name override, e.g. "Lieutenant Hoover"
    aliases: list = field(default_factory=list)
    personality: str = ""
    kit: str = ""                 # specialist script; injected only on matching orders
    avatar_url: str = None
    station: str = ""             # default duty location, e.g. "the engine room"
    location: str = ""            # current location (starts at station, moves in play)

    def __post_init__(self):
        if not self.location:
            self.location = self.station

    @property
    def display_name(self) -> str:
        """Name shown in chat, e.g. 'Helmsman Cole' -- or a per-NPC `display` override."""
        if self.display:
            return self.display
        if self.billet and self.name:
            return f"{self.billet} {self.name.split()[-1]}"
        return self.name or self.key

    @property
    def persona(self) -> str:
        """The character description handed to the model, built from the sheet."""
        s = "You are"
        if self.rank:
            s += f" {self.rank}"
        s += f" {self.name}"
        tail = []
        if self.rate:
            tail.append(f"a {self.rate}")
        if self.billet:
            tail.append(f"serving as the ship's {self.billet}")
        if tail:
            s += ", " + " ".join(tail)
        s += "."
        if self.personality:
            s += " " + self.personality.strip()
        return s


def load_crew(path: str):
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"Character sheet not found: {path}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    crew = []
    for entry in data.get("crew", []):
        crew.append(
            NPC(
                key=entry["key"],
                name=entry["name"],
                rank=entry.get("rank", ""),
                rate=entry.get("rate", ""),
                billet=entry.get("billet", ""),
                display=entry.get("display", "") or "",
                station=entry.get("station", ""),
                aliases=[a.lower() for a in entry.get("aliases", [])],
                personality=entry.get("personality", ""),
                kit=(entry.get("kit") or "").strip(),
                avatar_url=entry.get("avatar_url") or None,
            )
        )
    if not crew:
        raise SystemExit(f"No crew found in {path}.")
    return crew


CREW = load_crew(config.CHARACTERS_FILE)


def load_ship(path: str) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    s = data.get("ship") or {}
    name = s.get("name") or "the ship"
    hull = s.get("hull") or ""
    return {
        "name": name,
        "hull": hull,
        "class": s.get("class") or "warship",
        "knowledge": s.get("knowledge") or "",
        "swo": s.get("swo") or "",
        "display": f"{name} ({hull})" if hull else name,
    }


SHIP = load_ship(config.CHARACTERS_FILE)


@dataclass
class Player:
    """A real human the crew take orders from."""
    name: str = ""
    rank: str = ""
    role: str = ""
    discord_id: int = None
    username: str = ""
    match: list = field(default_factory=list)  # extra Discord usernames/nicknames to match on

    @property
    def address(self) -> str:
        """How the crew refer to them, e.g. 'Lieutenant Commander Hale'."""
        parts = [p for p in (self.rank, self.name) if p]
        return " ".join(parts) if parts else "the officer on deck"


def load_players(path: str):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    players = []
    for entry in data.get("players") or []:
        players.append(
            Player(
                name=entry.get("name") or "",
                rank=entry.get("rank") or "",
                role=entry.get("role") or "",
                discord_id=entry.get("discord_id"),
                username=(entry.get("username") or "").lower().lstrip("@"),
                match=[str(m).lower().lstrip("@") for m in (entry.get("match") or [])],
            )
        )
    return players


PLAYERS = load_players(config.CHARACTERS_FILE)


def resolve_player(author_id, username="", display_name="", roles=None):
    """Match a Discord author to a known player entry, or None.

    A sheet `match:` list is checked against the username, the display name (whole
    OR any word within it), and the member's Discord role names. That way a player
    whose nickname or server role reads e.g. "Commodore" still maps to the right
    entry -- and is addressed by that entry's rank ("Captain Santos") -- instead of
    falling through to the raw Discord role and being called "Commodore".
    """
    uname = (username or "").lower().lstrip("@")
    dname = (display_name or "").lower()
    dtokens = {t for t in re.split(r"[\s,]+", dname) if t}
    rnames = {(r or "").lower() for r in (roles or [])}
    for p in PLAYERS:
        if p.discord_id and author_id == p.discord_id:
            return p
        if p.username and p.username == uname:
            return p
        if p.name and p.name.lower() == dname:
            return p
        if p.match:
            m = set(p.match)
            if uname in m or dname in m or (m & dtokens) or (m & rnames):
                return p
    return None


def load_ranks(path: str):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [str(r) for r in (data.get("ranks") or [])]


RANKS = load_ranks(config.CHARACTERS_FILE)
_RANKS_LOWER = [r.lower() for r in RANKS]


def rank_from_roles(role_names):
    """Most senior recognised rank among a member's Discord role names, or ''."""
    best_idx, best = -1, ""
    for name in role_names:
        low = (name or "").lower()
        if low in _RANKS_LOWER:
            idx = _RANKS_LOWER.index(low)
            if idx > best_idx:
                best_idx, best = idx, name
    return best


def rank_index(rank_name: str) -> int:
    """Index of a rank in the junior->senior RANKS list, or -1 if unknown.
    Handles full titles ("Lieutenant Commander") and partial matches."""
    low = (rank_name or "").strip().lower()
    if not low:
        return -1
    if low in _RANKS_LOWER:
        return _RANKS_LOWER.index(low)
    best = -1
    for i, r in enumerate(_RANKS_LOWER):
        if r and r in low and i > best:
            best = i
    return best


# Index at/above which a speaker counts as an OFFICER (Warrant Officer and up).
_OFFICER_MIN_IDX = next((i for i, r in enumerate(_RANKS_LOWER) if r == "warrant officer"), 5)
_CHIEF_IDX = next((i for i, r in enumerate(_RANKS_LOWER) if r == "chief petty officer"), 4)


def authority_note(rank_name: str) -> str:
    """A sentence telling the crew what this speaker is authorised to order,
    based on their rank. Used to enforce the chain of command."""
    idx = rank_index(rank_name)
    who = rank_name or "an unidentified person"
    if idx >= _OFFICER_MIN_IDX:
        return (
            f"The speaker is {who} -- a commissioned or warrant OFFICER with command authority. "
            "They may direct the ship: set or secure General Quarters and other alert states, order "
            "course, speed, and helm/engine changes, and employ weapons. Carry out their lawful orders."
        )
    if idx == _CHIEF_IDX:
        return (
            f"The speaker is {who} -- a Chief Petty Officer (senior enlisted). They run the deckplate and "
            "may direct routine work, watches, and their rating's domain, and you heed them with respect. "
            "But a Chief does NOT have authority to set or secure General Quarters, or to order major "
            "ship-control changes (course, speed, helm, engines) or weapons employment on their own -- those "
            "require an officer or the OOD. Politely refer such orders up the chain."
        )
    if idx >= 0:
        return (
            f"The speaker is {who} -- a junior enlisted sailor. They may ask questions and carry out or relay "
            "routine tasks, but they have NO authority to order major evolutions (setting or securing General "
            "Quarters), ship-control changes (course, speed, helm, engines), or weapons employment. Respectfully "
            "decline such orders and refer them to the OOD, the XO, or the Captain."
        )
    return (
        "The speaker's rank is not established. Be courteous and answer questions, but do NOT set or secure "
        "General Quarters or make major ship-control or weapons changes on their say-so until a known officer "
        "confirms the order."
    )


def can_order_ship(rank_name: str) -> bool:
    """True if this rank may change course, speed, or alert (warrant/officer+)."""
    return rank_index(rank_name) >= _OFFICER_MIN_IDX


# --- Spatial awareness: fold free-form locations into canonical "earshot" spaces ---
# Two people can hear each other only if they share a space. Bridge wings collapse
# into "bridge" (they open onto it); an unrecognized location becomes its own
# isolated space, so e.g. a crewman "below decks, unaccounted for" hears no one.
_SPACE_KEYWORDS = (
    ("damage control", ("damage control", "dc central", "dccentral", "repair locker")),
    ("cic",            ("combat information", "cic", "combat")),
    ("engineering",    ("engine room", "engineering", "main control", "propulsion", "fireroom", "shaft alley")),
    ("bridge",         ("bridge", "pilothouse", "helm", "wheel", "chart table", "conn", "wing")),
    ("main deck",      ("main deck", "weather deck", "topside", "forecastle", "fo'c'sle", "fantail", "quarterdeck")),
    ("ship's office",  ("ship's office", "ships office", "the office", "admin")),
    ("wardroom",       ("wardroom",)),
    ("cpo mess",       ("goat locker", "cpo mess", "chief's mess", "chiefs mess")),
    ("mess",           ("mess", "galley", "scullery")),
    ("weapons",        ("magazine", "vls", "gun mount", "weapons")),
    ("sickbay",        ("sickbay", "medical", "battle dressing")),
)


def space_of(location: str) -> str:
    """Canonical 'earshot' space for a free-form location string. Same return value
    == within earshot. Unknown locations fall back to themselves (isolated)."""
    low = (location or "").lower()
    for space, keys in _SPACE_KEYWORDS:
        if any(k in low for k in keys):
            return space
    return low.strip() or "unknown"


# Station names a caller can hail over comms (radio / sound-powered phone / 1MC),
# each mapped to the canonical space that answers. Calling a station reaches whoever
# mans it anywhere on the ship -- that is the whole point of comms. Longer phrases
# first so "combat information center" wins over "combat".
_STATION_HAILS = (
    ("combat information center", "cic"), ("cic", "cic"), ("combat", "cic"),
    ("bridge", "bridge"), ("pilothouse", "bridge"),
    ("main engine control", "engineering"), ("main control", "engineering"),
    ("engineering", "engineering"), ("engine room", "engineering"),
    ("damage control central", "damage control"), ("damage control", "damage control"),
    ("dc central", "damage control"), ("dcc", "damage control"),
    ("sickbay", "sickbay"), ("medical", "sickbay"),
    ("ship's office", "ship's office"), ("the office", "ship's office"),
    ("main deck", "main deck"),
)


def find_hailed_spaces(text: str):
    """Canonical spaces hailed as stations over comms, ordered by first appearance.
    A station name counts only when used vocatively (at the start, next to a comma, or
    before !/:/.) -- i.e. calling that station on a radio or sound-powered phone.
    'Bridge, CIC' -> ['bridge', 'cic']."""
    low = text.lower().strip()
    hits = {}
    for phrase, space in _STATION_HAILS:
        for m in re.finditer(rf"\b{re.escape(phrase)}\b", low):
            i = m.start()
            before = low[max(0, i - 2):i]
            after = low[m.end():m.end() + 1]
            vocative = i <= 2 or "," in before or after in (",", "!", ":", ".")
            if vocative and space not in hits:
                hits[space] = i
    return [s for s, _ in sorted(hits.items(), key=lambda kv: kv[1])]


# Collective vocatives -- addressing the whole group present, so all co-located crew
# answer ("how we feeling, team?", "all hands, listen up", "alright everyone").
_GROUP_TERMS = (
    "team", "everyone", "everybody", "all hands", "all of you", "you all", "y'all",
    "guys", "gents", "gentlemen", "crew", "people", "folks", "gang",
)
# When a group word follows one of these it's a noun, not a call ("the team", "our crew").
_NON_VOCATIVE_PRE = {
    "the", "a", "an", "our", "my", "your", "his", "her", "their", "this", "that",
    "whole", "entire", "of", "to", "with", "for", "no", "each", "one", "same",
}


def is_group_address(text: str) -> bool:
    """True if the message hails the group present -- a collective vocative like
    'team', 'everyone', 'all hands' -- so every co-located crew member should answer."""
    low = text.lower()
    for term in _GROUP_TERMS:
        for m in re.finditer(rf"\b{re.escape(term)}\b", low):
            i, j = m.start(), m.end()
            before = low[max(0, i - 2):i]
            after = low[j:j + 1]
            pre_word = low[:i].rstrip().split()[-1] if low[:i].strip() else ""
            if pre_word in _NON_VOCATIVE_PRE:
                continue  # "the team", "our crew" -> a noun, not an address
            if i <= 2 or "," in before or after in (",", "?", "!", ":"):
                return True
    return False


_MOVE_VERB = (
    r"(?:heads?|heading|walk(?:s|ing)?|mov(?:e|es|ing)|go(?:es|ing)?|step(?:s|ping)?|"
    r"proceed(?:s|ing)?|makes?\s+\w*\s*way|made\s+way|enter(?:s|ing)?|arriv(?:e|es|ing)|"
    r"return(?:s|ing)?|report(?:s|ing)?\s+to|lays?\s+up|climb(?:s|ing)?|descend(?:s|ing)?|"
    r"down\s+to|up\s+to|over\s+to|back\s+to)"
)


def _space_or_none(text):
    low = (text or "").lower()
    for space, keys in _SPACE_KEYWORDS:
        if any(k in low for k in keys):
            return space
    return None


def player_location_from_text(text: str):
    """The space the PLAYER themselves narrates being in / heading to (inside their own
    *actions* or a first-person clause), or None. Deliberately ignores orders aimed at
    the crew ("McTane, head to the bridge") so it never mis-moves the player."""
    low = text.lower()
    cands = []
    for seg in re.findall(r"\*([^*]*)\*", low):          # *action* narration
        seg = seg.strip()
        if re.search(_MOVE_VERB, seg) or re.match(r"(?:in|on|at|aboard|inside)\b", seg):
            cands.append(seg)
    for m in re.finditer(r"\bi(?:'m| am)?\s+(?:in|on|at|aboard|inside|" + _MOVE_VERB + r")\b[^.]{0,30}", low):
        cands.append(m.group(0))                          # first-person position/movement
    for seg in cands:
        sp = _space_or_none(seg)
        if sp:
            return sp
    return None


# Orders that send a crew member somewhere (not helm/course changes).
_MOVE_ORDER_CUES = (
    "report to", "report in", "lay up to", "lay to the", "lay to",
    "get up here", "get in here", "get down here", "get over here",
    "come here", "come up here", "come down here",
    "on the double", "front and center",
    "get to the", "up to the bridge",
    "find the", "go check", "go see",
)


def is_movement_order(text: str) -> bool:
    """True if the speaker is sending someone somewhere (not 'come about to 090')."""
    low = (text or "").lower()
    if any(c in low for c in _MOVE_ORDER_CUES):
        return True
    # "Hartley, to CIC" / "to the bridge" -- a destination with no explicit verb.
    if re.search(r"\bto\s+(?:the\s+)?", low) and (
        _space_or_none(low) or re.search(r"\b(?:captain|skipper|xo|cabin)\b", low)
    ):
        return True
    if not re.search(_MOVE_VERB, low):
        return False
    return _space_or_none(low) is not None or bool(
        re.search(r"\b(?:captain|skipper|xo|cabin)\b", low)
    )


# Watchstanders who brief contacts / conn the ship get the SWO encyclopedia.
_SWO_KEYS = {"navigator", "mctane", "lookout", "hoover"}


def swo_for(npc) -> str:
    """SWO threat/weapons brick, or '' if this billet does not need it every call."""
    if getattr(npc, "key", None) in _SWO_KEYS:
        return SHIP.get("swo") or ""
    return ""


# Ship's communication circuits. Intra-ship talk rides these; a hail reaches another
# space ONLY over one of them (otherwise you're limited to earshot). The 1MC reaches
# the WHOLE ship; other circuits reach the station/person you raise.
# Generic 1MC uses a word boundary so "21MC"/"31MC" (specific circuits) aren't mistaken
# for the 1 Main Circuit.
_1MC_RE = re.compile(
    r"\b1\s*-?\s*mc\b|\bone main circuit\b|\bnow hear this\b|\bpass(?:es)? the word\b|\bgeneral announcing\b"
)
_CIRCUIT_CUES = (
    "2mc", "3mc", "4mc", "5mc", "6mc", "19mc", "21mc", "22mc", "24mc", "29mc",
    "squawk box", "bitch box", "intercom", "over the radio", "on the radio", " radios ",
    "radioed", "keys the mic", "keys up", "over the net", "on the net", "over the circuit",
    "on the circuit", "over comms", "on comms", "sound-powered", "sound powered", "growler",
    "1jv", "ja circuit", "jl circuit", "jw circuit", "jx circuit", "jz circuit", "jc circuit",
    "over the horn", "pipes over", "hails over",
)


def comms_channel(text: str):
    """Which ship's circuit a message rides, if any:
      "1mc"     -> the 1 Main Circuit (shipwide announcing -- reaches everyone),
      "circuit" -> a radio net, 21MC intercom, another MC, or a sound-powered phone
                   (emergency) -- reaches the station/person raised, anywhere aboard,
      None      -> spoken in person (earshot only).
    A hail carries across the ship ONLY when a circuit is used. A specific circuit
    (21MC, radio, ...) is matched before the generic 1MC."""
    low = text.lower()
    if any(c in low for c in _CIRCUIT_CUES):
        return "circuit"
    if _1MC_RE.search(low):
        return "1mc"
    return None


# Orders that should attach an NPC's `kit` (Hartley's 1MC phrase book). Kept
# specific so "Bosun, how's the deck?" does not load the whole POD.
_ANNOUNCE_CUES = (
    "now hear this", "pass the word", "pass a word", "passing the word",
    "general announcing", "over the 1mc", "on the 1mc", "pipe the",
    "sound general quarters", "general quarters", "battle stations",
    "man overboard",
    "getting underway", "get underway", "special sea and anchor",
    "special sea detail", "single up", "let go all lines", "shift colors",
    "coming into port", "come into port", "make all preparations",
    "unrep", "refuel", "refueling",
    "sea rescue", "helo detail",
    "reveille", "sweepers", "mess call",
    "quarters for muster", "all hands to quarters",
    "attention to colors", "make colors",
    "turn to", "knock off ship's work", "liberty call",
    "taps", "lights out", "alarm test", "whistle test",
    "arriving", "departing",
)


def is_announcement_order(text: str) -> bool:
    """True if the line is a pass-the-word / 1MC / evolution call, not ordinary chatter."""
    if comms_channel(text) == "1mc":
        return True
    low = (text or "").lower()
    return any(c in low for c in _ANNOUNCE_CUES)


def kit_for(npc, text: str) -> str:
    """NPC specialist script if this order is the job the kit is for, else ''."""
    if not getattr(npc, "kit", ""):
        return ""
    return npc.kit if is_announcement_order(text) else ""


def _gq_reason(order: str, plot=None) -> str:
    low = (order or "").lower()
    if re.search(r"\b(?:drones?|aircraft|air|bogeys?|bogies|bandits?|missiles?|raid)\b", low):
        return "air"
    if re.search(r"\b(?:sub|submarine|torpedo|asw)\b", low):
        return "submarine"
    if re.search(r"\b(?:surface|ship|skunk|small boat)\b", low):
        return "surface"
    kinds = {getattr(c, "kind", "") for c in (getattr(plot, "contacts", None) or [])}
    if kinds == {"air"}:
        return "air"
    if kinds == {"sub"}:
        return "submarine"
    if kinds == {"surface"}:
        return "surface"
    if kinds:
        return "multiple threats"
    return "unknown contacts"


def general_quarters_1mc(order: str = "", plot=None) -> str:
    """Full GQ pass-the-word: reason, route of travel, Zebra, drill/not, alarm."""
    drill = "This is a drill." if "drill" in (order or "").lower() else "This is not a drill."
    reason = _gq_reason(order, plot)
    asw = " Set the ASW detail." if reason == "submarine" else ""
    return (
        "*pipes, then over the 1MC* General quarters, general quarters! "
        "All hands man your battle stations! "
        f"Reason for general quarters: {reason}. "
        "The route of travel is forward and up to starboard, down and aft to port. "
        f"Set material condition Zebra throughout the ship.{asw} {drill} "
        "*general quarters alarm, twelve gongs*"
    )


def announcement_followup(order: str, plot=None) -> str:
    """Verbatim 1MC beat when the model acknowledges GQ but leaves followup empty."""
    low = (order or "").lower()
    if re.search(r"general quarters|battle stations|\bgq\b", low):
        return general_quarters_1mc(order, plot)
    return ""


def can_reach(caller_location: str, callee_location: str, text: str) -> bool:
    """True if callee can hear caller: same earshot space, or the line rides a circuit."""
    if comms_channel(text) is not None or find_hailed_spaces(text):
        return True
    return space_of(caller_location) == space_of(callee_location)


def _classify_addressed(text: str):
    """[(npc, called), ...] ordered by first appearance.

    `called` == True when the crew member is actively HAILED -- their name/alias at
    the start, next to a comma, or before '!'/':' (e.g. "Helmsman, come about" /
    "Bosun!"), or any alias/station inside a roleplay *action* ("*dials the bosun*").
    `called` == False is a passing MENTION -- a personal name used mid-sentence
    ("is McTane any good?"); those crew only chime in if they're in the same space.
    A role word used purely as narration ("the navigator looked nervous") is ignored.
    """
    low = text.lower().strip()
    is_action = "*" in text
    hits = {}  # npc.key -> [pos, npc, called]
    for npc in CREW:
        name_tokens = set(npc.name.lower().split())
        for alias in npc.aliases:
            is_name = alias in name_tokens  # a personal name is a strong signal
            for m in re.finditer(rf"\b{re.escape(alias)}\b", low):
                i = m.start()
                before = low[max(0, i - 2):i]
                after = low[m.end():m.end() + 1]
                vocative = i <= 2 or "," in before or after in (",", "!", ":")
                called = vocative or is_action
                if not (called or is_name):
                    continue  # a role word used as narration -> ignore
                if npc.key not in hits:
                    hits[npc.key] = [i, npc, called]
                else:
                    hits[npc.key][0] = min(hits[npc.key][0], i)
                    hits[npc.key][2] = hits[npc.key][2] or called
    ordered = sorted(hits.values(), key=lambda h: h[0])
    return [(npc, called) for _, npc, called in ordered]


def find_all_addressed(text: str):
    """Every crew member addressed OR mentioned, ordered by first appearance."""
    return [npc for npc, _ in _classify_addressed(text)]


def find_addressed_split(text: str):
    """(called, mentioned) -- crew actively hailed vs merely named, each ordered."""
    called = [npc for npc, c in _classify_addressed(text) if c]
    mentioned = [npc for npc, c in _classify_addressed(text) if not c]
    return called, mentioned


def find_called(text: str):
    """Only crew who are actively hailed/addressed (used for crew-to-crew summons)."""
    return [npc for npc, called in _classify_addressed(text) if called]


def find_addressed(text: str):
    """The single NPC addressed earliest in the message, or None."""
    addressed = find_all_addressed(text)
    return addressed[0] if addressed else None


def npc_by_display_name(name: str):
    """Find a crew member by the name they post under (their webhook username),
    e.g. 'Helmsman Cole' -> the helmsman. Used to route Discord replies."""
    low = (name or "").strip().lower()
    if not low:
        return None
    for npc in CREW:
        if npc.display_name.lower() == low:
            return npc
    return None
