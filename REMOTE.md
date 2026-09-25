# Remote hybrid hosting (draft — later)

Status: pondering note only. Not implemented. Captures the agreed direction from 2026-09-25.

## Goal

Keep HaylerBot online 24/7 without the gaming desktop awake. Optional local LM Studio when the desktop is on. Admin from a travel Mac when away.

## Roles

- **Home laptop** (Ubuntu Server or Debian — not Kali): always-on Discord bot, JSON state, LLM router, Wake-on-LAN sender, Tailscale node.
- **Desktop** (wired LAN, GPU): LM Studio only when needed; may sleep.
- **Travel Mac** (phone optional): Tailscale + Discord officer commands (or Shortcuts) to control the laptop. Not RDP-as-architecture.
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

Discord officer commands: `/llm status`, `/llm wake`, `/llm local`, `/llm xai` (maybe `/bot restart`). Optional Mac Shortcut later. No custom iPhone app for v1. No public expose of LM Studio. One Discord token = one bot process (on the laptop only).

## Day-to-day

- Home, want local: start LM Studio (icon) or `/llm wake`
- Home, desktop off: xAI — fine
- Traveling: leave alone (laptop + xAI)
- Traveling + want local: Mac → Tailscale → `/llm wake` → `/llm local`
- Force cloud: `/llm xai`

## Build order (when we pick this up)

1. Memory MVP (separate PR — may already be in flight)
2. `/llm status|wake|local|xai` + health-check router
3. Reflash laptop → systemd bot + Tailscale
4. Desktop WoL + LM Studio autostart
5. Polish: Shortcuts / tiny status page only if Discord is annoying

## Reject

GPU cloud 24/7; RDP as remote design; second bot on desktop; public port-forward to LM Studio; keeping Kali as appliance OS.

## Open questions

- Officer role IDs for `/llm` (and any `/bot restart`).
- Whether wake-from-travel is worth the desktop power draw.
- Backup of laptop JSON state (ship, plot, log) if the laptop disk fails.
