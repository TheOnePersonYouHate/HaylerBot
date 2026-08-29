# HaylerBot

A self-hosted Discord bot that runs an **NPC crew** for naval roleplay aboard a modern U.S. cruiser.

You talk to the watch like a radio net. Address someone by name, rank, or station and they answer in character, under their own name. The bot tracks where people are, what the ship is doing, and what is on the plot — so a fight does not vanish when the chat scrolls.

The point is not a chatbot with hats. It is a **watch bill**: who may speak, who may hear, who may change the ship.

## Why it exists

Tabletop and Discord naval RP fall apart in two places: the GM cannot voice every watchstander, and a language model will happily invent a new air picture, teleport the bosun, or set general quarters because a seaman joked about it.

HaylerBot keeps **voice** in the model and **the world** in code.

- Crew only answer when they can actually hear you (same space or a circuit).
- Course, speed, and general quarters only change if the speaker is a warrant or officer.
- Contacts live on a **plot**, not only in the last 80 lines of chatter.
- Inference prefers a **local** model so play does not depend on a cloud round-trip. A cloud backend is optional fallback when the GPU is busy or offline.

## How it works

```
Discord channel
    -> bot.py     who is speaking, where they are, who can hear
    -> brain.py   one LLM call per addressed NPC (local, then cloud)
    -> webhook    that NPC posts as themselves
    -> disk       ship state, plot, pending actions, ship's log
```

Each reply is a **new, short request**. The model does not keep a 500k-token thread. The bot rebuilds what matters every time: persona, ship, plot, held actions, last stretch of chat, your line.

| Layer | Job |
|---|---|
| `characters.yaml` | Ship, roster, ranks, optional human players |
| `npcs.py` | Addressing, earshot, circuits, movement orders |
| `bot.py` | Discord, routing, webhooks, slash/prefix commands |
| `brain.py` | Prompts and LLM backends |
| `plot.py` | CIC contacts and last facts |
| `ship.py` | Course, speed, alert — crash-safe JSON |

## Play in one minute

```
*In CIC*
Lieutenant Hoover, report.
*three friendly aircraft, bearing 045, IFF friendly*
!plot
```

`*In CIC*` places you. Naming Hoover talks to him. The asterisk line writes the plot. `!plot` shows it.

Full command list: **[COMMANDS.md](COMMANDS.md)**.

| Command | What it does |
|---|---|
| `/plot` or `!plot` | Show the CIC plot |
| `/plot action:clear` or `!plot clear` | Wipe the plot |
| `/status` | Ship, pending waits, plot |
| `/crew` | NPCs and how to address them |
| `/where` | Your space and who is in earshot |
| `/roster` | Humans the crew will take orders from |
| `/recap` | Write this session into the ship's log |

On a host Discord server, an admin may need to enable new slash commands under **Integrations**. `!plot` does not need that.

## Setup

1. Create a Discord application. Enable **Message Content Intent**. Invite the bot with `bot` + `applications.commands` and permission to **Manage Webhooks**.
2. Copy `.env.example` to `.env`. Set `DISCORD_TOKEN` and `RP_CHANNEL_ID` (one or more channel IDs).
3. Optional local brain: [LM Studio](https://lmstudio.ai) on `http://127.0.0.1:1234/v1`.
4. Optional cloud fallback: `XAI_API_KEY` in `.env`.
5. Install and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python bot.py
```

Or `.\run.ps1` / `.\run.bat` on Windows (starts LM Studio if present, then the bot). Portable launchers: [PORTABLE.md](PORTABLE.md). Standalone build: [build/BUILD.md](build/BUILD.md). Always-on host: [deploy/DEPLOY.md](deploy/DEPLOY.md).

Do not commit `.env`. Player Discord IDs belong in your local `characters.yaml` only.

## The world

Default setting is **USS Hayler (CG-126)** — a guided-missile cruiser *converted from a guided-missile destroyer*, not a Ticonderoga. About 12,000 tons full load, 128-cell Mk 41 battery, SPY-6, near-future campaign. The roster, fit, and ranks are all in `characters.yaml`.

Human players are listed under `players:` (Discord user ID and/or username → rank the crew should use). Keep real IDs off public remotes.

## Design rules (short)

- **Code owns the ship.** The model proposes; helm and GQ are refused unless the speaker is warrant+.
- **Earshot is real.** A shout in CIC does not reach the main deck. 1MC / 21MC / a station hail does.
- **Narration is fact.** `*three friendly aircraft, bearing 045*` is what is happening. The plot stores it.
- **Scrollback is not memory.** History is a short window for voice. Plot, pending actions, locations, and the ship's log are what survive.

Deeper internals: **[ARCHITECTURE.md](ARCHITECTURE.md)**.
