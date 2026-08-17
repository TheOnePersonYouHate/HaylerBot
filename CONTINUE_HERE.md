# Continue Here — Naval RP Bot

**Read this first** when resuming on Windows (`C:\Users\Riley\naval-rp-bot`).
Written 2026-08-11 on the Mac after bringing that box up to date.
Deeper architecture: `PROJECT_STATUS.md`. Mac-session changelog: `CHANGES_2026-07-05.md`.

---

## 1. What to do first on Windows

Stop any running `HaylerBot.exe` (it locks the file). Then **overwrite Windows source with the Mac copies** of:

| Copy from Mac `~/Test/naval-rp-bot/` | Onto Windows `C:\Users\Riley\naval-rp-bot\` |
|---|---|
| `bot.py` | same |
| `brain.py` | same |
| `npcs.py` | same |
| `characters.yaml` | same (**and** `dist\characters.yaml`) |
| `CONTINUE_HERE.md` | same |
| `run.ps1` | same (now loads gemma with `-c 24000`) |

Do **not** overwrite Windows `.env` / `dist\.env` — those have the local LM Studio setup. After the yaml copy, rebuild the exe (`build\build-windows.bat`) and relaunch.

**Do not run Mac and Windows on the same Discord token at once.**

---

## 2. Where we left off

### Mac (this session, 2026-08-11)
- Behavioral parity with the last Windows build (earshot/circuits, sign-off, narration, group address, crew-to-crew, Navy knowledge block, `/where`, Santos ID, Hoover = **Lieutenant Hoover**, 3rd channel).
- **Irinchev (XO NPC) removed** from live `crew:` — parked in `inactive_crew:` so `xo`/`exec` no longer clash with player Kovacs.
- Desktop app: `~/Desktop/HaylerBot.app` → `dist/HaylerBot` (xAI-only). Rebuilt + signed. Not left running.
- Real Mac roster kept (SWO knowledge + Hartley's 1MC repertoire). Windows still had a reconstructed placeholder yaml until you copy this one over.
- Offline routing suite: **31/31**. Bridge station hail now answers as **Navigator Vance** (senior watch still on the bridge after Irinchev).

### Windows (last session there, ~2026-07-06)
- Live on 3 channels with LM Studio `gemma-4-31b` + xAI overflow.
- Last product decision: **reply-to-talk stays consistent with earshot** (“Leave it consistent”).
- Last work: Navy comms model + Navy knowledge drop + icon. Then paused.

### Intentional Mac ≠ Windows (until you sync)
| | Mac app | Windows app (until copy) |
|---|---|---|
| Brain | xAI only | LM Studio first, Grok overflow |
| Irinchev | gone | still present |
| `characters.yaml` | real roster | reconstructed placeholder |
| Icon | July 5 HNC badge | newer USS Hayler silhouette `.ico` |

---

## 3. How to think about the bot (resume-chat prompt)

The bot is good at **answering in character**. It is not yet a reliable **ship simulation**.

Code decides *who* may speak (routing, earshot, circuits). The model decides *what’s true in the scene*. Those disagree, and scenes break. Treat it as a **watch bill + radio net**, not ChatGPT with hats:

- **Code owns:** who can hear, who may order GQ/helm/weapons, where people are, what each NPC is *in the middle of*.
- **Model owns:** voice, banter, how they *say* the report.

Do **not** add more crew or more Wikipedia until state/spatial/authority are real.

---

## 4. Issues to iron out (priority)

### P0 — breaks scenes

**1. Actions don’t stick (pending-action).**
Bosun knocks and waits → next line he’s back on the main deck. We store speech + a location string. We do **not** store “waiting at the CO’s door until someone says enter.” The prompt fights itself: “hold the beat” vs “vary your language / advance the moment.” `FOLLOWUP_DELAY = 15` fires whether the beat is ready or not.

Fix: persist per-NPC `pending` on `ChannelState` (e.g. `waiting at captain's cabin, knocked, not admitted`). Inject it every `npc_respond`. Clear on “enter” / new order. Suppress “advance the moment” while set. Don’t treat a 15s timer as “arrived.”

**2. Crew-to-crew ignores earshot.**
Players can’t yell from engineering to McTane. But if Hoover says “Bosun! Get in here!”, `_run_crew_chain` uses `find_called` with **no** space/circuit check — Hartley answers from the main deck. Same hole for NPC 1MC vs face-to-face.

Fix: run crew-chain targets through the same earshot + `comms_channel` rules as players.

**3. Authority is honor-system.**
`apply_update` never checks rank. A Seaman can set GQ or change course if the model plays along. Location is the same: omit `location` → they never moved; hallucinate it → they teleport.

Fix: refuse helm/GQ/weapons in code unless `rank_index` is officer+. Optionally ignore `location` jumps that skip a movement beat.

### P1 — keeps biting in play

**4. Alias landmines** in `characters.yaml`:
- Doyle: `chief` (steals McTane / any “Chief, …”)
- Pike: `watch`
- Flasterstein: `gunner`
Vocative rules help; they aren’t airtight. Drop the generic words; keep personal names.

**5. Prompt is too fat.**
Every call gets SWO spec + `NAVY_REFERENCE` + 120-line history. Credits aren’t the issue; **attention** is. Last two lines of the scene get buried → loops, wrong contacts, “Commodoree.”

Fix: shared Navy block first (prefix-cache on local); 1MC repertoire only on Hartley; SWO detail on nav/helm/OOD types; history ~60 unless `/recap` just ran.

**6. Memory is scrollback, not a log.**
`/recap` is manual. Crash loses the story. `ship.notes` is a sticky, not a CIC plot. Chronicle is one blob every NPC reads the same way. Auto-recap on idle/shutdown is the durable fix.

### P2 — polish / ops

**7. Avatars** — files in `avatars/`; need public URLs in yaml. McTane has none.
**8. Soundboard** — `VoiceChannel.send_sound` exists; needs PyNaCl + join-voice + rebuild. Design TBD.
**9. Two machines, one token** — easy to double-boot. No always-on host (`deploy/` paused).
**10. Windows icon** — newer Hayler silhouette is Windows-only; Mac launcher still uses the HNC badge. Cosmetic.

---

## 5. Suggested next pass (when you sit down)

One PR-sized chunk, in this order:

1. Pending-action field + prompt tweak (kill “advance the moment” while pending).
2. Earshot/circuits on `_run_crew_chain`.
3. Hard reject in `apply_update` for sub-officer helm/GQ/weapons.
4. Alias cleanup (`chief` / `watch` / `gunner`).

Then shrink the prompt. Then auto-recap. Then avatars/soundboard.

Keep the existing offline regress (`_regress.py` from the Windows session, or recreate from the 31 checks). Add cases for: pending hold, crew-chain blocked across spaces, Seaman cannot `state_update.alert = general quarters`.

---

## 6. Live roster (Mac yaml, after Irinchev removal)

**Active (11):** Vance (nav), Hartley (bosun + 1MC), Pike (lookout), Doyle (engineer), Woods (AWOL), Hoover (LT, CIC, display `Lieutenant Hoover`), Tartaglione (HT), Whitfield (yeoman), Flasterstein (wing gunner), McGilvray (EN3), **McTane** (helm, QMC).

**Inactive:** Irinchev (xo), Torres, Owens, Maulawin, Cole.

**Players:** Santos → Captain (`discord_id: 269270106264043521`, match `commodore`); LCDR `theonepersonyouhate` `998033426676449391`.

**Channels:** `1366153657049153540`, `1519769056801067068`, `1523548921610244277`.

**Bot:** Hayler Bot#6018.

---

## 7. Restart / rebuild rules

- yaml / `.env` → relaunch only. Update `dist\` copies too (the exe reads from `dist\`).
- `bot.py` / `brain.py` / `npcs.py` → **stop the running exe first**, then `build\build-windows.bat`.
- Single-instance lock: `127.0.0.1:49219`.
- Mac: `bash build/build-mac.command` (does not overwrite `dist/.env`).
