# Building the standalone (no Python needed to run it)

PyInstaller bundles Python + all libraries into **one file per OS**, so the machine
that *runs* it needs nothing installed:
- **Windows** → `dist/HaylerBot.exe`
- **macOS** → `dist/HaylerBot`

`characters.yaml` and `.env` stay **outside** the binary (next to it) so you can edit
the crew and secrets without rebuilding. `config.py` looks for them next to the exe.

The finished package is a small folder:
```
HaylerBot(.exe)     <- the standalone (double-click)
characters.yaml     <- edit the crew here
.env                <- your token + xAI key (copy from .env.portable)
```
State/logs (`ship_state.json`, `chronicle.json`, `bot.log`) are written next to it.

---

## Windows
The `.exe` is prebuilt (see `dist/`). To rebuild: double-click `build\build-windows.bat`
(or run it). It makes a build venv, installs PyInstaller, and runs the spec.

## macOS (finish this on the Mac — you can use Grok Build)
PyInstaller can't cross-compile, so the Mac binary is built **on a Mac**.

1. Open this folder on the Mac. Ensure Python 3 is installed (`python3 --version`;
   else install from python.org or `brew install python`).
2. Build it:
   ```bash
   bash build/build-mac.command
   ```
   This creates `dist/HaylerBot`, copies `characters.yaml` + `.env.portable` next to it,
   ad-hoc code-signs it, and clears the quarantine flag.
3. In `dist/`, copy `.env.portable` to `.env` and fill in `DISCORD_TOKEN`, `RP_CHANNEL_ID`,
   `XAI_API_KEY`.
4. Run it: double-click `HaylerBot` in Finder (opens Terminal), or `./HaylerBot`.

### Mac gotchas (what Grok Build should handle if they appear)
- **Gatekeeper "cannot verify developer":** the build script already runs
  `codesign --force --deep -s - dist/HaylerBot` and
  `xattr -dr com.apple.quarantine dist/HaylerBot`. If macOS still blocks it,
  right-click the binary → **Open** once.
- **Architecture:** the binary matches the build Mac (Apple Silicon or Intel). For a
  universal build you'd need PyInstaller `target_arch='universal2'` **and** universal
  wheels for `pydantic-core` — usually not worth it; build on the same chip you'll run on.
- **Want a double-click `.app`** instead of a Terminal binary? Add a `BUNDLE(...)` step
  to `naval-bot.spec` for `darwin`, or wrap `HaylerBot` in a one-line Automator app.
  A console app in a `.app` won't show output, so the plain binary is usually nicer for a bot.

---

## Notes
- The spec is `naval-bot.spec` (shared by both OSes). Build command:
  `pyinstaller --clean --noconfirm naval-bot.spec` from the project root.
- If a build errors with a missing module, add it to `hiddenimports` in the spec.
- **Single-instance:** the standalone still binds `127.0.0.1:49219`; run one copy per
  machine, and use a separate **test bot token** if running alongside your main bot.
