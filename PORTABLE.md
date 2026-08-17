# Portable / flash-drive build (Windows + Mac)

Run the bot from a USB stick on any computer for testing. This build uses **xAI
(Grok) as the brain**, so the test machine needs **no LM Studio and no GPU** —
just Python 3 and an internet connection.

## What goes on the flash drive
Copy the **whole project folder** to the USB. The parts that matter for portable use:

```
bot.py  brain.py  npcs.py  ship.py  config.py   (the code -- cross-platform)
characters.yaml   requirements.txt
start-windows.bat        <- double-click on Windows
start-mac.command        <- double-click on Mac
.env.portable            <- copy to .env and fill in (see below)
```

You do **not** need to copy `.venv`, `bot.log`, or `ship_state.json` — those get
created on the test machine. (An exFAT-formatted USB is the safest for sharing
between Windows and Mac.)

## One-time setup
1. Copy `.env.portable` to a new file named **`.env`** (same folder).
2. Open `.env` and fill in:
   - `DISCORD_TOKEN` — **use a separate test bot**, see the warning below.
   - `RP_CHANNEL_ID` — the channel(s) to listen in.
   - `XAI_API_KEY` — your xAI key.
   (Everything else is preset for xAI-only.)

## Running it
- **Windows:** double-click **`start-windows.bat`**.
- **Mac:** double-click **`start-mac.command`**. If macOS blocks it (common on
  USB drives, which don't keep the "executable" flag), open Terminal and run:
  ```
  cd /Volumes/YOUR_USB/naval-rp-bot
  bash start-mac.command
  ```

The **first run** builds a small Python environment in `.venv-windows` /
`.venv-mac` on the stick (needs internet, takes ~a minute). Every run after that
starts immediately. Close the window (or Ctrl+C) to stop.

## Important: don't run two copies of the same bot
The bot only responds correctly when **one instance** is running per token.
- The built-in single-instance lock stops two copies on the *same* machine.
- But two machines using the **same token** will *both* answer → doubled replies.

So for testing on other computers, **create a separate "test" Discord bot** (its
own application + token in the Developer Portal) and put that token in `.env`.
Then the test build can run alongside your main bot without collisions, and a
misplaced USB only exposes a throwaway test token.

## Notes
- The code is pure Python and identical on both OSes — no rebuild needed.
- State/logs (`ship_state.json`, `chronicle.json`, `bot.log`) are written next to
  the app on the USB, so a session's memory travels with the stick.
- Want a *no-Python-needed* build (a single double-click .exe / .app)? That's
  possible with PyInstaller, but has to be compiled separately on a Windows PC and
  a Mac. Ask and I'll set up the build scripts.
