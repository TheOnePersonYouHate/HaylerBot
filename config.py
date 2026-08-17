"""Configuration loaded from environment / .env file."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _base_dir() -> Path:
    """Folder to read .env / data files from and write state to. Next to the
    executable when bundled (PyInstaller standalone), else next to the source.
    Keeps the app working no matter what the launch directory is."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = _base_dir()
load_dotenv(BASE_DIR / ".env")


def _under_base(p: str) -> str:
    """Resolve a (possibly relative) data-file path against BASE_DIR."""
    q = Path(p)
    return str(q if q.is_absolute() else BASE_DIR / q)


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(
            f"Missing required env var {name!r}. "
            "Copy .env.example to .env and fill it in."
        )
    return value


# --- Discord ---
DISCORD_TOKEN = _require("DISCORD_TOKEN")

# Channels the crew operate in -- one or more IDs, comma-separated, across any
# servers the bot is in (e.g. RP_CHANNEL_ID=111,222).
RP_CHANNEL_IDS = {
    int(x) for x in os.getenv("RP_CHANNEL_ID", "").replace(" ", "").split(",") if x
}
if not RP_CHANNEL_IDS:
    raise SystemExit("Set RP_CHANNEL_ID in .env (one or more channel IDs, comma-separated).")

# Channels where the crew reply ONLY when a crew member is explicitly named
# (no conversation-continuity guessing). Good for shared / test channels.
STRICT_CHANNEL_IDS = {
    int(x) for x in os.getenv("STRICT_CHANNEL_ID", "").replace(" ", "").split(",") if x
}

# How long (seconds) an un-addressed follow-up still continues the conversation
# with the last-engaged NPC. Pause longer than this and the crew disengage, so
# you can talk out-of-context freely. ~60 keeps natural back-and-forth smooth (no
# re-naming every line); the relevance gate + OOC markers still filter stray chatter.
CONTINUITY_SECONDS = int(os.getenv("CONTINUITY_SECONDS", "60"))

# Optional. Slash commands now sync to every server the bot is in, so this is
# unused -- kept only for backward compatibility with older .env files.
GUILD_ID = int(os.getenv("GUILD_ID") or 0)

# --- Local LLM (LM Studio's OpenAI-compatible server) ---
# 127.0.0.1 (not "localhost") avoids slow IPv6 resolution on Windows.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:1234/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemma-4-31b")
# LM Studio ignores the key, but the OpenAI client requires a non-empty value.
LLM_API_KEY = os.getenv("LLM_API_KEY", "lm-studio")

# --- Cloud fallback (xAI / Grok) ---
# If LM Studio is offline, the bot falls back to xAI so the crew stays online.
# Leave XAI_API_KEY blank to disable the fallback (local only).
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-4.3")

# How many replies may generate on the local GPU at once before new ones
# overflow to xAI (when XAI_API_KEY is set). Match this to LM Studio's parallel
# slots (its default is 4). Set to 0 to disable overflow and always use local.
LOCAL_MAX_INFLIGHT = int(os.getenv("LOCAL_MAX_INFLIGHT", "4"))

# --- Characters ---
CHARACTERS_FILE = _under_base(os.getenv("CHARACTERS_FILE", "characters.yaml"))

# --- Persistence ---
STATE_FILE = _under_base(os.getenv("STATE_FILE", "ship_state.json"))
LOG_FILE = _under_base(os.getenv("LOG_FILE", "chronicle.json"))
