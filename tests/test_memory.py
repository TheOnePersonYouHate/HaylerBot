"""Pins, player locations, scene seed, recap hygiene, prompt cache order, token tiers.

Run from the repo root:

    python tests/test_memory.py
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("RP_CHANNEL_ID", "1")
os.environ.setdefault("LLM_BASE_URL", "")
os.environ.setdefault("XAI_API_KEY", "")

from memory import (  # noqa: E402
    MAX_PIN_CHARS, MAX_PINS, SCENE_SEED_LINES, Pinboard, history_for_recap,
    is_noisy_residue, load_pinboards, parse_pin_lines, save_pinboards, scene_blob,
)
from npcs import CREW  # noqa: E402
from ship import ShipState, load_maps, load_texts  # noqa: E402


def check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _npc(key):
    return next(n for n in CREW if n.key == key)


class _Role:
    def __init__(self, name):
        self.name = name


class _Perms:
    def __init__(self, manage):
        self.manage_messages = manage


class _Member:
    def __init__(self, role, manage=False):
        self.roles = [_Role(role)]
        self.id = 7
        self.name = "tester"
        self.display_name = "Tester"
        self.guild_permissions = _Perms(manage)


def test_hygiene():
    print("hygiene")
    check("plot cleared is meta", is_noisy_residue("plot cleared"))
    check("command is meta", is_noisy_residue("!plot clear"))
    check("slash command is meta", is_noisy_residue("/pin add hello"))
    check("ooc is meta", is_noisy_residue("(this is ooc)"))
    check("contact is not meta", not is_noisy_residue("*three friendly aircraft, bearing 045*"))
    check("air picture is not meta", not is_noisy_residue("air picture clear"))
    recent = history_for_recap([
        "LT: *three friendly aircraft, bearing 045*",
        "LT: plot cleared",
        "LT: !plot clear",
        "LT: (ooc note)",
        "LT: Bosun is still at the cabin door",
    ])
    check("recap keeps the contact", "friendly aircraft" in recent)
    check("recap keeps the cabin", "cabin" in recent)
    check("recap drops plot cleared", "plot cleared" not in recent.lower())
    check("recap drops the command", "!plot" not in recent)
    lines = parse_pin_lines("- Bosun is at the cabin\n- plot cleared\n1. Hoover holds CIC")
    check("parser keeps in-world lines", len(lines) == 2)
    check("parser drops plot cleared", all("plot cleared" not in p.lower() for p in lines))
    check("NONE alone is empty", parse_pin_lines("NONE") == [])


def test_pins_cap_and_disk():
    print("pins")
    board = Pinboard()
    ok, _ = board.add("plot cleared")
    check("refuse meta pin", not ok)
    ok, _ = board.add("// ooc")
    check("refuse ooc pin", not ok)
    ok, msg = board.add("Bosun is waiting at the captain's cabin")
    check("pin added", ok and "cabin" in msg)
    ok, msg = board.add("x" * 250)
    check("pin clipped to 200", ok and len(msg) == MAX_PIN_CHARS)
    for i in range(MAX_PINS - 2):
        added, _ = board.add(f"watch fact {i} still unresolved")
        check(f"pin {i} fits", added)
    check("at cap", len(board.items) == MAX_PINS)
    ok, _ = board.add("one fact too many for the watch")
    check("thirteenth refused", not ok)
    ok, gone = board.remove("1")
    check("remove by number", ok and "cabin" in gone)
    ok, _ = board.add("Hoover has the air picture")
    check("slot reopened", ok)
    shown = board.display()
    check("list is numbered", shown.startswith("1."))
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "pins.json")
        save_pinboards({8: board}, path)
        loaded = load_pinboards(path)
        check("roundtrip channel", 8 in loaded)
        check("roundtrip text", any("air picture" in p for p in loaded[8].items))
        board.clear()
        save_pinboards({8: board}, path)
        check("clear omits the channel", 8 not in load_pinboards(path))


def test_player_location_restart():
    print("player location restart")
    import bot

    cid = 424242
    orig_file = bot.config.PLAYER_LOCATIONS_FILE
    orig_store = bot._player_locations
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "player_locations.json")
            bot.config.PLAYER_LOCATIONS_FILE = path
            bot._player_locations = {}
            cs = bot.ChannelState(channel_id=cid, ship=ShipState())
            bot.set_player_space(cs, 99, "cic")
            check("in memory", cs.player_space[99] == "cic")
            loaded = load_maps(path)
            check("on disk like npc locations", loaded[cid]["99"] == "cic")
            bot.set_player_space(cs, 99, "cic")
            check("same space does not need a new value", cs.player_space[99] == "cic")
            bot._player_locations = load_maps(path)
            bot._channels.pop(cid, None)
            again = bot.channel_state(cid)
            check("restart restores int author id", again.player_space.get(99) == "cic")
    finally:
        bot.config.PLAYER_LOCATIONS_FILE = orig_file
        bot._player_locations = orig_store
        bot._channels.pop(cid, None)


def test_scene_seed_and_recap_hygiene():
    print("scene seed")
    import bot

    cid = 434343
    orig_scene = bot.config.SCENE_FILE
    orig_log = bot.config.LOG_FILE
    orig_scenes = bot._scenes
    orig_logs = bot._logs
    orig_summarize = bot.brain.summarize
    try:
        with tempfile.TemporaryDirectory() as tmp:
            bot.config.SCENE_FILE = str(Path(tmp) / "scene.json")
            bot.config.LOG_FILE = str(Path(tmp) / "chronicle.json")
            bot._scenes = {}
            bot._logs = {}
            cs = bot.ChannelState(channel_id=cid, ship=ShipState())
            for i in range(50):
                cs.history.append(f"LT: line {i}")
            cs.history.append("LT: plot cleared")
            blob = scene_blob(cs.history)
            lines = blob.splitlines()
            check("seed length", len(lines) == SCENE_SEED_LINES)
            check("seed keeps the tail", lines[-1] == "LT: line 49")
            check("seed drops plot cleared", all("plot cleared" not in ln.lower() for ln in lines))
            bot.save_scene_seed(cs)
            stored = load_texts(bot.config.SCENE_FILE)[cid]
            check("seed on disk", stored.splitlines()[-1] == "LT: line 49")

            seen = {}

            async def fake_summarize(recent, prior=""):
                seen["recent"] = recent
                return "The watch held CIC."

            bot.brain.summarize = fake_summarize
            cs.log_dirty = True
            saved = asyncio.run(bot.recap_channel(cs))
            check("recap saved", saved)
            check("recap input dropped meta", "plot cleared" not in seen["recent"].lower())
            check("recap input kept a line", "line 49" in seen["recent"])
            check("chronicle text stored", "CIC" in bot._logs[cid])
            check("not dirty after recap", cs.log_dirty is False)

            bot._scenes[cid] = stored
            bot._channels.pop(cid, None)
            again = bot.channel_state(cid)
            check("load restores history", list(again.history)[-1] == "LT: line 49")
            check("restored seed is not a new session", again.log_dirty is False)
    finally:
        bot.brain.summarize = orig_summarize
        bot.config.SCENE_FILE = orig_scene
        bot.config.LOG_FILE = orig_log
        bot._scenes = orig_scenes
        bot._logs = orig_logs
        bot._channels.pop(cid, None)


def test_memory_gates():
    print("memory gates")
    import bot

    seaman = _Member("Seaman")
    officer = _Member("Lieutenant")
    mod = _Member("Seaman", manage=True)
    check("seaman cannot manage memory", not bot.can_manage_memory(seaman))
    check("officer can manage memory", bot.can_manage_memory(officer))
    check("manage messages can manage memory", bot.can_manage_memory(mod))

    cid = 444444
    orig_plot = bot.config.PLOT_FILE
    orig_log = bot.config.LOG_FILE
    orig_pins = bot.config.PINS_FILE
    orig_plots = bot._plots
    orig_logs = bot._logs
    orig_pins_store = bot._pins
    try:
        with tempfile.TemporaryDirectory() as tmp:
            bot.config.PLOT_FILE = str(Path(tmp) / "plot.json")
            bot.config.LOG_FILE = str(Path(tmp) / "chronicle.json")
            bot.config.PINS_FILE = str(Path(tmp) / "pins.json")
            bot._plots = {}
            bot._logs = {}
            bot._pins = {}
            cs = bot.ChannelState(channel_id=cid, ship=ShipState())
            cs.plot.ingest("*surface contact bearing 270 at 12nm*", "player")
            refused = bot._apply_plot_action(cs, "clear", seaman)
            check("seaman cannot clear the plot", "officer" in refused.lower())
            check("plot still held", cs.plot.contacts)
            cleared = bot._apply_plot_action(cs, "clear", officer)
            check("officer cleared the plot", cleared == "Plot cleared." and not cs.plot.contacts)

            ok, _ = cs.pins.add("Bosun is at the cabin")
            check("direct add", ok)
            denied_list = bot._pin_mutate(cs, seaman, "list", "")
            check("seaman cannot list pins", denied_list == bot._MEMORY_DENIED)
            listed = bot._pin_mutate(cs, officer, "list", "")
            check("officer can list pins", "cabin" in listed)
            denied = bot._pin_mutate(cs, seaman, "clear", "")
            check("seaman cannot clear pins", denied == bot._MEMORY_DENIED and cs.pins.items)
            wiped = bot._pin_mutate(cs, mod, "clear", "")
            check("manage messages cleared pins", wiped == "Pins cleared." and not cs.pins.items)

            cs.summary = "The ship was at general quarters."
            bot._logs[cid] = cs.summary
            denied_log = bot.recap_gate(cs, seaman, "clear")
            check("seaman cannot clear the chronicle", denied_log == bot._MEMORY_DENIED)
            check("chronicle remains", cs.summary)
            cleared_log = bot.recap_gate(cs, officer, "clear")
            check("officer cleared the chronicle", cleared_log == "Ship's log cleared.")
            check("chronicle empty", cs.summary == "" and cid not in bot._logs)
    finally:
        bot.config.PLOT_FILE = orig_plot
        bot.config.LOG_FILE = orig_log
        bot.config.PINS_FILE = orig_pins
        bot._plots = orig_plots
        bot._logs = orig_logs
        bot._pins = orig_pins_store


def test_cooldown_and_chorus():
    print("cooldown and chorus")
    import bot

    cs = bot.ChannelState(channel_id=455, ship=ShipState())
    check("cooldown starts open", bot.memory_llm_wait(cs) == 0)
    check("slot taken", bot.take_memory_llm_slot(cs) == 0)
    check("second call waits", bot.take_memory_llm_slot(cs) > 0)
    cs.last_memory_llm = time.monotonic() - 10_000
    check("old stamp is ready", bot.memory_llm_wait(cs) == 0)

    hoover = _npc("hoover")
    pike = _npc("lookout")
    for n in CREW:
        cs.locations[n.key] = "the engine room"
    cs.locations[hoover.key] = "CIC"
    cs.locations[pike.key] = "CIC"
    cs.player_space[5] = "cic"
    orig_players = bot.config.PLAYER_LOCATIONS_FILE
    try:
        with tempfile.TemporaryDirectory() as tmp:
            bot.config.PLAYER_LOCATIONS_FILE = str(Path(tmp) / "players.json")
            team = asyncio.run(bot.route(cs, 5, "how we feeling, team?", time.monotonic()))
            check("group hail is one chorus", len(team) == 1)
            check("chorus is the senior in the space", team[0].key == hoover.key)
            named = asyncio.run(bot.route(cs, 5, "Pike, team, what do you see?", time.monotonic()))
            check("named vocative does not fan out", [n.key for n in named] == [pike.key])
            mentioned = asyncio.run(bot.route(cs, 5, "Hoover, is Pike ready?", time.monotonic()))
            check("mention does not add a second completion", [n.key for n in mentioned] == [hoover.key])
            check("crew chain cap unchanged", bot.MAX_CREW_CHAIN == 3)
    finally:
        bot.config.PLAYER_LOCATIONS_FILE = orig_players


def test_prompt_and_tokens():
    print("prompt and tokens")
    import brain

    check("normal reply is 350-450", 350 <= brain.TOKENS_REPLY <= 450)
    check("chatter uses the normal budget",
          brain.reply_max_tokens("Bosun, how's the deck?") == brain.TOKENS_REPLY)
    check("1MC uses the long budget",
          brain.reply_max_tokens("Bosun, sound general quarters.") == brain.TOKENS_LONG)
    check("movement follow-up uses the long budget",
          brain.reply_max_tokens("Bosun, report to the captain's cabin.") == brain.TOKENS_LONG)
    check("long budget is higher", brain.TOKENS_LONG > brain.TOKENS_REPLY)
    check("recap budget is higher", brain.TOKENS_RECAP > brain.TOKENS_REPLY)
    check("classifier is tiny", brain.TOKENS_CLASSIFIER <= 64)
    check("local json schema stays off", brain.LOCAL_JSON_SCHEMA is False)
    template = brain.SYSTEM_TEMPLATE
    check("ship block before persona", template.find("{ship_knowledge}") < template.find("{persona}"))
    check("navy block before persona", template.find("{navy_reference}") < template.find("{persona}"))
    check("chronicle before pins", template.find("{chronicle}") < template.find("{pins}"))
    check("pins before history", template.find("{pins}") < template.find("{history}"))
    check("cache comment names the prefix", "prefix" in brain.__doc__ or "Prefix cache" in Path(brain.__file__).read_text(encoding="utf-8"))


def main():
    test_hygiene()
    test_pins_cap_and_disk()
    test_player_location_restart()
    test_scene_seed_and_recap_hygiene()
    test_memory_gates()
    test_cooldown_and_chorus()
    test_prompt_and_tokens()
    print("all passed")


if __name__ == "__main__":
    main()
