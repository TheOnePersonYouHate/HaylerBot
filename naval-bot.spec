# PyInstaller spec for the Naval RP bot -- one standalone file per OS.
# Windows -> dist/HaylerBot.exe   |   macOS -> dist/HaylerBot
# Build from the project root:  pyinstaller --clean --noconfirm naval-bot.spec
#
# characters.yaml and .env stay OUTSIDE the binary (next to it) so the crew and
# secrets can be edited without rebuilding. config.py resolves them next to the exe.
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

# Pull in submodules that PyInstaller's static analysis can miss, plus the package
# metadata a couple of libraries read at import time.
hiddenimports = collect_submodules("discord") + collect_submodules("openai")
datas = []
for dist in ("openai", "certifi"):
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass

a = Analysis(
    ["bot.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HaylerBot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,          # show a console window: you can see "Logged in" + errors, close to stop
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
