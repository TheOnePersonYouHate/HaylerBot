# Deploying the Naval RP Bot 24/7 (xAI brain, no GPU)

This runs the bot on a small always-on Linux server with **xAI (grok-4.3) as the
only brain** — no LM Studio, no GPU. The bot stays online in Discord independent
of your home PC.

> The xAI API key is the *brain*, not the *host*. You still need a machine that
> runs `bot.py` around the clock. Any tiny Linux VPS (1 vCPU / 512 MB–1 GB RAM)
> is plenty — the bot just makes HTTP calls to xAI.

---

## 1. Get a server
A small VPS on Ubuntu **24.04** (ships Python 3.12) is the easiest. SSH in, then
create a non-root user to run the bot:

```bash
sudo adduser --system --group --home /opt/naval-rp-bot botuser
sudo apt update && sudo apt install -y python3 python3-venv git
```

## 2. Put the code on the server
Copy the project to `/opt/naval-rp-bot` (git clone, `scp -r`, or rsync). Do **not**
copy your existing `.env` — you'll make a server-specific one in the next step.

```bash
sudo chown -R botuser:botuser /opt/naval-rp-bot
```

## 3. Create the virtual env + install deps
```bash
cd /opt/naval-rp-bot
sudo -u botuser python3 -m venv .venv
sudo -u botuser .venv/bin/pip install -r requirements.txt
```

## 4. Create the xAI-only `.env`
Create `/opt/naval-rp-bot/.env` (owned by `botuser`, mode `600`). The key line is
**`LLM_BASE_URL=` left empty** — that turns off the local backend cleanly so the
bot goes straight to xAI with no startup delay.

```ini
# --- Discord ---
DISCORD_TOKEN=your-bot-token
RP_CHANNEL_ID=1366153657049153540,1519769056801067068

# --- Brain: xAI only (no local model on this host) ---
LLM_BASE_URL=
XAI_API_KEY=xai-your-key
XAI_BASE_URL=https://api.x.ai/v1
XAI_MODEL=grok-4.3

# --- Conversation feel ---
CONTINUITY_SECONDS=60

# --- Persistence (relative to this directory) ---
STATE_FILE=ship_state.json
LOG_FILE=chronicle.json
CHARACTERS_FILE=characters.yaml
```

Lock it down (it holds your token + key):
```bash
sudo chown botuser:botuser .env && sudo chmod 600 .env
```

## 5. Smoke test
```bash
sudo -u botuser .venv/bin/python bot.py
```
You should see `Logged in as Hayler Bot#6018 ...`. Address a crew member in
Discord to confirm replies, then `Ctrl+C`.

## 6. Run it forever with systemd
```bash
sudo cp deploy/naval-rp-bot.service /etc/systemd/system/
# Edit User=/WorkingDirectory=/ExecStart= in the unit if your paths differ.
sudo systemctl daemon-reload
sudo systemctl enable --now naval-rp-bot
```

Useful commands:
```bash
systemctl status naval-rp-bot          # is it up?
journalctl -u naval-rp-bot -f          # live logs
sudo systemctl restart naval-rp-bot    # after a code/.env change
```

`Restart=always` brings it back on crash; `enable` brings it back on reboot.

## 7. Updating later
```bash
cd /opt/naval-rp-bot && sudo -u botuser git pull
sudo -u botuser .venv/bin/pip install -r requirements.txt   # only if deps changed
sudo systemctl restart naval-rp-bot
```

---

## Alternative: Docker
Prefer containers? Build from the project root (so the build context is the repo):

```bash
docker build -f deploy/Dockerfile -t naval-rp-bot .
docker run -d --name naval-rp-bot --restart=always \
  --env-file .env \
  -v naval-rp-state:/app/state \
  naval-rp-bot
```

With Docker, set `STATE_FILE=state/ship_state.json` and `LOG_FILE=state/chronicle.json`
in `.env` so the ship's log and state persist on the named volume across restarts.
The image never bakes in `.env` (it's excluded) — secrets come in at runtime via
`--env-file`.

---

## Notes
- **Privacy:** on this host everything goes through xAI (no local/private model).
  Your home PC setup still runs local-first when you use it there.
- **Resilience:** discord.py auto-reconnects to the gateway; systemd/Docker handle
  process crashes and reboots. The OpenAI client retries transient xAI errors.
- **Secrets:** keep `.env` at mode `600`, run as a non-root user, and rotate the
  Discord token in the Developer Portal if it's ever exposed.
- **One bot only:** run the bot in exactly one place at a time. Two instances on
  the same token = doubled replies.
