"""Offline regress for scene-state fixes: pending actions, earshot, authority, aliases.

Run from the repo root:

    python tests/test_scene_state.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("RP_CHANNEL_ID", "1")
os.environ.setdefault("LLM_BASE_URL", "")
os.environ.setdefault("XAI_API_KEY", "")

from npcs import (  # noqa: E402
    CREW, SHIP, announcement_followup, can_order_ship, can_reach,
    find_all_addressed, find_called, is_announcement_order, is_movement_order,
    kit_for, swo_for,
)
from ship import ShipState, load_maps, save_maps  # noqa: E402


def _npc(key):
    return next(n for n in CREW if n.key == key)


def check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def test_aliases():
    print("aliases")
    check("chief does not address Doyle",
          all(n.key != "engineer" for n in find_all_addressed("Chief, report.")))
    check("watch does not address Pike",
          all(n.key != "lookout" for n in find_all_addressed("The watch is set.")))
    check("gunner does not address Flasterstein",
          all(n.key != "flasterstein" for n in find_called("Gunner, check the mount.")))
    check("chief mctane still reaches McTane",
          any(n.key == "mctane" for n in find_called("Chief McTane, come about.")))
    check("pike still reaches Pike",
          any(n.key == "lookout" for n in find_called("Pike, report.")))
    check("doyle still reaches Doyle",
          any(n.key == "engineer" for n in find_called("Doyle, how's the plant?")))


def test_authority():
    print("authority")
    check("seaman cannot order ship", not can_order_ship("Seaman"))
    check("PO1 cannot order ship", not can_order_ship("Petty Officer 1st Class"))
    check("chief cannot order ship", not can_order_ship("Chief Petty Officer"))
    check("unknown cannot order ship", not can_order_ship(""))
    check("warrant can order ship", can_order_ship("Warrant Officer"))
    check("ensign can order ship", can_order_ship("Ensign"))
    check("lt can order ship", can_order_ship("Lieutenant"))
    check("captain can order ship", can_order_ship("Captain"))


def test_apply_update():
    print("apply_update")
    import bot

    cs = bot.ChannelState(channel_id=99, ship=ShipState(heading=90, speed=10, alert="normal"))
    with tempfile.TemporaryDirectory() as tmp:
        orig = bot.config.STATE_FILE
        bot.config.STATE_FILE = str(Path(tmp) / "ship_state.json")
        try:
            bot.apply_update(cs, {"heading": 180, "speed": 25, "alert": "general quarters"}, "Seaman")
            check("seaman cannot set GQ", cs.ship.alert == "normal")
            check("seaman cannot change heading", cs.ship.heading == 90)
            check("seaman cannot change speed", cs.ship.speed == 10)

            bot.apply_update(cs, {"notes": "three friendlies, bearing 045"}, "Seaman")
            check("seaman notes still apply", "friendlies" in cs.ship.notes)

            bot.apply_update(cs, {"heading": 270, "speed": 20, "alert": "general quarters"}, "Lieutenant")
            check("officer can set heading", cs.ship.heading == 270)
            check("officer can set speed", cs.ship.speed == 20)
            check("officer can set GQ", cs.ship.alert == "general quarters")
        finally:
            bot.config.STATE_FILE = orig


def test_earshot():
    print("earshot")
    cic = "the Combat Information Center (CIC)"
    deck = "the main deck"
    check("same space hears", can_reach(cic, "CIC plot table", "Bosun! Get in here!"))
    check("cross-space shout is silent",
          not can_reach(cic, deck, "Bosun! Get in here!"))
    check("21MC reaches across spaces",
          can_reach(cic, deck, "*keys the 21MC* Bosun, CIC, get up here."))
    check("1MC reaches across spaces",
          can_reach(cic, deck, "Now hear this. All hands, Bosun to the bridge."))
    check("station hail counts as circuit",
          can_reach(cic, "the helm on the bridge", "Bridge, CIC."))


def test_crew_chain_filter():
    print("crew-chain filter")
    import bot

    hoover = _npc("hoover")
    hartley = _npc("bosun")
    cs = bot.ChannelState(channel_id=7, ship=ShipState())
    cs.locations[hoover.key] = hoover.station
    cs.locations[hartley.key] = hartley.station
    check("Hoover in CIC cannot hail Hartley on the main deck",
          not bot._crew_hears(cs, hoover, hartley, "Bosun! Get in here!"))
    check("same hail on 21MC does reach",
          bot._crew_hears(cs, hoover, hartley, "*keys the 21MC* Bosun, CIC."))


def test_pending_roundtrip():
    print("pending persist")
    import bot

    cs = bot.ChannelState(channel_id=42, ship=ShipState())
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "pending.json")
        orig = bot.config.PENDING_FILE
        bot.config.PENDING_FILE = path
        try:
            bot.set_pending(cs, "bosun", "waiting at captain's cabin, knocked, not admitted")
            check("set in memory", "cabin" in cs.pending["bosun"])
            loaded = load_maps(path)
            check("persisted to disk", "cabin" in loaded[42]["bosun"])
            bot.set_pending(cs, "bosun", "")
            check("cleared from memory", "bosun" not in cs.pending)
            loaded = load_maps(path)
            check("cleared from disk", 42 not in loaded)
        finally:
            bot.config.PENDING_FILE = orig

    check("enter is a release", bot.is_release("Enter."))
    check("come in is a release", bot.is_release("*opens the door* Come in."))
    check("as you were is a release", bot.is_release("As you were, Bosun."))
    check("report is not a release", not bot.is_release("Bosun, report to the bridge."))
    check("heading out is not a release", not bot.is_release("Heading out."))


def test_pending_from_reply():
    print("pending from reply")
    import bot

    npc = _npc("bosun")
    cs = bot.ChannelState(channel_id=8, ship=ShipState())
    with tempfile.TemporaryDirectory() as tmp:
        bot.config.PENDING_FILE = str(Path(tmp) / "pending.json")
        bot._apply_pending(cs, npc, {
            "followup": "*arrives at the cabin and knocks*",
            "location": "the captain's cabin",
        })
        check("followup becomes en-route pending",
              cs.pending[npc.key].startswith("en route"))
        bot._apply_pending(cs, npc, {"pending": "waiting at captain's cabin, knocked"})
        check("explicit pending wins", "knocked" in cs.pending[npc.key])
        bot._apply_pending(cs, npc, {"pending": ""}, player_text="Enter.")
        check("empty pending clears", npc.key not in cs.pending)
        bot.set_pending(cs, npc.key, "waiting")
        bot._apply_pending(cs, npc, {}, player_text="Enter.")
        check("release without pending field clears", npc.key not in cs.pending)


def test_location_persist():
    print("location persist")
    import bot

    cs = bot.ChannelState(channel_id=11, ship=ShipState())
    with tempfile.TemporaryDirectory() as tmp:
        orig = bot.config.LOCATIONS_FILE
        bot.config.LOCATIONS_FILE = str(Path(tmp) / "locations.json")
        try:
            bot.set_location(cs, "bosun", "the captain's cabin")
            check("location in memory", cs.locations["bosun"] == "the captain's cabin")
            loaded = load_maps(bot.config.LOCATIONS_FILE)
            check("location on disk", loaded[11]["bosun"] == "the captain's cabin")
        finally:
            bot.config.LOCATIONS_FILE = orig


def test_hartley_kit():
    print("hartley 1MC kit")
    hartley = _npc("bosun")
    vance = _npc("navigator")
    check("persona is just voice (no GQ script)",
          "Set Condition Zebra" not in hartley.persona)
    check("kit still has the verbatim GQ call",
          "Set Condition Zebra" in hartley.kit)
    check("GQ order is an announcement",
          is_announcement_order("Bosun, sound general quarters."))
    check("1MC pass-the-word is an announcement",
          is_announcement_order("Bosun, pass the word: now hear this, sweepers."))
    check("deck chatter is not an announcement",
          not is_announcement_order("Bosun, how's the deck looking?"))
    check("report-to is not an announcement",
          not is_announcement_order("Bosun, report to the captain's cabin."))
    check("kit attaches on GQ",
          "Set Condition Zebra" in kit_for(hartley, "Bosun, sound general quarters."))
    check("kit stays off on chatter",
          kit_for(hartley, "Bosun, how's the deck looking?") == "")
    check("other crew have no kit",
          kit_for(vance, "Navigator, sound general quarters.") == "")
    import brain
    attached = brain._kit_block(hartley, "Hartley, make colors.")
    silent = brain._kit_block(hartley, "Hartley, got a minute?")
    check("prompt kit on colors", "Attention to colors" in attached)
    check("prompt kit off on banter", silent == "")
    canned = announcement_followup("Bosun, sound general quarters, set condition zebra")
    check("GQ followup is the 1MC call", "General quarters, general quarters" in canned)
    check("GQ followup is not a drill unless said", "not a drill" in canned.lower())


def test_teleports():
    print("teleports")
    import bot

    hartley = _npc("bosun")
    cs = bot.ChannelState(channel_id=3, ship=ShipState())
    cs.locations[hartley.key] = hartley.station
    check("report-to is a movement order",
          is_movement_order("Bosun, report to the captain's cabin."))
    check("head-to CIC is a movement order",
          is_movement_order("Hartley, head to CIC."))
    check("to-CIC is a movement order",
          is_movement_order("*In CIC, over 1MC* Bosun Hartley, to CIC"))
    check("come-about is not a movement order",
          not is_movement_order("McTane, come about to course 090."))
    check("banter is not a movement order",
          not is_movement_order("Bosun, how's the deck looking?"))
    check("movement order may change location",
          bot.allows_location_change(cs, hartley, "the captain's cabin",
                                     "Bosun, report to the captain."))
    check("banter may not teleport",
          not bot.allows_location_change(cs, hartley, "the mess decks",
                                         "Bosun, how's the deck looking?"))
    check("same-space restatement is allowed",
          bot.allows_location_change(cs, hartley, "the main deck",
                                     "Bosun, how's the deck looking?"))
    cs.pending[hartley.key] = "en route to the captain's cabin"
    check("en-route arrival may land",
          bot.allows_location_change(cs, hartley, "the captain's cabin",
                                     "anything"))
    cs.pending.pop(hartley.key, None)
    check("followup beat may move even without a parsed verb",
          bot.allows_location_change(
              cs, hartley, "CIC", "Hartley, with me.",
              {"followup": "*reaches CIC and reports in*", "location": "CIC"},
          ))


def test_prompt_shape():
    print("prompt shape")
    import bot
    import brain

    check("history window is 60", bot.HISTORY_LIMIT == 60)
    check("shared knowledge dropped the SWO encyclopedia",
          "Type 003 Fujian" not in SHIP["knowledge"])
    check("SWO brick still exists", "Type 003 Fujian" in SHIP["swo"])
    check("Vance (nav) gets SWO", "Type 003" in swo_for(_npc("navigator")))
    check("Hoover gets SWO", "Type 003" in swo_for(_npc("hoover")))
    check("Hartley does not get SWO", swo_for(_npc("bosun")) == "")
    check("Doyle does not get SWO", swo_for(_npc("engineer")) == "")
    check("navy reference dropped the lecture tail",
          "1775" not in brain.NAVY_REFERENCE and "1110 Surface" not in brain.NAVY_REFERENCE)
    check("navy reference kept circuits", "21MC" in brain.NAVY_REFERENCE)
    filled = brain._fill(
        brain.SYSTEM_TEMPLATE,
        persona="You are Hartley.",
        ship_display="USS Hayler (CG-126)",
        ship_class="cruiser",
        ship_knowledge="ship",
        swo_knowledge="",
        navy_reference="navy",
        specialist_kit="",
        speaker="Captain {Santos}",
        speaker_authority="officer",
        location="the {bridge}",
        pending_action="none",
        chronicle="story {so far}",
        ship_summary="ok",
        plot="PLOT: none",
        history='Hartley: "set {condition} Zebra"',
    )
    check("braces in history do not KeyError", "set (condition) Zebra" in filled)
    check("speaker braces sanitized", "Captain (Santos)" in filled)


def main():
    test_aliases()
    test_authority()
    test_earshot()
    test_apply_update()
    test_crew_chain_filter()
    test_pending_roundtrip()
    test_pending_from_reply()
    test_location_persist()
    test_hartley_kit()
    test_teleports()
    test_prompt_shape()
    print("all passed")


if __name__ == "__main__":
    main()
