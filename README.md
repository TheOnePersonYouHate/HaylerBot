# Naval RP NPC Crew Bot

A private, single-server Discord bot that runs an AI **NPC crew** for naval
roleplay. Address a crew member by name and they answer in character through
their own webhook identity. Orders that change the ship (course, speed, alert)
update a shared **ship state** the whole crew reasons from.

The "brain" is a **local LLM via [LM Studio](https://lmstudio.ai)** (its
OpenAI-compatible server) — no real API key, no per-token cost, nothing leaves
your machine.

## How it works

```
Discord  <->  bot.py (this process)  <->  LM Studio (127.0.0.1:1234/v1)
                 |
                 +-- webhook -> each NPC speaks with its own name/avatar
                 +-- ship_state.json (shared world state)
```

- **Hear** — the bot reads messages in one RP channel (Message Content intent).
- **Think** — `brain.py` asks the model for JSON: `{ "say": ..., "state_update": ... }`.
- **Speak** — `speak()` posts the reply via a webhook as that crew member.
- **Remember** — recent chatter (rolling) + persistent `ship_state.json`.

Example: you type `Helmsman, come right to course 240.` ->
**Helmsman Cole:** "Aye, sir. Right standard rudder, coming to course 240." ->
the ship's heading becomes 240, and a moment later he reports *steady on course*.

## Setup

> **Fast path:** do step 1 to get a bot token, then run
> `.\.venv\Scripts\python.exe setup.py`. The wizard validates the token, prints
> the invite URL, finds your server + channel IDs, and writes `.env` for you —
> automating steps 2-5. The manual steps below are the fallback.

### 1. Create the Discord app + bot
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) -> **New Application**.
2. **Bot** tab -> **Reset Token** -> copy it (this is `DISCORD_TOKEN`).
3. Still on the **Bot** tab -> enable **Message Content Intent** under *Privileged Gateway Intents*.

### 2. Invite the bot to your server
Use this URL (replace `CLIENT_ID` with your app's Application ID):

```
https://discord.com/api/oauth2/authorize?client_id=CLIENT_ID&scope=bot+applications.commands&permissions=536939520
```

`536939520` = View Channel + Send Messages + Read Message History + **Manage Webhooks**
(Manage Webhooks is required so the crew can post under their own names).

### 3. Get the IDs
Enable **Developer Mode** (Discord Settings -> Advanced), then right-click your
server icon and the RP channel to copy their IDs.

### 4. Start the local LLM (LM Studio)
1. Load a model — `google/gemma-4-31b` is a great fit on a 32 GB GPU:
   ```powershell
   lms load google/gemma-4-31b --gpu max
   ```
2. Start the OpenAI-compatible server (or use the app's **Developer** tab):
   ```powershell
   lms server start
   ```
   It listens on `http://127.0.0.1:1234/v1`. No API key needed — it's local.

### 5. Configure the bot
```powershell
copy .env.example .env
# then edit .env and fill in DISCORD_TOKEN, GUILD_ID, RP_CHANNEL_ID
```

### 6. Install + run
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python bot.py
```

## One-command start

Run **`.\run.ps1`** (or double-click **`run.bat`**) — that's the whole thing.
The first run bootstraps; every run after just starts:

1. Creates the virtual env + installs dependencies (first run only)
2. Runs the Discord setup wizard if `.env` has no token yet
3. Starts the LM Studio server and loads `LLM_MODEL`
4. Launches the bot

```powershell
.\run.ps1
```

(If LM Studio can't start, the bot still runs on the xAI fallback when set.)

## Using it

- Address a crew member by name in the RP channel:
  - `Helmsman, come to course 090 and make turns for 15 knots.`
  - `Lookout, report.`
  - `Bosun, sound general quarters.`
  - `Navigator, what's the bearing to the nearest island?`
- `/status` — show the current ship state (private to you).
- `/crew` — list the crew and how to address each one.

## The crew (defined in `characters.yaml`)

| Name | Rank | Rate | Billet | Address as |
|---|---|---|---|---|
| Elias Cole | PO2 | Quartermaster | Helmsman | helm, helmsman, quartermaster, cole |
| Adaline Vance | CPO | Quartermaster | Navigator | navigator, nav, vance |
| Tomas Hartley | CPO | Boatswain's Mate | Bosun | bosun, boatswain, bos'n, hartley |
| Jonah Pike | Seaman | Boatswain's Mate (striker) | Lookout | lookout, watch, pike |
| Rourke Doyle | PO1 | Machinist's Mate | Engineer | engineer, engine room, chief, doyle |

## Editing the crew (character reference sheet)

All crew live in **`characters.yaml`** — the single source of truth for the
roster. Each NPC's model persona is *generated* from these fields, so just edit
the sheet (no code changes) to rename, re-rank, re-personalise, add, or remove
crew:

```yaml
  - key: gunner                 # stable id (don't reuse / rename casually)
    name: Mara Quill
    rank: Petty Officer 1st Class
    rate: Gunner's Mate
    billet: Gunnery
    aliases: [guns, gunner, quill]
    personality: >-
      Coolly precise and a little bloodthirsty. Lives for a clean firing
      solution and counts every round.
    avatar_url:                 # optional image URL -> visual identity in chat
```

In chat each NPC appears as **`<billet> <surname>`** (e.g. "Helmsman Cole").
Set `avatar_url` to any image URL to give them a distinct face.

## Swapping the model

Any model loaded in LM Studio works — just set `LLM_MODEL` in `.env` to its
identifier (see `lms ps` or the LM Studio UI). Larger models give more
consistent personas; smaller ones respond faster.

## Always-on fallback (xAI / Grok)

The bot tries your **local** model first (free, private). If LM Studio isn't
running, it automatically falls back to the **xAI cloud API** so the crew never
goes dark. Turn it on by filling these in `.env`:

```
XAI_API_KEY=xai-...          # from https://console.x.ai (blank = no fallback)
XAI_MODEL=grok-4-latest      # set to a model your account supports
```

- **Local up** -> uses LM Studio. **Local down** -> uses xAI. No restart needed.
- `/status` shows which backend served the last reply.
- Trade-off: local is free + private; the cloud fallback keeps the crew online
  even when LM Studio is closed.

## Extending

- **More ship state** — add fields to `ShipState` in `ship.py` and list them in
  the schema + prompt in `brain.py`.
- **Crew-to-crew banter** — have one NPC's reply trigger another.
- **Real turn simulation** — model heading change over time instead of the
  simple `steady_up` delay.
