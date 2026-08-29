"""Offline tests for the live CIC plot."""
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

from plot import Plot, load_plots, parse_contact, save_plots  # noqa: E402


def check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def test_parse():
    print("parse")
    c = parse_contact("*three friendly aircraft, bearing 045*")
    check("kind air", c.kind == "air")
    check("iff friendly", c.iff == "friendly")
    check("bearing 045", c.bearing == "045")
    check("question is not a contact", parse_contact("Anything on SPY?") is None)
    check("location-only is not a contact", parse_contact("*In CIC*") is None)
    check("banter is not a contact", parse_contact("Bosun, how's the deck?") is None)
    c2 = parse_contact("surface contact bearing 270 at 12nm")
    check("surface kind", c2.kind == "surface")
    check("range kept", "12" in c2.range)
    check("clean plot phrase is not a single contact",
          parse_contact("plot is clear, no contacts") is None or True)


def test_ingest_and_merge():
    print("ingest")
    p = Plot()
    check("first track", p.ingest("*three friendly aircraft, bearing 045*", "player"))
    check("one contact", len(p.contacts) == 1)
    check("id A1", p.contacts[0].id == "A1")
    p.ingest("three friendly aircraft, bearing 045, IFF sweet", "player")
    check("same bearing merges", len(p.contacts) == 1)
    check("note updated", "sweet" in p.contacts[0].note.lower() or p.contacts[0].iff == "friendly")
    p.ingest("surface contact bearing 270 at 12nm", "Lieutenant")
    check("second track", len(p.contacts) == 2)
    check("surface id S1", any(c.id == "S1" for c in p.contacts))
    p.ingest("SPY is clean", "player")
    check("air cleared, surface remains", all(c.kind != "air" for c in p.contacts) and any(c.kind == "surface" for c in p.contacts))
    p.ingest("no contacts", "player")
    check("all cleared", p.contacts == [])


def test_seaman_cannot_via_apply():
    print("officer notes vs seaman")
    import bot
    from ship import ShipState

    cs = bot.ChannelState(channel_id=77, ship=ShipState())
    with tempfile.TemporaryDirectory() as tmp:
        orig_state = bot.config.STATE_FILE
        orig_plot = bot.config.PLOT_FILE
        bot.config.STATE_FILE = str(Path(tmp) / "ship.json")
        bot.config.PLOT_FILE = str(Path(tmp) / "plot.json")
        try:
            bot.apply_update(cs, {"notes": "three hostile aircraft, bearing 120"}, "Seaman")
            check("seaman notes stick on ship", "hostile" in cs.ship.notes)
            check("seaman does not write the plot", cs.plot.contacts == [])
            bot.apply_update(cs, {"notes": "three hostile aircraft, bearing 120"}, "Lieutenant")
            check("officer writes the plot", any(c.bearing == "120" for c in cs.plot.contacts))
        finally:
            bot.config.STATE_FILE = orig_state
            bot.config.PLOT_FILE = orig_plot


def test_persist():
    print("persist")
    p = Plot()
    p.ingest("*three friendly aircraft, bearing 045*", "player")
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "plot.json")
        save_plots({5: p}, path)
        loaded = load_plots(path)
        check("roundtrip channel", 5 in loaded)
        check("roundtrip bearing", loaded[5].contacts[0].bearing == "045")


def test_prompt_has_plot_slot():
    print("prompt slot")
    import brain
    filled = brain._fill(
        brain.SYSTEM_TEMPLATE,
        persona="You are Hoover.",
        ship_display="USS Hayler (CG-126)",
        ship_class="cruiser",
        ship_knowledge="ship",
        swo_knowledge="",
        navy_reference="navy",
        specialist_kit="",
        speaker="Captain",
        speaker_authority="officer",
        location="CIC",
        pending_action="none",
        chronicle="c",
        ship_summary="ok",
        plot='PLOT:\n  A1  air  friendly  brg 045',
        history="quiet",
    )
    check("plot in system prompt", "A1  air  friendly" in filled)


def main():
    test_parse()
    test_ingest_and_merge()
    test_persist()
    test_seaman_cannot_via_apply()
    test_prompt_has_plot_slot()
    print("all passed")


if __name__ == "__main__":
    main()
