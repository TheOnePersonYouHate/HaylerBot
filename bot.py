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
from npcs import (
    CREW, SHIP, authority_note, comms_channel, find_addressed_split, find_called,
    find_hailed_spaces, is_group_address, npc_by_display_name,
    player_location_from_text, rank_from_roles, rank_index, resolve_player, space_of,
)
from ship import ShipState, load_states, load_texts, save_states, save_texts

log = logging.getLogger("naval_bot")

intents = discord.Intents.default()
intents.message_content = True  # privileged: enable in the Developer Portal

ENGAGE_WINDOW = config.CONTINUITY_SECONDS  # seconds before the crew disengage
# (wait longer than this without addressing anyone to talk out-of-context freely)
HISTORY_LIMIT = 120  # how many recent messages per channel the crew "remember"
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


_ship_states = load_states(config.STATE_FILE)  # {channel_id: ShipState}
_logs = load_texts(config.LOG_FILE)            # {channel_id: persistent ship's-log summary}


class CrewBot(commands.Bot):
    async def setup_hook(self):
        # Commands are synced per-guild in on_ready / on_guild_join so they
        # appear in every server the bot is in.
        pass


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
    summary: str = ""        # persistent ship's log carried over from earlier sessions

    def location_of(self, npc) -> str:
        return self.locations.get(npc.key) or npc.station or "their usual station"


_channels = {}


def channel_state(channel_id: int) -> ChannelState:
    cs = _channels.get(channel_id)
    if cs is None:
        cs = ChannelState(channel_id=channel_id, ship=_ship_states.get(channel_id) or ShipState(name=SHIP["display"]))
        cs.summary = _logs.get(channel_id, "")
        _channels[channel_id] = cs
    return cs


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
            return True
        except discord.NotFound:
            cs.webhook = None  # webhook was deleted -> rebuild on the next attempt
        except discord.HTTPException:
            break  # permission/other error -> try the plain-message fallback
    try:
        await channel.send(f"**{npc.display_name}:** {text}")
        cs.history.append(f"{npc.display_name}: {text}")
        return True
    except discord.HTTPException:
        log.warning("Could not post reply for %s in channel %s",
                    npc.display_name, getattr(channel, "id", "?"))
        return False


def apply_update(cs: ChannelState, update: dict) -> None:
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
    if called or station_npcs or group:
        here = cs.player_space.get(author_id)
        if here is None and prev is not None and now < prev[1]:
            here = space_of(cs.location_of(prev[0]))          # you're with your active crew
        if here is None and called:
            here = space_of(cs.location_of(reply_npc or called[0]))  # bootstrap: first contact only
        if here is not None:
            cs.player_space[author_id] = here                 # remember where you are (don't teleport on a call)
        # EARSHOT vs CIRCUITS: someone you CALL by name answers only if they're in your
        # space -- UNLESS you're on a ship's circuit (1MC / radio / intercom / sound-
        # powered), which carries the hail across the ship. Someone you only MENTION, or
        # a group hail, needs co-location. A STATION hailed by callsign is a circuit call.
        called_keys = {n.key for n in called}
        mentioned_keys = {n.key for n in mentioned}
        seen, npcs = set(), []
        for n in list(called) + list(station_npcs) + list(CREW):
            if n.key in seen:
                continue
            co_located = here is not None and space_of(cs.location_of(n)) == here
            if (n.key in station_keys
                    or (n.key in called_keys and (co_located or comms))
                    or (group and co_located)
                    or (n.key in mentioned_keys and co_located)):
                npcs.append(n)
                seen.add(n.key)
        if not npcs:
            return []
    elif mentioned:
        here = cs.player_space.get(author_id)
        npcs = mentioned if here is None else [n for n in mentioned if space_of(cs.location_of(n)) == here]
        if not npcs:
            return []
    elif not strict and prev is not None and now < prev[1]:
        if is_narration(text):
            return []  # a pure scene/story beat -- the crew note it, but it's no one's cue to reply
        if await brain.is_continuation(prev[0], text, "\n".join(cs.history)):
            npcs = [prev[0]]
            cs.player_space[author_id] = space_of(cs.location_of(prev[0]))
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
    await speak(cs, channel, npc, text)


async def _post_reply(cs: ChannelState, channel, npc, reply: dict):
    """Post one NPC line, apply ship/location changes, schedule any follow-up. Returns
    the spoken line (for crew-to-crew scanning) or None if nothing could be posted."""
    if not await speak(cs, channel, npc, reply["say"]):
        return None  # couldn't post at all -> don't mutate ship state for an unseen reply
    apply_update(cs, reply["state_update"])
    if reply["location"]:
        cs.locations[npc.key] = reply["location"]
    if reply["followup"]:
        asyncio.create_task(deliver_followup(cs, channel, npc, reply["followup"]))
    return reply["say"]


async def _run_crew_chain(cs: ChannelState, channel, calls, spoken: set, ship_summary: str) -> None:
    """Let the crew answer each other: when a posted line HAILS another crew member
    ("Bosun! Get in here!"), that crew member replies too, and may move to the caller.
    Bounded by MAX_CREW_CHAIN and a 'spoken' set (each crew answers at most once per
    turn), so an A->B->A ping-pong can never loop."""
    queue = deque(calls)  # (called_npc, caller_npc, caller_text)
    hops = 0
    while queue and hops < MAX_CREW_CHAIN:
        called_npc, caller, caller_text = queue.popleft()
        if called_npc.key in spoken:
            continue
        spoken.add(called_npc.key)
        hops += 1
        try:
            async with channel.typing():
                reply = await npc_respond(
                    called_npc, caller_text, ship_summary, "\n".join(cs.history),
                    speaker=caller.display_name, location=cs.location_of(called_npc),
                    log=cs.summary, speaker_authority=authority_note(caller.rank),
                )
        except Exception:
            log.exception("crew-chain reply failed for %s", called_npc.display_name)
            continue
        posted = await _post_reply(cs, channel, called_npc, reply)
        if posted is None or is_signoff(posted):
            continue  # nothing posted, or this crew member signed off -> stop the chain here
        for nxt in find_called(posted):  # this crew member may hail yet another
            if nxt.key != called_npc.key and nxt.key not in spoken:
                queue.append((nxt, called_npc, posted))


async def _sync_guild(guild) -> None:
    try:
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    except Exception:
        pass


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


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.channel.id not in config.RP_CHANNEL_IDS:
        return
    if not message.content:
        return
    if is_ooc(message.content):
        return  # out-of-character / out-of-context aside -- the crew ignore it

    cs = channel_state(message.channel.id)
    speaker = speaker_for(message.author)
    speaker_authority = authority_for(message.author)
    cs.seen_players[message.author.id] = (message.author.display_name, speaker)
    label = speaker if speaker != "the officer on deck" else message.author.display_name
    cs.history.append(f"{label}: {message.content}")

    if is_signoff(message.content):
        cs.active.pop(message.author.id, None)  # "out"/hang-up ends the exchange
        return  # voice-procedure sign-off -> the crew give no further reply

    loc = player_location_from_text(message.content)  # "*heads to engineering*" -> track your position
    if loc:
        cs.player_space[message.author.id] = loc

    reply_npc = await resolve_reply_target(message)
    npcs = await route(cs, message.author.id, message.content, time.monotonic(), reply_npc)
    if not npcs:
        return

    # Generate every addressed NPC's reply together (busy ones overflow to xAI),
    # then post them in the order they were named so the exchange reads in order.
    history = "\n".join(cs.history)
    ship_summary = cs.ship.summary()
    async with message.channel.typing():
        replies = await asyncio.gather(
            *(
                npc_respond(npc, message.content, ship_summary, history,
                            speaker, cs.location_of(npc), cs.summary,
                            speaker_authority=speaker_authority)
                for npc in npcs
            ),
            return_exceptions=True,
        )

    spoken = {n.key for n in npcs}   # crew who've already answered this turn
    calls = []                       # (called_npc, caller_npc, caller_text) for the crew chain
    for npc, reply in zip(npcs, replies):
        if isinstance(reply, Exception):  # LM Studio down, model not loaded, etc.
            log.warning("Backend error generating reply for %s: %r", npc.display_name, reply)
            await message.channel.send(
                f"*(comms with {npc.display_name} are down: {reply})*", delete_after=12
            )
            continue
        try:
            posted = await _post_reply(cs, message.channel, npc, reply)
            if posted is None:
                continue
            if is_signoff(posted):
                continue  # this crew member signed off -> don't spawn more replies
            for c in find_called(posted):  # did this line hail another crew member?
                if c.key != npc.key and c.key not in spoken:
                    calls.append((c, npc, posted))
        except Exception:  # one NPC's failure must not abort the rest of the turn
            log.exception("Failed handling reply for %s", npc.display_name)

    if calls:  # crew answering crew (bounded, non-looping)
        await _run_crew_chain(cs, message.channel, calls, spoken, ship_summary)


@bot.tree.command(name="status", description="Show this channel's ship status")
async def status(interaction: discord.Interaction):
    cs = channel_state(interaction.channel_id)
    info = f"{cs.ship.summary()}\nLLM backend (last used): {brain.LAST_BACKEND}"
    await interaction.response.send_message(f"```\n{info}\n```", ephemeral=True)


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


@bot.tree.command(name="recap", description="Summarize this session into the ship's log for next time")
async def recap(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    cs = channel_state(interaction.channel_id)
    if not cs.history:
        await interaction.followup.send("Nothing has happened to log yet.", ephemeral=True)
        return
    cs.summary = await brain.summarize("\n".join(cs.history), cs.summary)
    _logs[cs.channel_id] = cs.summary
    save_texts(_logs, config.LOG_FILE)
    await interaction.followup.send(f"**Ship's log updated:**\n{cs.summary}", ephemeral=True)


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
