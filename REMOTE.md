# Remote hybrid hosting (draft — later)

Status: pondering note only. Not implemented. Captures the agreed direction from 2026-09-25.

## Goal

Keep HaylerBot online 24/7 without the gaming desktop awake. Optional local LM Studio when the desktop is on. Admin from a travel Mac when away.

## Roles

- **Home laptop** (Ubuntu Server or Debian — not Kali): always-on Discord bot, JSON state, LLM router, Wake-on-LAN sender, Tailscale node, and the local ops console (below).
- **Desktop** (wired LAN, GPU): LM Studio only when needed; may sleep.
- **Travel Mac** (phone optional): Tailscale onto the laptop, then Discord officer commands (or Shortcuts) or the local ops channel on that host. Not RDP-as-architecture.
- **xAI**: default LLM whenever desktop / LM Studio is down.

## Traffic

Players → Discord → home laptop bot → LM Studio on desktop if healthy, else xAI.

Admin on Mac (away) → Tailscale → laptop → `/llm status|wake|local|xai` and WoL to desktop → autostart LM Studio → bot flips local when API healthy.

## Same LAN

Laptop and desktop share the home LAN (desktop wired). At home, the laptop calls `http://<desktop-lan-ip>:1234/v1`. No Tailscale required for that hop. Firewall: allow LM Studio / port on the Private network only; DHCP reservation for the desktop.

## Out of house

Tailscale on the laptop and the travel Mac. Phone optional. The laptop relays WoL; a phone or Mac cannot magic-packet the LAN alone from LTE.

## WoL notes

BIOS WoL on; NIC magic packet; Fast Startup off; wired preferred. After wake: Task Scheduler / login script starts LM Studio and the model. The bot stays on xAI until the health check passes.

## Control plane (v1)

Two surfaces. Discord is the player front door. Officer corrections also need a path that does not depend on Discord.

Discord officer commands (convenience, only while Discord is up): `/llm status`, `/llm wake`, `/llm local`, `/llm xai` (maybe `/bot restart`). Optional Mac Shortcut later. No custom iPhone app for v1. No public expose of LM Studio. One Discord token = one bot process (on the laptop only).

Local ops (the path that still works if Discord is down): see below. It lives on the bot host, not in the Discord client.

## Local ops console (later)

Status: backlog. Not implemented.

Officer access on the machine running the bot, for commands and corrections, with no Discord (and no other third party) in the loop. Players still enter through Discord. Ops should keep working if Discord is down, rate-limited, or no client is open.

Not RP chat in the terminal. Not a clone of player slash commands.

Shape, all local-only — stdin in the run window, a small `haylerctl` CLI, and/or localhost HTTP. Officer commands only, for example: `status`, `pin list|add|rm`, `where`, `llm local|xai|status`, maybe `reload-state`.

Where it lives: the bot process’s host. In this hybrid plan that is the always-on home laptop, not the desktop and not a second bot. Away from home, reach that laptop over Tailscale (SSH) and use the local channel there. Do not publish an admin listener off the box.

Auth idea: if you can reach the process on the host (or on localhost), you are trusted. Bind it to localhost / the machine running the bot.

Out of scope for this note: building the console now; changing Discord player UX; exposing an admin API beyond localhost.

## Day-to-day

- Home, want local: start LM Studio (icon) or `/llm wake`
- Home, desktop off: xAI — fine
- Traveling: leave alone (laptop + xAI)
- Traveling + want local: Mac → Tailscale → `/llm wake` → `/llm local`
- Force cloud: `/llm xai`
- Discord down, or no client open, and state needs a correction: on the laptop, local ops (`status`, pins, `llm`, …). Not the Discord client.

## Build order (when we pick this up)

1. Memory MVP (separate PR — may already be in flight)
2. `/llm status|wake|local|xai` + health-check router
3. Reflash laptop → systemd bot + Tailscale
4. Desktop WoL + LM Studio autostart
5. Polish: Shortcuts / tiny status page only if Discord is annoying
6. Local ops on the laptop (stdin / `haylerctl` / localhost) so officer corrections do not need Discord

## Reject

GPU cloud 24/7; RDP as remote design; second bot on desktop; public port-forward to LM Studio; keeping Kali as appliance OS; an admin API reachable beyond localhost.

## Open questions

- Officer role IDs for `/llm` (and any `/bot restart`).
- Whether wake-from-travel is worth the desktop power draw.
- Backup of laptop JSON state (ship, plot, log) if the laptop disk fails.
