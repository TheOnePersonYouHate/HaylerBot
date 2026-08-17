#!/bin/bash
# Portable launcher for macOS. Double-click in Finder, or from Terminal run:
#   bash start-mac.command
# Needs Python 3 (https://www.python.org/downloads/) + internet on first run.
cd "$(dirname "$0")" || exit 1
VENV=".venv-mac"
PYEXE="$VENV/bin/python"

if [ ! -x "$PYEXE" ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 not found."
    echo "Install it from https://www.python.org/downloads/ or run: brew install python"
    read -r -p "Press Enter to close..."
    exit 1
  fi
  echo "[setup] First run: building the environment. This takes a minute..."
  python3 -m venv "$VENV"
  "$PYEXE" -m pip install --disable-pip-version-check -q -r requirements.txt
fi

if [ ! -f ".env" ]; then
  echo "No .env found. Copy .env.portable to .env and fill in your token and xAI key."
  echo "See PORTABLE.md for the steps."
  read -r -p "Press Enter to close..."
  exit 1
fi

echo "[start] Launching the crew. Press Ctrl+C or close this window to stop."
"$PYEXE" bot.py
