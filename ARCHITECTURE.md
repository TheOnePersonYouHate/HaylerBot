# Architecture

HaylerBot is a Discord client that turns one channel into a ship’s watch. This page is how the pieces fit — not a session log.

## One call, one voice

The model is stateless. Every NPC reply is a fresh chat completion. `brain.py` builds a system prompt from:

1. Shared ship identity, then the Navy reference (rates, GQ, circuits). These bytes are the same on every call, so a prefix cache can reuse them
2. That NPC’s persona (and, for the bosun, a 1MC phrase book *only* when the order is a pass-the-word job)
3. A SWO / threat brick — **only** for nav, helm, lookout, and the CIC officer
4. Speaker rank and whether they may order the ship
5. That NPC’s location and any **pending** action (knocking, en route, waiting)
6. Current ship state and the **plot**
7. Ship’s log (chronicle) from earlier sessions
8. Episodic **pins** (at most 12 short facts for this channel)
9. The last ~80 channel lines
10. The line just typed

A typical call is a few thousand tokens. The local server may reserve a larger window; unused reserve is not extra memory of the scene.

Local LM Studio is tried first. If it is down, or already handling several replies, the same prompt goes to the optional cloud backend.

## Routing

`bot.py` decides *who* speaks before any model runs.

| Signal | Effect |
|---|---|
| Vocative / alias (`Hoover, report.`) | That NPC is called |
| Group address (`bridge team`) | Everyone in that group who can hear |
| Reply-to an NPC message | Continues that NPC, if earshot still holds |
| Continuity window | Last NPC you were talking to, if the line is still for them |
| Pure `*narration*` | No reply — the scene moved, nobody was hailed |
| OOC (`(…)`, `{…}`, `//`) | Ignored |
| `out` / hang-up | Thread ends |

`npcs.py` applies **earshot**: same canonical space, or a circuit (1MC, 21MC, JV, station hail). Crew-to-crew uses the same rule. A face-to-face name in another compartment does not pull an answer.

Player space comes from narration (`*In CIC*`, `*heads to engineering*`) or, on first contact, from the person they called.

## What code refuses

The model may emit JSON (`say`, `followup`, `location`, `pending`, `state_update`). The bot applies it with checks:

- **Helm / alert** — stripped unless the speaker is warrant or above. Notes still apply.
- **Location** — ignored unless this turn is a movement order, a follow-up arrival, or the same space (no teleport on banter). `to CIC` counts as movement.
- **Pending** — stored per NPC, persisted, injected every call. Arrival stays at the door until `Enter` / `as you were` / `belay`.
- **Plot** — player contact language and *officer* notes write tracks. Junior-enlisted model notes cannot invent ghosts.

## Persistence

Each RP channel has its own world. Writes are atomic (temp file, then replace). Corrupt JSON is quarantined instead of crashing startup.

| File | Contents |
|---|---|
| `ship_state.json` | Course, speed, alert, freeform notes |
| `plot.json` | Contacts and last facts |
| `pending.json` | Per-NPC held actions |
| `locations.json` | Where each NPC is |
| `player_locations.json` | Where each player is (same durability as NPC locations) |
| `chronicle.json` | Ship’s log from `/recap` and idle/shutdown recap |
| `pins.json` | Episodic pins for the channel (≤12, ≤200 characters) |
| `scene.json` | Last ~32 in-world lines, written on idle recap and shutdown, restored into RAM on load |

`/plot clear`, pin edits, and chronicle clears require **Manage Messages** or an officer rank (warrant and above). `/recap` and `/pin extract` share a cooldown so those LLM calls cannot be spammed. Recap and pin extract drop OOC, commands, and meta such as “plot cleared”.

`.env` holds tokens and channel IDs. It is not in git.

## Why not a bigger context window

Filling the prompt with more old chatter buries the last line of the scene. That is how you get loops and a wrong contact picture. Long memory is the **plot**, **pending**, **locations** (crew and players), **chronicle**, and **pins** — small, structured, every call. The scene seed is only a short voice warm-start, not a second transcript.

On a VPS where xAI is the only brain, that cap is also the bill. Ship identity and the Navy reference sit at the front of the prompt so a prefix cache can reuse them. Normal replies ask for about 400 tokens; 1MC and movement follow-ups get more; the continuity classifier stays tiny. A group hail (“team”, “all hands”) is one chorus reply from the senior person in the space, not a full completion per body. `MAX_CREW_CHAIN` still caps crew answering crew.

## Tests

From the repo root, with a dummy token in the environment (the suite sets one):

```
python tests/test_scene_state.py
python tests/test_plot.py
python tests/test_memory.py
```

These cover addressing, earshot, authority, pending, movement, the 1MC kit, the plot parser, pins, player locations, the scene seed, and the prompt prefix order. They do not need Discord or a GPU.
