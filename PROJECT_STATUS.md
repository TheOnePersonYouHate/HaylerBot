# Naval RP NPC Crew Bot — Project Status / Handoff

> Living handoff doc. Written so a fresh Grok Build session (e.g. on a Mac) can pick
> the project up cold. The repo is cross-platform; only the LM Studio launchers are
> Windows-specific. **Restart the bot after any change to code, `.env`, or `characters.yaml`.**

---

## 1. What it is
A private, self-hosted **Discord bot** that runs an **AI NPC crew** for naval roleplay
aboard **USS Hayler (CG-126)**. You address a crew member by name/rank/station and they
answer in character through their own webhook identity, carry out orders, track the ship's
state, remember the conversation, and keep a ship's log that persists across sessions.

The "brain" is an LLM. Primary is a **local model (LM Studio, gemma-4-31b)** for free/private
inference; **xAI (Grok, `grok-4.3`)** is the cloud backend used as a **fallback** (LM Studio off)
and an **overflow** (GPU busy). The same prompt is sent to whichever backend is chosen — the
model is stateless and everything it needs is assembled into the prompt each call.

## 2. Repository map
| Path | Purpose |
|---|---|
| `bot.py` | Discord wiring, per-channel state, routing, `speak()` (webhooks), slash commands, logging, single-instance lock |
| `brain.py` | LLM calls: persona reply (`npc_respond`), relevance gate (`is_continuation`), session summary (`summarize`); backend routing/fallback/overflow; `SYSTEM_TEMPLATE` |
| `npcs.py` | Loads crew/players/ranks/ship from `characters.yaml`; addressing (`find_all_addressed`, `find_addressed`, `npc_by_display_name`) |
| `ship.py` | `ShipState`; atomic + corruption-tolerant JSON persistence (`ship_state.json`, `chronicle.json`) |
| `characters.yaml` | **The data file** — ship spec, crew roster, human players, rank list. Single source of truth. |
| `config.py` | Settings loaded from `.env` |
| `setup.py` | Interactive Discord setup wizard (Windows-oriented) |
| `run.ps1` / `run.bat` | Windows launcher: starts LM Studio (`lms`), loads the model with `--parallel 4`, runs the bot |
| `start-windows.bat` / `start-mac.command` | **Portable** cross-platform launchers (xAI-only, no LM Studio) — see `PORTABLE.md` |
| `.env` | Secrets/config (token, xAI key, channels) — **git-ignored** |
| `.env.example` / `.env.portable` | Config templates (home setup / portable-test setup) |
| `deploy/` | Always-on hosting kit: `DEPLOY.md`, `Dockerfile`, `naval-rp-bot.service` (systemd), `make_cloud_init.py` |
| `PORTABLE.md` | Flash-drive / cross-platform test build guide |
| `naval-bot.spec`, `build/` | **Standalone build** (no Python needed to run): PyInstaller spec + `build-windows.bat` / `build-mac.command` + `BUILD.md`. Produces a one-file `HaylerBot` (`.exe` on Windows, binary on Mac) |
| `requirements.txt`, `README.md`, `.gitignore` | Deps, docs, ignore rules |
| _generated_ | `ship_state.json`, `chronicle.json`, `bot.log*`, `.venv*/`, `dist/`, `.build-work/` (git-ignored) |

## 3. Stack
- Python 3.12 · `discord.py>=2.4` · `openai>=1.0` · `python-dotenv` · `pyyaml`
- Local LLM: **LM Studio** (OpenAI-compatible at `127.0.0.1:1234`), gemma-4-31b, loaded with **4 parallel slots**
- Cloud LLM: **xAI** (`https://api.x.ai/v1`), `grok-4.3`, OpenAI-compatible, supports `json_schema` structured outputs
- Dev machine: user's PC (RTX 5090, 32 GB). Code is pure-Python and runs on macOS/Linux too.

## 4. How to run
**Start on Windows — step by step:**

1. **Install Python 3** if you don't have it. Download it from <https://www.python.org/downloads/>, run the installer, and on the first screen **tick "Add Python to PATH"**. To check it worked, open the Start menu, type `PowerShell`, open it, and run `python --version`.

2. **Open a terminal inside the project folder.** In File Explorer, open the `naval-rp-bot` folder. Click the address bar at the top, type `powershell`, and press Enter — a terminal opens already pointed at that folder.

3. **Create the virtual environment** (first time only):
   ```powershell
   python -m venv .venv
   ```

4. **Install the dependencies** (first time, and after any `requirements.txt` change):
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

5. **Create your `.env`** (first time). Reuse an existing one, or start from the template:
   ```powershell
   Copy-Item .env.portable .env
   ```
   Then open `.env` in Notepad and fill in `DISCORD_TOKEN`, `RP_CHANNEL_ID`, and `XAI_API_KEY`.
   - **No LM Studio / no GPU?** Leave `LLM_BASE_URL=` empty → xAI-only (needs internet + the key).
   - **Using LM Studio for local inference?** Start its server and load a model, then set `LLM_BASE_URL=http://127.0.0.1:1234/v1` and `LLM_MODEL=<model>`. (On this PC, `run.ps1` does all of that automatically — see the shortcuts below.)

6. **Start the bot:**
   ```powershell
   .\.venv\Scripts\python.exe bot.py
   ```
   Watch for `Logged in as Hayler Bot#...`, then address a crew member in Discord to test.

7. **Stop the bot:** press `Ctrl+C` in that window (or close it).

**One-click shortcuts** (once `.env` exists — no terminal needed):
- **`start-windows.bat`** — double-click for the simplest xAI-only run (no LM Studio; it does the venv + install + run itself).
- **`run.bat`** (or `run.ps1`) — the full home-PC launcher: starts LM Studio, loads gemma-4-31b with 4 parallel slots, then the bot. Use this for local inference. Keep the window open; closing it stops the bot.

**Start on Mac — step by step:**

1. **Install Python 3** if you don't have it. Check with `python3 --version`; if it's missing, get it from <https://www.python.org/downloads/> or run `brew install python`.

2. **Open Terminal and go to the project folder:**
   ```bash
   cd ~/path/to/naval-rp-bot
   ```

3. **Create the virtual environment** (first time only):
   ```bash
   python3 -m venv .venv
   ```

4. **Install the dependencies** (first time, and after any `requirements.txt` change):
   ```bash
   .venv/bin/pip install -r requirements.txt
   ```

5. **Create your `.env`** (first time). Reuse an existing one, or start from the template:
   ```bash
   cp .env.portable .env
   ```
   Then edit `.env` and fill in `DISCORD_TOKEN`, `RP_CHANNEL_ID`, and `XAI_API_KEY`.
   - **No LM Studio on this Mac?** Leave `LLM_BASE_URL=` empty → xAI-only (needs internet + the key).
   - **Want local inference?** Install LM Studio (Apple Silicon), load a model, start its server, then set `LLM_BASE_URL=http://127.0.0.1:1234/v1` and `LLM_MODEL=<model>`.

6. **Start the bot:**
   ```bash
   .venv/bin/python bot.py
   ```
   Watch for `Logged in as Hayler Bot#...`, then address a crew member in Discord to test.

7. **Stop the bot:** press `Ctrl+C` in that Terminal (or close the window).

After the first time, starting again is just steps 2 + 6. Or double-click **`start-mac.command`**, which does the venv + install + run for you (see `PORTABLE.md`).

**Portable (USB stick, any computer, xAI-only):** copy `.env.portable`→`.env`, fill it in, then
double-click `start-windows.bat` or `start-mac.command`. Full steps in `PORTABLE.md`.

**xAI-only mode (no LM Studio / no GPU):** set `LLM_BASE_URL=` (empty) in `.env`. `brain._local`
becomes `None` and every reply goes to Grok. This is what the portable + cloud builds use.

## 5. Current configuration (non-secret)
- **Bot:** Hayler Bot#6018 — application/client id `1520984497993023549`
- **Servers:** "Misery and Self Loathing…" (`1366153654725513246`, personal) · "Hayler Naval Corps (HNC)" (`1279993042186666025`, friend's)
- **Listening channels (`RP_CHANNEL_ID`):** `1366153657049153540` (personal) · `1519769056801067068` (HNC `#naval-laboratory`)
- **Player:** Lieutenant Commander, Discord id `998033426676449391` (`theonepersonyouhate`)
- **Ship:** USS Hayler (CG-126), guided-missile cruiser — full spec in `characters.yaml`
- **Crew (5):** Helmsman Cole, Navigator Vance, Bosun Hartley, Lookout Pike, Engineer Doyle
- **Key `.env` settings now:** `CONTINUITY_SECONDS=60` · `LOCAL_MAX_INFLIGHT=4` · `XAI_MODEL=grok-4.3` · `XAI_API_KEY` **set** (active; account has large credit balance) · `STRICT_CHANNEL_ID=` (empty)
- **Secrets** (`DISCORD_TOKEN`, `XAI_API_KEY`) live only in `.env` (git-ignored). Not in this doc.

## 6. Features (complete)
- **Addressing:** by name (matches anywhere), or role/station word as a **vocative** (start of message or next to a comma), or any alias inside a `*roleplay action*`. Narration mentions ("the navigator looked nervous") are ignored.
- **Multi-NPC in one message:** naming several ("Cole and Vance, report") engages them all; they answer in the order named.
- **Reply-to-talk:** replying (Discord reply) to a crew member's message routes straight to them — no name, no timer.
- **Per-person continuity:** each speaker has their own active-NPC thread, so two people can talk to different crew at once without collisions. Un-named follow-ups continue *your own* thread for `CONTINUITY_SECONDS` (60s), gated by a relevance check.
- **Identity:** each NPC posts via one shared webhook, with its own name (avatar optional via `avatar_url`). One webhook → unlimited NPC identities (sidesteps Discord's 15-webhook/channel cap).
- **Structured replies:** JSON `{say, followup, location, state_update}` via `response_format` json_schema.
- **Two-step orders:** acknowledge → carry out → report complete (~6 s later).
- **Ship state:** heading/speed/alert/notes tracked and persisted; `/status` shows it + last backend used.
- **Personality & rank:** distinct voices from `characters.yaml`; you're addressed by your Discord rank role.
- **Spatial awareness:** per-channel crew locations, kept consistent with the scene.
- **Ship knowledge:** crew know the full CG-126 spec (weapons, sensors, propulsion, layout).
- **Slash commands:** `/status`, `/crew`, `/roster`, `/recap`.
- **Multi-server, per-channel isolation:** separate ship/crew-locations/history per channel (crew roster is global).
- **Out-of-context control:** `(parens)` / `//` / `[brackets]` / `OOC:` prefixes are ignored; smart relevance gate; disengage timeout; optional per-channel strict mode.
- **Memory:** last 60 messages per channel; **cross-session** via `/recap` → `chronicle.json` → loaded next session as "story so far."
- **Backend routing:** local-first, overflow to xAI when the GPU is busy, fall back to xAI when LM Studio is down; JSON salvage for truncated local replies.
- **Robustness:** atomic state writes, corruption-tolerant load, webhook recovery + plain-message fallback, per-NPC error isolation, rotating `bot.log`, single-instance lock.

## 7. Changelog — latest work session
1. **Per-person continuity** — `ChannelState.active` is now `{author_id: (npc, expires_at)}`; `route()` keys continuity by speaker.
2. **xAI fallback validated + load overflow** — added `LOCAL_MAX_INFLIGHT` and an in-flight counter (`brain._local_inflight`); when ≥N local requests are in flight, new replies overflow to xAI. Live-validated the key + `grok-4.3` + structured output. **Fixed a real bug:** grok rejects `presence_penalty`/`frequency_penalty`, so `_complete(..., penalties=False)` for xAI. Updated `XAI_MODEL` `grok-4-latest`→`grok-4.3`.
3. **Multi-NPC** — `find_all_addressed()` returns all named crew; `route()` returns a list; `on_message` gathers replies concurrently and posts in order.
4. **Parallel slots** — LM Studio loaded with `--parallel 4` (run.ps1); `LOCAL_MAX_INFLIGHT=4` aligned to it. Benchmarked: ~25 tok/s aggregate, latency scales ~linearly with concurrency (prompt processing dominates short replies).
5. **Smoothness** — `CONTINUITY_SECONDS` 8→60; added **reply-to-talk** (`resolve_reply_target`, `npc_by_display_name`).
6. **Robustness fixes** — (1) atomic writes + safe load in `ship.py`; (2) `speak()` webhook recovery + plain fallback + per-NPC isolation; (3) rotating `bot.log`; (4) single-instance lock (`127.0.0.1:49219`).
7. **Deploy kit** (`deploy/`) — VPS/systemd/Docker + a cloud-init generator. Cloud hosting explored (Oracle free tier) but **paused** (complexity + not wanting to pay). Kept for later.
8. **Portable kit** — cross-platform USB test build (`start-windows.bat`, `start-mac.command`, `.env.portable`, `PORTABLE.md`).

## 8. How it works (key technical notes)
- **Stateless brain.** The model knows nothing on its own. `brain.SYSTEM_TEMPLATE` is filled each call with: the NPC persona (from `characters.yaml`), the ship spec, who's speaking (rank), the NPC's location, current ship state, the chronicle, and recent history — plus the user's message and a JSON-schema instruction. The **same** prompt goes to local or xAI; only the penalty params differ.
- **Backend routing (`brain.npc_respond`).** `busy = xai_available and _local_inflight >= LOCAL_MAX_INFLIGHT`. If local is configured and not busy → try LM Studio (increments the in-flight counter); on `APIConnectionError`/`APITimeoutError` fall through to xAI. If busy or local is `None` → go straight to xAI. `LAST_BACKEND` records the choice (shown by `/status`). The gate and summary also fall over to xAI but do **not** overflow.
- **Addressing/continuity (`bot.route`).** Explicit names/replies always engage (bypass the gate); un-named messages continue the speaker's own active NPC only if `is_continuation` says yes and within the window. Strict channels skip continuity.
- **Persistence (`ship.py`).** `_atomic_write` (temp file + fsync + `os.replace`) so a mid-write kill can't corrupt state; `_load_json` moves a corrupt file to `*.corrupt` and returns empty instead of crashing on boot.
- **Concurrency.** On one GPU, ~4 concurrent short replies is the comfortable ceiling; beyond that they overflow to xAI (separate hardware) or queue. Only *concurrent* responders matter — total roster size barely affects performance.

## 9. Tuning guide (most changes need no code)
- **Crew voices / add-remove crew / ship spec / aliases / ranks / players:** edit `characters.yaml`, then restart.
- **Conversation window:** `CONTINUITY_SECONDS` in `.env`.
- **When to overflow to Grok:** `LOCAL_MAX_INFLIGHT` (keep ≤ LM Studio's `--parallel`).
- **Explicit-address-only channels:** `STRICT_CHANNEL_ID` (comma-separated ids).
- **Global tone / behavior:** edit `SYSTEM_TEMPLATE` in `brain.py`.

## 10. Known issues / risks (remaining)
- **60 s window ⇒ more relevance-gate calls** (a call before many un-named follow-ups). Tradeoff for smoothness; tune the window if latency bites.
- **Alias false-positives** — common words are names/aliases (`watch`, `chief`, `nav`, `wheel`); the vocative rule mitigates but isn't airtight.
- **Permission gaps degrade quietly** — missing "Manage Webhooks" now falls back to plain messages; missing "Read Message History" disables reply-to-talk silently.
- **`characters.yaml` typos** (missing `key`/`name`) crash startup with a `KeyError` (no friendly message).
- **No auto-recap** — chronicle only updates on manual `/recap`; a crash loses unsaved narrative.
- **Voice shift on failover** — gemma↔grok tone differs mid-scene if LM Studio drops.
- **No test suite in-repo** — tests were written ad-hoc as temp scripts and deleted; regressions aren't guarded.

## 11. Open items / next ideas
- **Continuity of in-progress actions** (pending-action/state per NPC) — still the top RP gap.
- **Soundboard** — feasible (`VoiceChannel.send_sound`) but needs PyNaCl + join-voice + a rebuild.
- **NPC avatars** (`avatar_url` per crew; files exist in `avatars/` but need public URLs).
- **Auto-recap** (durability + convenience).
- **Prompt-prefix optimization** — put the shared ship-knowledge block *first* so LM Studio can prefix-cache it.
- **Cloud always-on** (kit ready in `deploy/`; paused).
- Copy this Mac `characters.yaml` back to the Windows box so both machines match.

See `CONTINUE_HERE.md` for the 2026-08-11 Mac/Windows-parity status (earshot, circuits, Irinchev removed).

## 12. Working on this with Grok Build (Mac)
- Code is cross-platform — verified no Windows-only calls in the runtime modules. `run.ps1`/`run.bat`/`setup.py` are the only Windows-oriented bits (LM Studio via the `lms` CLI). On Mac, run via a venv (§4) or the portable launcher; LM Studio also runs on Apple Silicon if you want local inference, otherwise use xAI-only.
- **Testing pattern used here:** small offline scripts that stub `brain.is_continuation` and fake Discord objects (message/channel/webhook), run with the venv Python, then delete. Good for exercising `route()`, addressing, `speak()`, and persistence without a live bot.
- **Single-instance lock:** only one bot per machine (and one per Discord token across machines). Use a **separate test bot token** when running a second copy for testing.
- **Restart rule:** config/`characters.yaml`/code changes require a bot restart to take effect.
- Runtime logs are in `bot.log` (rotating); ship state in `ship_state.json`; cross-session memory in `chronicle.json`.
- **Standalone (no-install) build:** see `build/BUILD.md`. The Windows `.exe` is prebuilt in `dist/`. Build the **Mac** binary on the Mac: `bash build/build-mac.command` (BUILD.md covers the Gatekeeper/quarantine/codesign finish steps). `config.py` resolves `.env` + data files next to the executable, so the bundle works wherever it's launched.
