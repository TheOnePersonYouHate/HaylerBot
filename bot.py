"""Naval RP NPC crew bot (multi-server).

Listens in every channel listed in RP_CHANNEL_ID (comma-separated, across any
servers the bot is in). Each channel keeps its own ship state, crew positions,
conversation, and webhook, so different servers never bleed into each other.
Crew reply in character via webhooks; humans are addressed by their Discord rank.
"""
import asyncio
import logging
import re
import shutil
import socket
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler

import discord
from discord.ext import commands

import brain
import config
from brain import npc_respond
from memory import (
    Pinboard, history_for_recap, is_noisy_residue, load_pinboards, save_pinboards,
    scene_blob, scene_lines,
)
from npcs import (
    CREW, SHIP, announcement_followup, authority_note, can_order_ship, can_reach,
    comms_channel, find_addressed_split, find_called, find_hailed_spaces,
    is_announcement_order, is_far_end_report, is_group_address, is_movement_order,
    looks_like_circuit_hold, npc_by_display_name, player_location_from_text,
    rank_from_roles, rank_index,
    resolve_player, space_of,
)
from plot import Plot, load_plots, save_plots
from ship import ShipState, load_maps, load_states, load_texts, save_maps, save_states, save_texts

log = logging.getLogger("naval_bot")

intents = discord.Intents.default()
intents.message_content = True  # privileged: enable in the Developer Portal

ENGAGE_WINDOW = config.CONTINUITY_SECONDS  # seconds before the crew disengage
# (wait longer than this without addressing anyone to talk out-of-context freely)
HISTORY_LIMIT = 80  # recent channel lines injected each call (plot holds the fight)
FOLLOWUP_DELAY = 15  # seconds before an NPC posts its follow-up beat (arriving, reporting, etc.)
LOCAL_CONTEXT = 24000  # context length the auto-loader requests from LM Studio
MAX_CREW_CHAIN = 3  # cap on crew-to-crew (NPC->NPC) replies per player turn -> can't loop

# Out-of-character / out-of-context messages the crew ignore entirely. Wrap an
# aside in (parentheses) or [brackets] / {braces}, or prefix it with // or OOC:,
# and the crew won't react to it or remember it. In-character *actions* still count.
_OOC_PREFIXES = ("//", "((", "(", "[", "{", "ooc:", "ooc ", "ooc-")


def is_ooc(text: str) -> bool:
    return text.strip().lower().startswith(_OOC_PREFIXES)


# Voice-procedure sign-off: "out" (NOT "over") ends the exchange -- no reply is
# expected. Any hang-up / end-of-call action counts too. "over and out" is a sign-off;
# a bare "over" is not (it invites a reply).
_SIGNOFF_ACTIONS = (
    "hangs up", "hung up", "hangs the phone", "hangs up the phone", "racks the handset",
    "sets down the handset", "sets down the receiver", "sets down the phone",
    "puts down the handset", "puts down the receiver", "puts the handset back",
    "ends the call", "ends the transmission", "signs off", "signing off", "terminates the call",
)


def is_signoff(text: str) -> bool:
    """True when a line closes the exchange -- 'out' as the final word, 'over and out',
    or a hang-up/end-of-call action -- so the crew give no further reply."""
    low = text.lower()
    if "over and out" in low or any(a in low for a in _SIGNOFF_ACTIONS):
        return True
    spoken = re.sub(r"\*[^*]*\*", " ", low).strip().rstrip(" .!?\"'")  # drop *actions* + trailing punct
    return bool(re.search(r"(?:^|[.,!?:])\s*out$", spoken))


def is_narration(text: str) -> bool:
    """True if the message is pure scene-setting narration -- entirely inside *...*
    action markers with no spoken dialogue outside them ('*cruising at 25 knots, course
    270*'). It advances the story rather than addressing anyone, so on its own it
    shouldn't pull a reply out of the active NPC (they just take note of it)."""
    outside = re.sub(r"\*[^*]*\*", " ", text).replace("*", " ")  # strip *actions* + stray markers
    return "*" in text and not re.search(r"[A-Za-z0-9]", outside)


# Releases a held pending action ("Enter" after a knock, "as you were", etc.).
_RELEASE = re.compile(
    r"(?:^|[.,!?:]\s*)(?:enter|come in|come on in|as you were|carry on|belay(?: that)?|"
    r"never mind|stand down|dismissed|that will be all)\b",
    re.I,
)


def is_release(text: str) -> bool:
    """True when the speaker ends a held wait (admit someone, belay, dismiss)."""
    if not text:
        return False
    spoken = re.sub(r"\*[^*]*\*", " ", text)
    return bool(_RELEASE.search(spoken.strip()))


_ship_states = load_states(config.STATE_FILE)  # {channel_id: ShipState}
_logs = load_texts(config.LOG_FILE)            # {channel_id: persistent ship's-log summary}
_pending = load_maps(config.PENDING_FILE)      # {channel_id: {npc.key: pending action}}
_locations = load_maps(config.LOCATIONS_FILE)  # {channel_id: {npc.key: current location}}
_player_locations = load_maps(config.PLAYER_LOCATIONS_FILE)  # {channel_id: {author_id: space}}
_plots = load_plots(config.PLOT_FILE)          # {channel_id: Plot}
_pins = load_pinboards(config.PINS_FILE)       # {channel_id: Pinboard}
_scenes = load_texts(config.SCENE_FILE)        # {channel_id: last-scene blob}


class CrewBot(commands.Bot):
    async def setup_hook(self):
        self.loop.create_task(_idle_recap_loop())

    async def close(self):
        try:
            await recap_all_dirty()
        except Exception:
            log.exception("shutdown recap failed")
        await super().close()


bot = CrewBot(command_prefix="!", intents=intents, help_command=None)


@dataclass
class ChannelState:
    """Everything that must stay separate per channel / server."""
    channel_id: int
    ship: ShipState
    history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_LIMIT))
    locations: dict = field(default_factory=dict)     # npc.key -> current location
    seen_players: dict = field(default_factory=dict)  # author_id -> (name, address)
    player_space: dict = field(default_factory=dict)  # author_id -> canonical space they're in
    webhook: object = None
    active: dict = field(default_factory=dict)  # author_id -> (npc, expires_at): each speaker's own thread
    pending: dict = field(default_factory=dict)  # npc.key -> unresolved action (knocking, waiting, en route)
    plot: Plot = field(default_factory=Plot)     # contacts + last facts (battle memory)
    pins: Pinboard = field(default_factory=Pinboard)  # capped episodic facts
    summary: str = ""        # persistent ship's log carried over from earlier sessions
    last_activity: float = 0.0
    log_dirty: bool = False
    last_memory_llm: float = 0.0  # monotonic; user /recap and /pin extract share a cooldown

    def location_of(self, npc) -> str:
        return self.locations.get(npc.key) or npc.station or "their usual station"

    def thread_npc(self, author_id: int, now: float):
        """Last NPC this speaker engaged, if the timer is live OR that NPC is mid-errand."""
        prev = self.active.get(author_id)
        if prev is None:
            return None
        npc, expires = prev
        if now < expires or self.pending.get(npc.key):
            return npc
        return None

    def npc_on_hold(self, author_id: int = None):
        """NPC waiting, en route, or on a circuit -- prefer this speaker's last thread."""
        if author_id is not None:
            prev = self.active.get(author_id)
            if prev and self.pending.get(prev[0].key):
                return prev[0]
        for n in CREW:
            held = (self.pending.get(n.key) or "").lower()
            if not held:
                continue
            if (
                held.startswith("en route")
                or "wait" in held
                or "knock" in held
                or "circuit" in held
                or "phone" in held
                or "sonar" in held
            ):
                return n
        return None


_channels = {}


def channel_state(channel_id: int) -> ChannelState:
    cs = _channels.get(channel_id)
    if cs is None:
        cs = ChannelState(channel_id=channel_id, ship=_ship_states.get(channel_id) or ShipState(name=SHIP["display"]))
        cs.summary = _logs.get(channel_id, "")
        cs.pending = dict(_pending.get(channel_id) or {})
        cs.locations = dict(_locations.get(channel_id) or {})
        cs.player_space = _player_space_from(_player_locations.get(channel_id) or {})
        cs.plot = _plots.get(channel_id) or Plot()
        board = _pins.get(channel_id)
        cs.pins = Pinboard(items=list(board.items) if board else [])
        for line in scene_lines(_scenes.get(channel_id, "")):
            cs.history.append(line)
        _channels[channel_id] = cs
    return cs


def _player_space_from(raw: dict) -> dict:
    """Disk map is {str(author_id): space}. Runtime lookups use the int id."""
    out = {}
    for key, space in (raw or {}).items():
        if str(key).lstrip("-").isdigit() and str(space).strip():
            out[int(key)] = str(space)
    return out


def save_plot(cs: ChannelState) -> None:
    _plots[cs.channel_id] = cs.plot
    save_plots(_plots, config.PLOT_FILE)


def _save_channel_map(store: dict, cs: ChannelState, data: dict, path: str) -> None:
    if data:
        store[cs.channel_id] = dict(data)
    else:
        store.pop(cs.channel_id, None)
    save_maps(store, path)


def set_pending(cs: ChannelState, npc_key: str, value: str) -> None:
    """Record or clear a per-NPC held action and persist it for this channel."""
    value = (value or "").strip()
    if value:
        cs.pending[npc_key] = value
    else:
        cs.pending.pop(npc_key, None)
    _save_channel_map(_pending, cs, cs.pending, config.PENDING_FILE)


def mark_activity(cs: ChannelState) -> None:
    """A turn happened -- reset the idle timer and mark the chronicle dirty."""
    cs.last_activity = time.monotonic()
    cs.log_dirty = True


def allows_location_change(cs: ChannelState, npc, proposed: str, player_text: str,
                           reply: dict = None) -> bool:
    """True if the model may move this NPC. Banter / Q&A cannot teleport them."""
    if not (proposed or "").strip():
        return False
    if space_of(proposed) == space_of(cs.location_of(npc)):
        return True
    pending = (cs.pending.get(npc.key) or "").lower()
    if pending.startswith("en route"):
        return True
    # Register 1b: acknowledge + follow-up arrival means they are moving, even if
    # the order was terse ("Hartley, to CIC") and we didn't parse a move verb.
    if reply and reply.get("followup"):
        return True
    return is_movement_order(player_text)


def set_player_space(cs: ChannelState, author_id: int, space: str) -> None:
    """Remember where this player is, with the same durability as NPC locations."""
    space = (space or "").strip()
    if not space or cs.player_space.get(author_id) == space:
        return
    cs.player_space[author_id] = space
    data = {str(k): v for k, v in cs.player_space.items() if str(v).strip()}
    _save_channel_map(_player_locations, cs, data, config.PLAYER_LOCATIONS_FILE)


def save_scene_seed(cs: ChannelState) -> None:
    """Persist the tail of this channel's RAM history for the next process."""
    blob = scene_blob(cs.history)
    if blob:
        _scenes[cs.channel_id] = blob
    else:
        _scenes.pop(cs.channel_id, None)
    save_texts(_scenes, config.SCENE_FILE)


def save_pins(cs: ChannelState) -> None:
    if cs.pins.items:
        _pins[cs.channel_id] = cs.pins
    else:
        _pins.pop(cs.channel_id, None)
    save_pinboards(_pins, config.PINS_FILE)


def clear_chronicle(cs: ChannelState) -> None:
    """Wipe the ship's log for this channel. Does not touch pins or the scene seed."""
    cs.summary = ""
    cs.log_dirty = False
    _logs.pop(cs.channel_id, None)
    save_texts(_logs, config.LOG_FILE)


def can_manage_memory(member) -> bool:
    """Plot/pin/chronicle clears and pin edits: Manage Messages, or an officer rank.

    Stricter than Send Messages. Checked at runtime so an officer whose Discord
    role is not Manage Messages can still use the command (default_permissions
    would hide it from them).
    """
    perms = getattr(member, "guild_permissions", None)
    if perms is not None and getattr(perms, "manage_messages", False):
        return True
    return can_order_ship(_speaker_rank(member))


def memory_llm_wait(cs: ChannelState) -> int:
    """Seconds until another user-triggered recap or pin-extract is allowed. 0 = ready."""
    elapsed = time.monotonic() - (cs.last_memory_llm or 0.0)
    remain = config.MEMORY_LLM_COOLDOWN - elapsed
    if remain <= 0:
        return 0
    return int(remain) + 1


def mark_memory_llm(cs: ChannelState) -> None:
    cs.last_memory_llm = time.monotonic()


def take_memory_llm_slot(cs: ChannelState) -> int:
    """Reserve the shared recap/pin-extract cooldown. Returns seconds still left, or 0."""
    wait = memory_llm_wait(cs)
    if wait:
        return wait
    mark_memory_llm(cs)
    return 0


def set_location(cs: ChannelState, npc_key: str, value: str) -> None:
    """Move an NPC and persist the new location so a restart doesn't snap them back."""
    value = (value or "").strip()
    if value:
        cs.locations[npc_key] = value
    else:
        cs.locations.pop(npc_key, None)
    _save_channel_map(_locations, cs, cs.locations, config.LOCATIONS_FILE)


async def get_webhook(cs: ChannelState, channel, refresh: bool = False) -> discord.Webhook:
    if cs.webhook is not None and not refresh:
        return cs.webhook
    cs.webhook = None
    for hook in await channel.webhooks():
        if hook.name == "NPC Crew" and hook.token:
            cs.webhook = hook
            return hook
    cs.webhook = await channel.create_webhook(name="NPC Crew")
    return cs.webhook


async def speak(cs: ChannelState, channel, npc, text: str) -> bool:
    """Post as the NPC via the channel webhook. If the webhook was deleted, rebuild
    it and retry; if the webhook path fails entirely (e.g. missing Manage Webhooks),
    fall back to a plain message so the line isn't silently lost. Returns False only
    if nothing could be posted at all."""
    kwargs = {"username": npc.display_name}
    if npc.avatar_url:
        kwargs["avatar_url"] = npc.avatar_url
    for attempt in (1, 2):
        try:
            webhook = await get_webhook(cs, channel, refresh=(attempt == 2))
            await webhook.send(content=text, **kwargs)
            cs.history.append(f"{npc.display_name}: {text}")
            mark_activity(cs)
            return True
        except discord.NotFound:
            cs.webhook = None  # webhook was deleted -> rebuild on the next attempt
        except discord.HTTPException:
            break  # permission/other error -> try the plain-message fallback
    try:
        await channel.send(f"**{npc.display_name}:** {text}")
        cs.history.append(f"{npc.display_name}: {text}")
        mark_activity(cs)
        return True
    except discord.HTTPException:
        log.warning("Could not post reply for %s in channel %s",
                    npc.display_name, getattr(channel, "id", "?"))
        return False


def apply_update(cs: ChannelState, update: dict, speaker_rank: str = "") -> None:
    """Apply a model-proposed ship-state change. Helm / GQ / alert require an officer."""
    if not update:
        return
    update = dict(update)
    if not can_order_ship(speaker_rank):
        blocked = [k for k in ("heading", "speed", "alert") if update.get(k) not in (None, "")]
        for k in blocked:
            update.pop(k, None)
        if blocked:
            log.info("refused ship-control update %s from rank %r", blocked, speaker_rank or "(unknown)")
    ship = cs.ship
    changed = False
    if update.get("heading") is not None:
        ship.heading = int(update["heading"]) % 360
        changed = True
    if update.get("speed") is not None:
        ship.speed = max(0, int(update["speed"]))
        changed = True
    if update.get("alert"):
        ship.alert = str(update["alert"])
        changed = True
    if update.get("notes"):
        ship.notes = str(update["notes"])
        changed = True
        # Officers may write the plot; junior enlisted cannot invent tracks.
        if can_order_ship(speaker_rank) and cs.plot.ingest(str(update["notes"]), source=speaker_rank or "officer"):
            save_plot(cs)
    if changed:
        _ship_states[cs.channel_id] = ship
        save_states(_ship_states, config.STATE_FILE)


def _speaker_rank(member) -> str:
    """The speaker's rank name: an explicit player override, else their Discord-role rank."""
    role_names = [r.name for r in getattr(member, "roles", [])]
    static = resolve_player(
        member.id, getattr(member, "name", ""), getattr(member, "display_name", ""), role_names
    )
    if static and static.rank:
        return static.rank
    return rank_from_roles(role_names)


def speaker_for(member) -> str:
    """How the crew address a Discord member: an explicit override, else Discord-role rank."""
    role_names = [r.name for r in getattr(member, "roles", [])]
    static = resolve_player(
        member.id, getattr(member, "name", ""), getattr(member, "display_name", ""), role_names
    )
    rank = _speaker_rank(member)
    name = static.name if (static and static.name) else ""
    parts = [p for p in (rank, name) if p]
    return " ".join(parts) if parts else "the officer on deck"


def authority_for(member) -> str:
    """Chain-of-command note describing what this speaker is authorised to order."""
    return authority_note(_speaker_rank(member))


def _senior_in_space(cs: ChannelState, space: str):
    """The senior-most crew member currently in `space` -- who picks up a comms hail to
    that station ("Bridge, aye"). None if the station is unmanned right now."""
    here = [n for n in CREW if space_of(cs.location_of(n)) == space]
    return max(here, key=lambda n: rank_index(n.rank)) if here else None


async def route(cs: ChannelState, author_id: int, text: str, now: float, reply_npc=None):
    """Pick which NPC(s) answer this speaker, keeping each person's thread separate.

    Face-to-face reaches only the speaker's compartment (earshot). To reach another
    space you use a ship's circuit (1MC shipwide, 21MC/radio/sound-powered otherwise).
    Naming crew, hailing a station, or a group vocative ("team") can engage them;
    a Discord reply is a direct address. Un-addressed follow-ups continue *that
    speaker's own* active NPC if the relevance gate agrees. Strict channels skip
    continuity. Returns a list.
    """
    called, mentioned = find_addressed_split(text)
    if reply_npc is not None and reply_npc.key not in {n.key for n in called}:
        called = [reply_npc] + called  # a Discord reply is a direct address
        mentioned = [n for n in mentioned if n.key != reply_npc.key]

    # Voice procedure is "TO, FROM", so the FIRST station named is who you're calling
    # -- "Bridge, CIC" hails the Bridge; "CIC" is just your own callsign. The senior
    # watchstander there answers.
    hailed = find_hailed_spaces(text)
    station_keys, station_npcs = set(), []
    if hailed:
        answerer = _senior_in_space(cs, hailed[0])
        if answerer is not None:
            station_npcs.append(answerer)
            station_keys.add(answerer.key)

    group = is_group_address(text)              # "team", "everyone" -> the whole room
    channel = comms_channel(text)               # "1mc" | "circuit" | None
    comms = channel is not None or bool(hailed)  # a ship's circuit is in use -> a hail carries
    strict = cs.channel_id in config.STRICT_CHANNEL_IDS
    prev = cs.active.get(author_id)
    live = cs.thread_npc(author_id, now)
    if called or station_npcs or group:
        here = cs.player_space.get(author_id)
        if here is None and live is not None:
            here = space_of(cs.location_of(live))          # you're with your active crew
        if here is None and called:
            here = space_of(cs.location_of(reply_npc or called[0]))  # bootstrap: first contact only
        if here is not None:
            set_player_space(cs, author_id, here)  # same durability as NPC locations
        # A named vocative or a Discord reply (already folded into `called`) gets
        # the completion. Do not also wake every co-located body. A pure group
        # hail ("team", "all hands", nobody named) is one chorus line from the
        # senior watchstander in the space. MAX_CREW_CHAIN still caps NPC->NPC.
        pure_group = bool(group) and not called and not station_npcs
        chorus_key = None
        if pure_group and here is not None:
            senior = _senior_in_space(cs, here)
            if senior is not None:
                chorus_key = senior.key
        # EARSHOT vs CIRCUITS: someone you CALL by name answers only if they're in your
        # space -- UNLESS you're on a ship's circuit (1MC / radio / intercom / sound-
        # powered), which carries the hail across the ship. Someone you only MENTION
        # needs co-location, and only when nobody was actually hailed. A STATION
        # hailed by callsign is a circuit call.
        called_keys = {n.key for n in called}
        mentioned_keys = {n.key for n in mentioned}
        seen, npcs = set(), []
        for n in list(called) + list(station_npcs) + list(CREW):
            if n.key in seen:
                continue
            co_located = here is not None and space_of(cs.location_of(n)) == here
            if (n.key in station_keys
                    or (n.key in called_keys and (co_located or comms))
                    or n.key == chorus_key
                    or (n.key in mentioned_keys and co_located and not called_keys)):
                npcs.append(n)
                seen.add(n.key)
        if not npcs:
            return []
    elif mentioned:
        here = cs.player_space.get(author_id)
        npcs = mentioned if here is None else [n for n in mentioned if space_of(cs.location_of(n)) == here]
        if not npcs:
            return []
    elif is_far_end_report(text):
        held = cs.npc_on_hold(author_id) or live
        if held is None:
            return []
        npcs = [held]
    elif not strict and live is not None:
        if is_narration(text):
            return []  # a pure scene/story beat -- the crew note it, but it's no one's cue to reply
        if cs.pending.get(live.key) or await brain.is_continuation(live, text, "\n".join(cs.history)):
            npcs = [live]
            set_player_space(cs, author_id, space_of(cs.location_of(live)))
        else:
            return []
    else:
        return []
    cs.active[author_id] = (npcs[-1], now + ENGAGE_WINDOW)  # follow-ups track the last engaged
    return npcs


async def resolve_reply_target(message: discord.Message):
    """If the message replies to a crew member's webhook post, return that NPC.

    Replying in Discord is a natural way to keep talking to someone without naming
    them again -- it engages that crew member directly (no timer, no relevance gate).
    Earshot still applies in route() -- a reply to someone in another space is silent
    unless a circuit is used.
    """
    ref = message.reference
    if ref is None:
        return None
    replied = ref.resolved if isinstance(ref.resolved, discord.Message) else None
    if replied is None and ref.message_id is not None:
        try:
            replied = await message.channel.fetch_message(ref.message_id)
        except discord.HTTPException:
            return None
    if replied is None or replied.webhook_id is None:
        return None  # only replies to crew (webhook) messages engage anyone
    name = getattr(replied.author, "display_name", "") or getattr(replied.author, "name", "")
    return npc_by_display_name(name)


async def deliver_followup(cs: ChannelState, channel, npc, text: str) -> None:
    await asyncio.sleep(FOLLOWUP_DELAY)
    if await speak(cs, channel, npc, text):
        held = (cs.pending.get(npc.key) or "").lower()
        if held.startswith("en route"):
            set_pending(cs, npc.key, text)
        else:
            set_pending(cs, npc.key, "")


def _apply_pending(cs: ChannelState, npc, reply: dict, player_text: str = "") -> None:
    """Keep, replace, or clear the NPC's held action from this reply."""
    pending = reply.get("pending")
    if pending is not None:
        set_pending(cs, npc.key, pending)
        return
    if reply.get("followup"):
        if is_announcement_order(player_text):
            return
        dest = reply.get("location") or cs.location_of(npc)
        set_pending(cs, npc.key, f"en route to {dest}")
        return
    if is_release(player_text):
        set_pending(cs, npc.key, "")
        return
    say = reply.get("say") or ""
    if looks_like_circuit_hold(say) or looks_like_circuit_hold(player_text):
        set_pending(cs, npc.key, "on circuit: " + re.sub(r"\s+", " ", say)[:80])


async def _post_reply(cs: ChannelState, channel, npc, reply: dict,
                      speaker_rank: str = "", player_text: str = ""):
    """Post one NPC line, apply ship/location changes, schedule any follow-up. Returns
    the spoken line (for crew-to-crew scanning) or None if nothing could be posted."""
    if not (reply.get("followup") or "").strip() and is_announcement_order(player_text):
        canned = announcement_followup(player_text, cs.plot)
        if canned:
            reply["followup"] = canned
    if reply.get("followup") and "general quarters" in reply["followup"].lower():
        reply["followup"] = reply["followup"].replace('"', "")
    if not await speak(cs, channel, npc, reply["say"]):
        return None  # couldn't post at all -> don't mutate ship state for an unseen reply
    apply_update(cs, reply.get("state_update") or {}, speaker_rank)
    low = (player_text or "").lower()
    if (
        can_order_ship(speaker_rank)
        and re.search(r"general quarters|battle stations|\bgq\b", low)
        and "secure" not in low
    ):
        apply_update(cs, {"alert": "general quarters"}, speaker_rank)
        cs.plot.add_fact("general quarters, condition Zebra")
        save_plot(cs)
    proposed = (reply.get("location") or "").strip()
    if proposed and allows_location_change(cs, npc, proposed, player_text, reply):
        set_location(cs, npc.key, proposed)
    elif proposed:
        log.info("ignored location jump for %s -> %r", npc.display_name, proposed)
    _apply_pending(cs, npc, reply, player_text)
    if reply.get("followup"):
        asyncio.create_task(deliver_followup(cs, channel, npc, reply["followup"]))
    return reply["say"]


def _crew_hears(cs: ChannelState, caller, callee, text: str) -> bool:
    """Same earshot/circuit rule players get -- a shout in CIC does not reach the main deck."""
    return can_reach(cs.location_of(caller), cs.location_of(callee), text)


async def _run_crew_chain(cs: ChannelState, channel, calls, spoken: set, ship_summary: str) -> None:
    """Let the crew answer each other: when a posted line HAILS another crew member
    ("Bosun! Get in here!"), that crew member replies too, and may move to the caller.
    Earshot and circuits apply the same as player speech. Bounded by MAX_CREW_CHAIN
    and a 'spoken' set (each crew answers at most once per turn)."""
    queue = deque(calls)  # (called_npc, caller_npc, caller_text)
    hops = 0
    while queue and hops < MAX_CREW_CHAIN:
        called_npc, caller, caller_text = queue.popleft()
        if called_npc.key in spoken:
            continue
        if not _crew_hears(cs, caller, called_npc, caller_text):
            log.info("  crew-chain: %s cannot hear %s (earshot)",
                     called_npc.display_name, caller.display_name)
            continue
        spoken.add(called_npc.key)
        hops += 1
        try:
            async with channel.typing():
                reply = await npc_respond(
                    called_npc, caller_text, ship_summary, "\n".join(cs.history),
                    speaker=caller.display_name, location=cs.location_of(called_npc),
                    log=cs.summary, speaker_authority=authority_note(caller.rank),
                    pending=cs.pending.get(called_npc.key, ""),
                    plot=cs.plot.render(cs.ship.alert),
                    pins=cs.pins.render(),
                )
        except Exception:
            log.exception("crew-chain reply failed for %s", called_npc.display_name)
            continue
        posted = await _post_reply(cs, channel, called_npc, reply, speaker_rank=caller.rank,
                                   player_text=caller_text)
        if posted is None or is_signoff(posted):
            continue  # nothing posted, or this crew member signed off -> stop the chain here
        for nxt in find_called(posted):  # this crew member may hail yet another
            if nxt.key != called_npc.key and nxt.key not in spoken and _crew_hears(cs, called_npc, nxt, posted):
                queue.append((nxt, called_npc, posted))


async def _sync_guild(guild) -> None:
    """Push slash commands to one server. Failures used to be silent, which left
    new commands (e.g. /plot) on one guild and missing on another."""
    for attempt in (1, 2):
        try:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            log.info("synced %d slash command(s) to %s (%s)",
                     len(synced), guild.name, guild.id)
            return
        except discord.HTTPException as exc:
            log.warning("slash-command sync failed for %s (attempt %d): %s",
                        getattr(guild, "name", guild), attempt, exc)
            if attempt == 1:
                await asyncio.sleep(2)
        except Exception:
            log.exception("slash-command sync failed for %s", getattr(guild, "name", guild))
            return


@bot.event
async def on_ready():
    for guild in bot.guilds:
        await _sync_guild(guild)
    log.info(
        "Logged in as %s in %d server(s); listening in %d channel(s).",
        bot.user, len(bot.guilds), len(config.RP_CHANNEL_IDS),
    )


@bot.event
async def on_guild_join(guild):
    await _sync_guild(guild)


def _chan(message) -> str:
    return f"#{getattr(message.channel, 'name', None) or message.channel.id}"


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.channel.id not in config.RP_CHANNEL_IDS:
        return
    if not message.content:
        return
    # Prefix commands (!plot) -- slash commands can be locked to admins on HNC.
    if message.content.startswith("!"):
        await bot.process_commands(message)
        return
    if is_ooc(message.content):
        log.info("%s %s: %r -> ignored (OOC)", _chan(message), message.author.display_name, message.content)
        return  # out-of-character / out-of-context aside -- the crew ignore it

    cs = channel_state(message.channel.id)
    speaker = speaker_for(message.author)
    speaker_authority = authority_for(message.author)
    cs.seen_players[message.author.id] = (message.author.display_name, speaker)
    label = speaker if speaker != "the officer on deck" else message.author.display_name
    # OOC and !commands never reach here. Still drop meta ("plot cleared") so it
    # does not become a fact the crew repeat, and so it does not reset the idle recap.
    if not is_noisy_residue(message.content):
        cs.history.append(f"{label}: {message.content}")
        mark_activity(cs)

    if is_signoff(message.content):
        cs.active.pop(message.author.id, None)  # "out"/hang-up ends the exchange
        log.info("%s %s: %r -> sign-off (no reply)", _chan(message), label, message.content)
        return  # voice-procedure sign-off -> the crew give no further reply

    loc = player_location_from_text(message.content)  # "*heads to engineering*" -> track your position
    if loc:
        set_player_space(cs, message.author.id, loc)

    if cs.plot.ingest(message.content, source="player"):
        save_plot(cs)

    reply_npc = await resolve_reply_target(message)
    npcs = await route(cs, message.author.id, message.content, time.monotonic(), reply_npc)
    if not npcs:
        called, mentioned = find_addressed_split(message.content)
        hailed = find_hailed_spaces(message.content)
        reached = bool(called or mentioned or hailed or is_group_address(message.content) or reply_npc)
        log.info("%s %s: %r -> no reply (%s)",
                 _chan(message), label, message.content,
                 "out of earshot" if reached else "not addressed")
        if reached:
            await message.channel.send(
                "*(no answer — not in earshot, and that line is not on a circuit.)*",
                delete_after=12,
            )
        return
    log.info("%s %s: %r -> %s",
             _chan(message), label, message.content,
             ", ".join(n.display_name for n in npcs))

    # Generate every addressed NPC's reply together (busy ones overflow to xAI),
    # then post them in the order they were named so the exchange reads in order.
    history = "\n".join(cs.history)
    ship_summary = cs.ship.summary()
    async with message.channel.typing():
        replies = await asyncio.gather(
            *(
                npc_respond(npc, message.content, ship_summary, history,
                            speaker, cs.location_of(npc), cs.summary,
                            speaker_authority=speaker_authority,
                            plot=cs.plot.render(cs.ship.alert),
                            pins=cs.pins.render(),
                            pending=cs.pending.get(npc.key, ""))
                for npc in npcs
            ),
            return_exceptions=True,
        )

    spoken = {n.key for n in npcs}   # crew who've already answered this turn
    calls = []                       # (called_npc, caller_npc, caller_text) for the crew chain
    speaker_rank = _speaker_rank(message.author)
    for npc, reply in zip(npcs, replies):
        if isinstance(reply, Exception):  # LM Studio down, model not loaded, etc.
            log.warning("Backend error generating reply for %s: %r", npc.display_name, reply)
            await message.channel.send(
                f"*(comms with {npc.display_name} are down: {reply})*", delete_after=12
            )
            continue
        try:
            posted = await _post_reply(
                cs, message.channel, npc, reply,
                speaker_rank=speaker_rank, player_text=message.content,
            )
            if posted is None:
                continue
            if is_signoff(posted):
                continue  # this crew member signed off -> don't spawn more replies
            for c in find_called(posted):  # did this line hail another crew member?
                if c.key != npc.key and c.key not in spoken and _crew_hears(cs, npc, c, posted):
                    calls.append((c, npc, posted))
        except Exception:  # one NPC's failure must not abort the rest of the turn
            log.exception("Failed handling reply for %s", npc.display_name)

    if calls:  # crew answering crew (bounded, non-looping)
        await _run_crew_chain(cs, message.channel, calls, spoken, ship_summary)


@bot.tree.command(name="status", description="Show this channel's ship status")
async def status(interaction: discord.Interaction):
    cs = channel_state(interaction.channel_id)
    info = f"{cs.ship.summary()}\nLLM backend (last used): {brain.LAST_BACKEND}"
    held = [f"{n.display_name}: {cs.pending[n.key]}" for n in CREW if n.key in cs.pending]
    if held:
        info += "\nPending:\n  " + "\n  ".join(held)
    plot = cs.plot.display(cs.ship.alert)
    if plot:
        info += "\n" + plot
    await interaction.response.send_message(f"```\n{info}\n```", ephemeral=True)


_MEMORY_DENIED = "That needs Manage Messages or an officer rank."


def _apply_plot_action(cs: ChannelState, action: str | None, member=None) -> str:
    act = (action or "").strip().lower()
    if act in {"clear", "reset", "wipe"}:
        if member is None or not can_manage_memory(member):
            return _MEMORY_DENIED
        cs.plot.clear()
        cs.plot.facts = []
        save_plot(cs)
        return "Plot cleared."
    return f"```\n{cs.plot.display(cs.ship.alert)}\n```"


@bot.tree.command(name="plot", description="Show or clear the CIC plot (contacts and last facts)")
@discord.app_commands.describe(action="Leave empty to show. Use clear to wipe contacts.")
@discord.app_commands.default_permissions(send_messages=True)
async def plot_cmd(interaction: discord.Interaction, action: str = None):
    await interaction.response.send_message(
        _apply_plot_action(channel_state(interaction.channel_id), action, interaction.user),
        ephemeral=True,
    )


@bot.command(name="plot")
async def plot_prefix(ctx: commands.Context, action: str = None):
    """Show or clear the CIC plot. Use when /plot is locked to admins: !plot / !plot clear"""
    if ctx.channel.id not in config.RP_CHANNEL_IDS:
        return
    await ctx.send(_apply_plot_action(channel_state(ctx.channel.id), action, ctx.author))


def _pin_mutate(cs: ChannelState, member, action: str, text: str) -> str | None:
    """Apply a pin command, or return None when the caller must run pin-extract.

    Every /pin subcommand is stricter than Send Messages: Manage Messages or
    an officer rank. Listing is included so the command is not a back door.
    """
    act = (action or "list").strip().lower()
    if not can_manage_memory(member):
        return _MEMORY_DENIED
    if act == "list":
        return cs.pins.display()
    if act == "add":
        ok, msg = cs.pins.add(text)
        if not ok:
            return msg
        save_pins(cs)
        return f"Pinned ({len(cs.pins.items)}/12): {msg}"
    if act in {"remove", "rm", "delete", "del"}:
        ok, msg = cs.pins.remove(text)
        if not ok:
            return msg
        save_pins(cs)
        return f"Removed pin: {msg}"
    if act in {"clear", "reset", "wipe"}:
        cs.pins.clear()
        save_pins(cs)
        return "Pins cleared."
    if act == "extract":
        return None
    return "Use add, list, remove, clear, or extract. Example: /pin add Bosun is waiting at the cabin."


def _pin_extract_ready(cs: ChannelState, member) -> str | None:
    """Permission, hygiene, and cooldown. None means the slot is taken and the LLM may run."""
    denied = _pin_mutate(cs, member, "extract", "")
    if denied is not None:
        return denied
    if not history_for_recap(cs.history):
        return "Nothing in-world in this scene to pin."
    wait = take_memory_llm_slot(cs)
    if wait:
        return f"Pin extract is cooling down. Try again in {wait}s."
    return None


async def _pin_extract(cs: ChannelState) -> str:
    """Caller already took the memory-LLM slot."""
    recent = history_for_recap(cs.history)
    lines = await brain.extract_pins(recent)
    added = []
    for line in lines:
        ok, msg = cs.pins.add(line)
        if ok:
            added.append(msg)
    if added:
        save_pins(cs)
        return "Pinned:\n" + "\n".join(f"- {p}" for p in added)
    return "No in-world facts worth pinning."


pin_group = discord.app_commands.Group(
    name="pin",
    description="Episodic pins for this channel (officer or Manage Messages to edit)",
)


@pin_group.command(name="add", description="Pin a short in-world fact (200 characters, 12 per channel)")
@discord.app_commands.describe(text="The fact to remember")
async def pin_add(interaction: discord.Interaction, text: str):
    cs = channel_state(interaction.channel_id)
    await interaction.response.send_message(
        _pin_mutate(cs, interaction.user, "add", text), ephemeral=True,
    )


@pin_group.command(name="list", description="List episodic pins for this channel")
async def pin_list(interaction: discord.Interaction):
    cs = channel_state(interaction.channel_id)
    await interaction.response.send_message(
        _pin_mutate(cs, interaction.user, "list", ""), ephemeral=True,
    )


@pin_group.command(name="remove", description="Remove one pin by number or by words from the text")
@discord.app_commands.describe(which="Pin number from /pin list, or a few words from it")
async def pin_remove(interaction: discord.Interaction, which: str):
    cs = channel_state(interaction.channel_id)
    await interaction.response.send_message(
        _pin_mutate(cs, interaction.user, "remove", which), ephemeral=True,
    )


@pin_group.command(name="clear", description="Wipe every episodic pin on this channel")
async def pin_clear(interaction: discord.Interaction):
    cs = channel_state(interaction.channel_id)
    await interaction.response.send_message(
        _pin_mutate(cs, interaction.user, "clear", ""), ephemeral=True,
    )


@pin_group.command(name="extract", description="Ask the model for a few in-world pins from this scene")
async def pin_extract_cmd(interaction: discord.Interaction):
    cs = channel_state(interaction.channel_id)
    ready = _pin_extract_ready(cs, interaction.user)
    if ready is not None:
        await interaction.response.send_message(ready, ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(await _pin_extract(cs), ephemeral=True)


bot.tree.add_command(pin_group)


@bot.command(name="pin")
async def pin_prefix(ctx: commands.Context, action: str = "list", *, text: str = ""):
    """Episodic pins. !pin list / !pin add <fact> / !pin remove <n> / !pin clear"""
    if ctx.channel.id not in config.RP_CHANNEL_IDS:
        return
    cs = channel_state(ctx.channel.id)
    if (action or "list").strip().lower() == "extract":
        ready = _pin_extract_ready(cs, ctx.author)
        if ready is not None:
            await ctx.send(ready)
            return
        await ctx.send(await _pin_extract(cs))
        return
    await ctx.send(_pin_mutate(cs, ctx.author, action, text))


@bot.tree.command(name="crew", description="List the NPC crew and how to address them")
async def crew(interaction: discord.Interaction):
    cs = channel_state(interaction.channel_id)
    blocks = []
    for n in CREW:
        rank_rate = ", ".join(p for p in [n.rank, n.rate] if p)
        header = f"**{n.display_name}**"
        if rank_rate:
            header += f"  ({rank_rate})"
        blocks.append(
            f"{header}\n  address as: {', '.join(n.aliases)}\n  location: {cs.location_of(n)}"
        )
    await interaction.response.send_message("\n".join(blocks), ephemeral=True)


@bot.tree.command(name="where", description="Show which space you're in and which crew are in earshot")
async def where(interaction: discord.Interaction):
    cs = channel_state(interaction.channel_id)
    here = cs.player_space.get(interaction.user.id)
    if not here:
        await interaction.response.send_message(
            "You're not placed anywhere yet -- talk to a crew member (or narrate heading "
            "somewhere with them) and that sets where you are.", ephemeral=True,
        )
        return
    crew_here = [n.display_name for n in CREW if space_of(cs.location_of(n)) == here]
    body = ", ".join(crew_here) if crew_here else "nobody"
    await interaction.response.send_message(
        f"You're in: **{here}**\nIn earshot: {body}", ephemeral=True,
    )


@bot.tree.command(name="roster", description="Show who's aboard and the rank the crew use for them")
async def roster(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    entries, note = {}, ""
    try:
        async for member in interaction.guild.fetch_members(limit=None):
            if not member.bot:
                entries[member.id] = (member.display_name, speaker_for(member))
    except Exception:
        note = "(A full scan needs the Server Members Intent. Showing people seen so far.)"
        entries = dict(channel_state(interaction.channel_id).seen_players)
    lines = []
    for name, rank in entries.values():
        shown = rank if rank != "the officer on deck" else "(no rank role)"
        lines.append(f"- {name}: {shown}")
    body = "\n".join(lines) if lines else "Nobody recognized yet."
    if note:
        body = f"{note}\n{body}"
    await interaction.followup.send(f"**Ship's roster**\n{body}", ephemeral=True)


async def recap_channel(cs: ChannelState) -> bool:
    """Write this channel's chronicle if there is something new. Returns True if saved.

    The scene seed is written first, including on idle and shutdown, so a failed
    LLM call still leaves the last lines for the next process. OOC, commands,
    and meta such as "plot cleared" are left out of the summary.
    """
    if not cs.history or not cs.log_dirty:
        return False
    save_scene_seed(cs)
    recent = history_for_recap(cs.history)
    if recent.strip():
        # Idle, shutdown, and /recap share this clock so a second LLM recap
        # cannot start the moment the first one finishes.
        mark_memory_llm(cs)
        cs.summary = await brain.summarize(recent, cs.summary)
        _logs[cs.channel_id] = cs.summary
        save_texts(_logs, config.LOG_FILE)
    cs.log_dirty = False
    return True


def recap_gate(cs: ChannelState, member, action: str | None) -> str | None:
    """Immediate reply for /recap, or None when the caller should run the LLM."""
    act = (action or "").strip().lower()
    if act in {"clear", "reset", "wipe"}:
        if not can_manage_memory(member):
            return _MEMORY_DENIED
        clear_chronicle(cs)
        return "Ship's log cleared."
    if act:
        return "Leave the action empty to write the log, or use clear to wipe it."
    if not cs.history:
        return "Nothing has happened to log yet."
    wait = take_memory_llm_slot(cs)
    if wait:
        return f"Recap is cooling down. Try again in {wait}s."
    return None


async def run_recap(cs: ChannelState) -> str:
    """User-triggered chronicle update. The cooldown slot was taken in recap_gate."""
    cs.log_dirty = True
    await recap_channel(cs)
    return f"**Ship's log updated:**\n{cs.summary or '(empty)'}"


async def recap_dirty_idle() -> None:
    now = time.monotonic()
    idle_after = config.RECAP_IDLE_SECONDS
    for cs in list(_channels.values()):
        if not cs.log_dirty or not cs.last_activity:
            continue
        if now - cs.last_activity < idle_after:
            continue
        try:
            if await recap_channel(cs):
                log.info("auto-recap channel %s after idle", cs.channel_id)
        except Exception:
            log.exception("auto-recap failed for channel %s", cs.channel_id)


async def recap_all_dirty() -> None:
    for cs in list(_channels.values()):
        if not cs.log_dirty or not cs.history:
            continue
        try:
            if await recap_channel(cs):
                log.info("shutdown recap channel %s", cs.channel_id)
        except Exception:
            log.exception("shutdown recap failed for channel %s", cs.channel_id)


async def _idle_recap_loop() -> None:
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(60)
        await recap_dirty_idle()


@bot.tree.command(name="recap", description="Summarize this session into the ship's log, or clear it")
@discord.app_commands.describe(action="Leave empty to write the log. Use clear to wipe it.")
async def recap(interaction: discord.Interaction, action: str = None):
    cs = channel_state(interaction.channel_id)
    quick = recap_gate(cs, interaction.user, action)
    if quick is not None:
        await interaction.response.send_message(quick, ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(await run_recap(cs), ephemeral=True)


@bot.command(name="recap")
async def recap_prefix(ctx: commands.Context, action: str = None):
    """Write or clear the ship's log. !recap / !recap clear"""
    if ctx.channel.id not in config.RP_CHANNEL_IDS:
        return
    cs = channel_state(ctx.channel.id)
    quick = recap_gate(cs, ctx.author, action)
    if quick is not None:
        await ctx.send(quick)
        return
    await ctx.send(await run_recap(cs))


BOT_LOG_FILE = str(config.BASE_DIR / "bot.log")
_LOCK_PORT = 49219  # arbitrary localhost port used as a single-instance guard
_instance_lock = None


def _setup_logging() -> None:
    """Send our logs and discord.py's to a rotating bot.log (plus the console), so
    crashes and errors are captured even when nobody is watching the window."""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(BOT_LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console)


def _acquire_single_instance_lock() -> bool:
    """Bind a localhost port as a lock. A second copy of the bot fails to bind and
    exits, preventing two instances from posting doubled replies. The OS frees the
    port automatically when the process ends (even on a crash)."""
    global _instance_lock
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", _LOCK_PORT))
    except OSError:
        s.close()
        return False
    s.listen(1)
    _instance_lock = s  # keep the socket open for the lifetime of the process
    return True


def _start_local_model() -> None:
    """Best-effort: if this box is configured for a local LM Studio server, start it
    and load the model (24k context, 4 parallel slots). No-ops when LLM_BASE_URL is
    empty / not loopback, or when the `lms` CLI isn't installed (Mac xAI-only)."""
    url = (config.LLM_BASE_URL or "").lower()
    if "127.0.0.1" not in url and "localhost" not in url:
        return
    lms = shutil.which("lms")
    if not lms:
        log.info("lms CLI not found; skipping local-model autoload.")
        return
    model = config.LLM_MODEL
    try:
        subprocess.run([lms, "server", "start"], check=False, capture_output=True, timeout=30)
        ps = subprocess.run([lms, "ps"], check=False, capture_output=True, text=True, timeout=15)
        already = model and model in (ps.stdout or "")
        if already:
            log.info("Local model already loaded: %s", model)
            return
        # Parallel 2-3 is snappier for one-line replies (less batching delay than 4).
        # 4 matches LM Studio's default and LOCAL_MAX_INFLIGHT. Thinking stays off
        # in brain.py (reasoning_effort "none"). Do not pass json_schema to local Gemma.
        subprocess.run(
            [lms, "load", model, "--gpu", "max", "--parallel", "4",
             "-c", str(LOCAL_CONTEXT), "-y"],
            check=False, timeout=180,
        )
        log.info("Requested load of local model %s", model)
    except Exception:
        log.warning("Could not auto-start LM Studio; will fall back to xAI if configured.",
                    exc_info=True)


if __name__ == "__main__":
    _setup_logging()
    if not _acquire_single_instance_lock():
        raise SystemExit(
            f"Another bot instance is already running (single-instance lock on "
            f"127.0.0.1:{_LOCK_PORT}). Close the other one first to avoid doubled replies."
        )
    _start_local_model()
    try:
        bot.run(config.DISCORD_TOKEN, log_handler=None)
    except discord.LoginFailure:
        raise SystemExit("DISCORD_TOKEN is invalid. Run `python setup.py` or fix it in .env.")
    except discord.PrivilegedIntentsRequired:
        raise SystemExit(
            "Enable 'Message Content Intent' in the Developer Portal (Bot tab), then run again."
        )
    except (KeyboardInterrupt, RuntimeError):
        # Ctrl+C: discord.py can raise a noisy "event loop is already running/closed"
        # RuntimeError while tearing down. The bot has stopped -- exit quietly.
        print("\nHaylerBot stopped.")
        raise SystemExit(0)
