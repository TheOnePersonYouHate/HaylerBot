#!/bin/bash
# Build the standalone macOS binary. Needs Python 3 + internet (one-time).
# Double-click, or from Terminal: bash build/build-mac.command
cd "$(dirname "$0")/.." || exit 1
PYEXE=".venv-build/bin/python"
if [ ! -x "$PYEXE" ]; then
  echo "[setup] Creating a build environment..."
  python3 -m venv .venv-build
fi
"$PYEXE" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller
"$PYEXE" -m PyInstaller --clean --noconfirm --workpath .build-work naval-bot.spec
if [ ! -x "dist/HaylerBot" ]; then echo "BUILD FAILED"; read -r -p "Press Enter to close..."; exit 1; fi
cp characters.yaml dist/
[ -f .env.portable ] && cp .env.portable dist/
# Ad-hoc codesign + clear the "downloaded" quarantine flag so it opens without a Gatekeeper block.
codesign --force --deep -s - dist/HaylerBot 2>/dev/null
xattr -dr com.apple.quarantine dist/HaylerBot 2>/dev/null
echo ""
echo "=== Build complete ==="
echo "Standalone folder: dist/  (HaylerBot + characters.yaml + .env.portable)"
echo "Copy .env.portable to .env in dist/, fill it in, then run ./HaylerBot (or double-click it)."
read -r -p "Press Enter to close..."
