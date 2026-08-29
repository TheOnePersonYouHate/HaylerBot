# HaylerBot commands

The crew answer in the RP channel. Slash commands are ephemeral (only you see them). Prefix commands (`!plot`) post in the channel.

If a new slash command is missing on a server, an admin must enable it: **Server Settings → Integrations → Hayler Bot**. New commands often default to admins-only.

## Slash commands

| Command | Who sees it | What it does |
|---|---|---|
| `/plot` | You only | Show the CIC plot (contacts + last facts) |
| `/plot action:clear` | You only | Wipe all contacts and facts |
| `/status` | You only | Course, speed, alert, pending waits, plot, last LLM backend |
| `/crew` | You only | NPC roster, aliases, current location |
| `/where` | You only | Your space and who is in earshot |
| `/roster` | You only | Humans aboard and the rank the crew use for them |
| `/recap` | You only | Summarize this session into the ship's log |

## Prefix commands

Use these when slash commands are locked (no admin on the host server).

| Command | Who sees it | What it does |
|---|---|---|
| `!plot` | Channel | Same as `/plot` |
| `!plot clear` | Channel | Same as `/plot action:clear` |

`reset` and `wipe` also work in place of `clear`.

## Set and clear the plot (in the channel)

No command required. The bot parses contact language, best inside `*asterisks*`.

| You type | Result |
|---|---|
| `*three friendly aircraft, bearing 045, IFF friendly*` | Track **A1** (air, friendly, 045) |
| `*surface contact bearing 270 at 12nm*` | Track **S1** |
| `*submarine contact bearing 180*` | Track **B1** |
| Same kind + same bearing again | Updates that track (A1 stays A1) |
| `*no contacts*` / `plot is clear` | Wipe all tracks |
| `*SPY is clean*` / `no air contacts` | Clear air only; surface/sub stay |
| `Anything on SPY?` | Question — does **not** write the plot |
| `*In CIC*` | Location only — does **not** write the plot |

Glue a track to an order:

```
*three friendly aircraft, bearing 045, IFF friendly*
Hoover, report.
```

## Place yourself and talk

| You type | Result |
|---|---|
| `*In CIC*` | You are in CIC. Narration only — nobody answers |
| `*On the bridge*` / `*heads to engineering*` | Same, for those spaces |
| `Lieutenant Hoover, report.` | Hoover answers if you can reach him |
| `Bosun, how's the deck?` | Hartley, if in earshot |
| `McTane, come about to 090.` | Helm, if in earshot (officer+) |
| `*keys the 21MC* Bosun, CIC, lay to CIC.` | Circuit — reaches another space |
| `*over the 1MC* Bosun Hartley, to CIC.` | 1MC + movement order |
| `Bridge, CIC.` | Station hail |
| `(this is ooc)` `{note}` `// note` | Ignored — crew do not hear it |
| `out` / `over and out` | Sign-off — that thread ends |

Face-to-face only works in the **same space**. Name someone in another compartment without a circuit and you get silence (or a short “not in earshot” line).

## Authority

| Speaker | May change course / speed / GQ |
|---|---|
| Warrant and above | Yes |
| Chief and below | No — they refuse in character; ship state does not move |
| Anyone | Notes, questions, routine reports |

`Chief` alone is not an alias. Use `Chief McTane`, `Bosun`, `Hartley`, `Hoover`, etc. `/crew` has the list.

## Movement / waits

| You type | Result |
|---|---|
| `Bosun, report to the captain's cabin.` | He leaves, then knocks and **waits** |
| `Hartley, to CIC` | Movement — he actually changes space |
| `Enter.` / `as you were` / `belay` | Releases a held wait |

`/status` lists held actions.

## Admin: make slash commands visible

| Where | What to set |
|---|---|
| Integrations → Hayler Bot | Enable `/plot` `/status` `/crew` `/where` `/roster` `/recap` for @everyone or the CIC role |
| Role permissions | **Use Application Commands** |
| RP channel | View Channel, Send Messages, Read History, **Manage Webhooks**, Embed Links, Use Application Commands |

Testers do **not** need Administrator.

## Quick test

1. `*In CIC*`
2. `Lieutenant Hoover, report.`
3. `*three friendly aircraft, bearing 045, IFF friendly*`
4. `!plot` (or `/plot` if enabled)
5. `*keys the 21MC* Bosun, CIC, lay to CIC.`
