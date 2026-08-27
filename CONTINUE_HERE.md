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

### Done (2026-08-26)

**1. Actions stick (pending-action).** Per-NPC `pending` on `ChannelState`, persisted in `pending.json`. Injected every `npc_respond`. Arrival follow-up becomes the held beat; “Enter” / “as you were” / “belay” / explicit `pending: ""` clears it. Prompt no longer says “advance the moment” while a wait is held. `/status` lists held actions.

**2. Crew-to-crew uses earshot.** `_run_crew_chain` and the hail collector run through `can_reach` (same space, or a circuit / station hail). A face-to-face “Bosun! Get in here!” from CIC no longer pulls Hartley off the main deck.

**3. Authority is enforced in code.** `apply_update` strips heading/speed/alert unless `can_order_ship` (warrant+). Notes still apply for anyone. Prompt refusal remains as the in-character response.

**4. Alias landmines removed.** Dropped Doyle `chief`, Pike `watch`, Flasterstein `gunner`. `Chief McTane` / personal names still work.

Offline regress: `python tests/test_scene_state.py`.

### Still open

Location teleports are blocked unless the line is a movement order, the NPC is already `en route`, or the new place is the same space.

Prompt slimmed: history 60; SWO encyclopedia is `ship.swo` for nav/helm/lookout/Hoover only; Navy lecture tail (history/awards/designators/uniforms) cut; Hartley 1MC kit injects only on announcement orders.

Auto-recap after `RECAP_IDLE_SECONDS` (default 10 min) idle, and on clean shutdown. `/recap` still works.

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

1. Shrink the prompt (shared Navy block first; 1MC only on Hartley; history ~60).
2. Auto-recap on idle/shutdown.
3. Optionally refuse hallucinated `location` jumps that skip a movement beat.
4. Avatars / soundboard.

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
