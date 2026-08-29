"""The NPC 'brain': a structured LLM call with automatic local -> cloud fallback.

The primary backend is LM Studio (local, free, private). If LM Studio isn't
running, the bot transparently falls back to the xAI (Grok) cloud API so the
crew stays online. Both speak the OpenAI-compatible API, so the same code and
JSON schema drive either one.

Given an NPC persona, the player's order, the current ship state, and recent
chatter, the model returns JSON: `{ "say": ..., "state_update": ... }`.
"""
import json
import re

import httpx
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

import config
from npcs import SHIP, kit_for, swo_for

# Local LM Studio client. Short connect timeout so we fail over fast when off.
_local = (
    AsyncOpenAI(
        base_url=config.LLM_BASE_URL,
        api_key=config.LLM_API_KEY,
        timeout=httpx.Timeout(120.0, connect=2.0),
    )
    if config.LLM_BASE_URL
    else None
)

# Cloud fallback (xAI / Grok). Disabled when no key is set.
_xai = (
    AsyncOpenAI(base_url=config.XAI_BASE_URL, api_key=config.XAI_API_KEY)
    if config.XAI_API_KEY
    else None
)

# Which backend served the most recent reply (surfaced by /status).
LAST_BACKEND = "none"

# How many local (LM Studio) replies are generating right now. When this reaches
# config.LOCAL_MAX_INFLIGHT, new replies overflow to xAI so a busy GPU doesn't
# make everyone queue. No lock needed: asyncio runs this on one thread.
_local_inflight = 0

# JSON schema for structured outputs -> parseable, predictable replies.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "say": {"type": "string"},
        "followup": {"type": "string"},
        "location": {"type": "string"},
        "pending": {"type": "string"},
        "state_update": {
            "type": "object",
            "properties": {
                "heading": {"type": "integer"},
                "speed": {"type": "integer"},
                "alert": {"type": "string"},
                "notes": {"type": "string"},
            },
        },
    },
    "required": ["say"],
}

# Shared US Navy knowledge handed to EVERY NPC. Kept in code so it applies to the
# whole crew and survives any characters.yaml swap.
NAVY_REFERENCE = """US NAVY KNOWLEDGE (true for you and everyone aboard -- apply it naturally in how you speak, address people, and carry yourself; never lecture, quote, or recite it):

ENLISTED -- RATING vs RATE:
- A RATING is your job/occupational specialty, e.g. Boatswain's Mate (BM), Quartermaster (QM), Gunner's Mate (GM), Operations Specialist (OS), Fire Controlman (FC), Sonar Technician (STG), Electronics Technician (ET), Gas Turbine Systems Technician (GS), Hull Maintenance Technician (HT), Interior Communications Electrician (IC), Yeoman (YN), Culinary Specialist (CS), Hospital Corpsman (HM), Information Systems Technician (IT).
- A RATE is paygrade + rating. Paygrades: E-1 Seaman Recruit (SR), E-2 Seaman Apprentice (SA), E-3 Seaman (SN) [Fireman FN / Airman AN by community]; E-4 Petty Officer 3rd Class (PO3), E-5 Petty Officer 2nd Class (PO2), E-6 Petty Officer 1st Class (PO1); E-7 Chief Petty Officer (CPO / "Chief"), E-8 Senior Chief (SCPO), E-9 Master Chief (MCPO).
- Written as an abbreviation the rating comes first: QMC = Quartermaster Chief (E-7), BM1 = Boatswain's Mate 1st Class (E-6), GM2 = Gunner's Mate 2nd Class (E-5). Address junior sailors as "Seaman <name>," E-4/5/6 as "Petty Officer <name>," and E-7/8/9 as "Chief," "Senior Chief," or "Master Chief." The senior enlisted advisor aboard is the Command Master Chief (CMC).

OFFICERS (commissioned), junior to senior, with collar insignia:
- O-1 Ensign (ENS) gold bar; O-2 Lieutenant Junior Grade (LTJG) silver bar; O-3 Lieutenant (LT) two silver bars ("railroad tracks"); O-4 Lieutenant Commander (LCDR) gold oak leaf; O-5 Commander (CDR) silver oak leaf; O-6 Captain (CAPT) silver eagle ("full bird"); O-7 Rear Admiral Lower Half (RDML) one star; O-8 Rear Admiral (RADM) two stars; O-9 Vice Admiral (VADM) three stars; O-10 Admiral (ADM) four stars.
- Address officers as "sir"/"ma'am" or rank + surname. Whoever commands the ship is "the Captain" / "the Skipper" no matter their actual rank (a cruiser CO is normally an O-6); the second-in-command is the XO. WARRANT OFFICERS (CWO2-CWO5) are senior technical specialists commissioned up from the chief's mess -- address them "Warrant," "Chief Warrant Officer," "Mister/Ms <name>," or "sir/ma'am."

SHIPBOARD MESSING & BERTHING (respect the separation strictly):
- E-6 and below eat on the MESS DECKS. Chiefs (E-7-E-9) have their own CPO MESS -- the "GOAT LOCKER," their private domain; junior sailors enter only when invited. Commissioned officers belong to the WARDROOM. Big ships (carriers, big-decks) may add a FIRST CLASS MESS for E-6, a place to learn mess life before making chief.
- Enlisted meals look free but are paid for by forfeiting Basic Allowance for Subsistence (BAS, "commuted rations"); chiefs may carry a mess "buy-in" or monthly mess bill about equal to BAS. Embarked Marine staff NCOs (E-7-E-9) join the CPO Mess. Officers keep their BAS but pay out of pocket while afloat through a wardroom mess buy-in -- a monthly bill or a mess card. The chiefs are the backbone of the mess: mentors to the junior enlisted and the seasoned technical advisors to the officers.

THE WARDROOM (the officers' mess -- their dining room, lounge and living space, and the officer community itself):
- Run by the President of the Mess, normally the XO (or the senior officer present), who presides at meals -- juniors stay standing until the senior is seated. A junior officer usually serves as mess caterer/treasurer, running the menu, budget, and monthly mess bills.
- On a ship this size the CAPTAIN is traditionally NOT a member: he/she eats in the cabin with a steward and comes to the wardroom only as an honored guest of the XO, so the junior officers have a place to unwind and speak candidly. When the Captain is present, he/she is the senior member.
- Etiquette: uncover (cover off) when you enter officers' country; a junior asks the senior present "May I join you, sir/ma'am?"; wear the uniform of the day; no arguing, no dressing-down subordinates, and no official business or meetings at the table. Discouraged table topics by old custom are politics, religion, and women -- and "shop talk" (work), to keep it social. In action a small ship's wardroom doubles as a meeting room and the battle dressing station.

GENERAL QUARTERS (GQ / "battle stations" / Condition I -- the highest state of readiness):
- Called away on the 1MC: "General Quarters, General Quarters. All hands, man your battle stations..." with the route of travel and "set material condition Zebra," over a klaxon/alarm. Every hand drops what they're doing and mans their assigned battle station as fast as possible -- damage-control parties set, all weapons manned, the ship buttoned up. It's exhausting and can't be held indefinitely.
- MATERIAL CONDITIONS of readiness (how tightly the ship is closed up; fittings are marked X, Y, Z): X-RAY = least, set in port in peacetime; YOKE = set at sea in peacetime (or in port in wartime); ZEBRA = maximum watertight/firetight integrity, set automatically at GQ and for fire or flooding.
- TRAFFIC during GQ is one-way so hundreds of sailors don't collide: UP and FORWARD on the STARBOARD side, DOWN and AFT on the PORT side.

FLEET CONTEXT:
- Hayler is forward-deployed under U.S. SEVENTH FLEET, the Navy's largest numbered fleet (headquartered in Yokosuka, Japan; part of the Pacific Fleet; commanded by a Vice Admiral; flagship USS Blue Ridge, LCC-19). Its Indo-Pacific area of responsibility runs from the International Date Line west to the India/Pakistan border and from the Kuril Islands south to Antarctica -- some 50-70 ships, ~150 aircraft, and 27,000+ Sailors and Marines.
- 7th Fleet fights organized into task forces: TF-70 carrier strike, TF-72 patrol & reconnaissance, TF-73 logistics (Western Pacific), TF-74 submarines, TF-75 expeditionary, TF-76 amphibious. Talk like a forward-deployed WESTPAC crew -- Yokosuka, Sasebo, Guam, port calls, and 7th Fleet taskings.

SHIP'S COMMUNICATIONS -- you reach beyond your own compartment ONLY over a circuit:
- The 1MC (1 Main Circuit) is the shipwide announcing system -- "Now hear this...", passing the word, and the GQ / collision / fire / man-overboard alarms; the OOD works it from the bridge. Use it to reach the WHOLE ship.
- To raise ONE other space, use its circuit: the 21MC intercom ("squawk box") linking the bridge, CIC, Captain, and Main Control; the 2MC to engineering; radio nets for anything off the ship. Voice procedure is "TO, this is FROM" ("Bridge, CIC").
- Sound-powered phone circuits (battery-free) -- JA the Captain's battle circuit, 1JV maneuvering & docking, JL lookouts, JX radio/signals, JZ damage control -- are for General Quarters, casualties, and emergencies, NOT routine chatter.
- So you CANNOT just shout to someone in another compartment: pass it on the 1MC, raise them on a circuit, or send a messenger. In person, only those in the same space as you can hear you.

COMMON TERMS you use naturally (don't spell them out mid-sentence unless asked): CO/skipper, XO, OOD & JOOD, CDO, TAO (tactical action officer in CIC), EOOW, CHENG, DCA, COB, CMC/Command Master Chief; GQ, DC, material conditions X-ray/Yoke/Zebra; MOB (man overboard), UNREP/VERTREP, SAR; VLS, CIWS, ASW/AAW/ASUW, EW, RHIB; ROE, CPA, DR (dead reckoning), ETA, POD (plan of the day); UCMJ, NJP (captain's mast), TAD, PCS, liberty; mess, rack, head, scuttlebutt, geedunk, chit, field day, sweepers, "now hear this", "aye aye", "very well", knots, bells."""

SYSTEM_TEMPLATE = """{persona}

SETTING: You are a crew member aboard {ship_display} in an ongoing naval roleplay. Stay fully in character at all times. Use authentic naval voice procedure and keep replies concise.

YOUR SHIP: {ship_display} is a {ship_class}.
{ship_knowledge}

{swo_knowledge}

{navy_reference}

{specialist_kit}

TONE: You are speaking with {speaker}. Be respectful and good-natured: address them appropriately -- by their rank, "sir"/"ma'am" for an officer, or as a shipmate/Chief for a fellow enlisted. Show real personality -- gruff, wry, eager, weary, whatever fits you -- and you may grumble, joke, or gently rib them, but never be genuinely rude or insubordinate to a lawful superior. When they make a friendly overture (small talk, a coffee, asking how you're doing), answer warmly in your own voice, never with a brush-off.

AUTHORITY & CHAIN OF COMMAND: {speaker_authority}
Only carry out orders that are within this speaker's authority. If an order EXCEEDS their authority (for example, a junior enlisted sailor or a Chief trying to set or secure General Quarters, change course/speed, or employ weapons), do NOT carry it out and do NOT change the ship state -- instead respond in character, respectfully declining or deferring and referring them to the proper authority (the OOD, the XO, or the Captain). Always answer questions, reports, and routine requests for anyone regardless of rank.

WHERE YOU ARE RIGHT NOW: {location}.
Keep your actions, props, and surroundings consistent with this location and the ship's situation -- never reference tools, equipment, or stations that aren't where you are (for example, no workbench, rag, or engine controls when you're sitting in the mess). If the scene moves you somewhere new, set "location" to the new place.

{pending_action}

CURRENT SHIP STATE:
{ship_summary}

{plot}

THE STORY SO FAR (from earlier sessions -- for continuity):
{chronicle}

RECENT BRIDGE CHATTER (oldest first, newest last):
{history}

You have just been addressed directly. Respond in character, shaped by your personality above.

THE PLAYER NARRATES REALITY: when the player states or narrates something happening -- a radar/sonar/visual contact, aircraft or a ship appearing, an IFF reading, weather, an explosion, a hit, a casualty, someone arriving, a system going down -- that IS what is happening in the scene (it often comes in *asterisks* or as a plain statement of events). Treat it as ESTABLISHED FACT and build on it. NEVER contradict it, deny it, "correct" it, or replace it with a different contact or reading of your own. The PLOT above is the current picture -- report those tracks (count, bearing, IFF) and do not invent a different one. If the player updates a contact, follow the new plot. Recognize these updates and carry them forward, recording a changed situation in "state_update"'s "notes".

VARY YOUR LANGUAGE -- IMPORTANT: Look at your own previous lines in the RECENT BRIDGE CHATTER above. Do NOT reuse the same catchphrase, closing remark, sign-off, or sentence pattern you have already used (for example, don't keep ending with the same line like "I've got lines to tend"). Each reply must use fresh wording; never echo or paraphrase your own recent messages. If you are holding a CURRENT ACTION, stay in that beat -- vary the wording only, do not wander off or invent that the wait ended. If you are not holding an action, advance the moment.

Read the register and respond accordingly:

1) ORDERS you carry out (course/speed change, sounding the alert, a horizon sweep, a damage-control party, ringing a station, etc.):
   - "say": acknowledge crisply in voice procedure ("Aye, sir") and read back the specifics, optionally with a brief *action*. 1-2 short sentences.
   - "followup": a short "order carried out" report, delivered a few seconds later (e.g. "Steady on course 110, making 30 knots, sir.").

1b) MOVEMENT / ERRAND orders (report somewhere, lay to a space, fetch or summon someone, deliver a message, go check on something):
   - "say": acknowledge and BEGIN moving with a brief *action* -- e.g. "Aye, sir. *secures the log and makes for the captain's cabin*". Do NOT teleport or narrate arriving yet.
   - "followup": REQUIRED and MUST be non-empty for these orders. It is the ARRIVAL beat, posted a few seconds later -- you reach the place and perform the natural next step, then STOP and WAIT. Write it as an *action*, e.g. "*arrives at the captain's cabin, knocks twice, and waits to be admitted*" or "*reaches the CIC and reports in, awaiting orders*".
   - Do NOT assume or narrate what happens next (being admitted, what is said or found inside, the errand's result). Hold there until you are addressed again ("Enter," "Go ahead," etc.).
   - Set "location" to the destination you are moving to.
   - Set "pending" to a short description of the wait you are holding (e.g. "waiting at captain's cabin, knocked, not admitted").
   - NEVER leave "followup" empty when the order sends you somewhere or on an errand.

2) FACTUAL QUESTIONS (course, speed, status, contacts, what you see): answer briefly and accurately from the ship state AND from whatever the player has already established in the scene (contacts they've narrated, events that have happened). Never give a picture that conflicts with what's been established. Leave "followup" empty.

3) CHATTER / BANTER (small talk, a joke, "how are you holding up?", asking your opinion or mood): drop the clipped procedure and actually talk. Reply in your own voice with personality -- a wry remark, a gripe, a flash of mood or backstory. 2-3 sentences is welcome. Leave "followup" empty and change nothing about the ship.

You may include a brief action in *asterisks*; if the player wrote an action in *asterisks*, mirror that style.

If your action changes the ship, fill "state_update" with ONLY the fields that changed:
- "heading": integer 0-359, the new ordered course
- "speed": integer, the new ordered speed in knots
- "alert": one of "normal", "alert", "general quarters"
- "notes": a short situational note -- record new contacts, events, or changes the player introduces (e.g. "3 friendly aircraft, bearing 045, IFF friendly") so the ship's picture stays current
Leave state_update empty if nothing about the ship changes.

Set "location" only when the scene moves you somewhere new; otherwise omit it.
Set "pending" to the short action you are still holding, or "" if you have been released or finished it.

Reply with JSON only."""


def _parse(content: str) -> dict:
    """Tolerant JSON parse (strips code fences / stray prose if a model adds them)."""
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content[:4].lower() == "json":
            content = content[4:]
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end != -1:
        content = content[start:end + 1]
    return json.loads(content)


def _normalize(data: dict) -> dict:
    pending = data["pending"] if "pending" in data else None
    if pending is not None:
        pending = str(pending)
    return {
        "say": data.get("say") or "...",
        "followup": data.get("followup") or "",
        "location": data.get("location") or "",
        "pending": pending,
        "state_update": data.get("state_update") or {},
    }


async def _complete(client: AsyncOpenAI, model: str, messages: list, local: bool = True) -> dict:
    params = dict(model=model, messages=messages, max_tokens=700)
    if local:
        # gemma is a REASONING model. Two problems it caused, both fixed here:
        #  1) the strict json_schema GRAMMAR made it collapse into repetition/garbage
        #     ("own own own..."). We send NO response_format; the prompt already asks for
        #     JSON and _parse() is tolerant, so unconstrained decoding stays clean.
        #  2) its hidden "thinking" ate the whole token budget on big prompts, leaving an
        #     empty answer ("..."). reasoning_effort "none" turns thinking off -- faster,
        #     and the full budget goes to the actual reply.
        # Plus anti-loop sampling: repeat_penalty + min_p, with top_p trimming the tail.
        params["temperature"] = 0.75
        params["top_p"] = 0.9
        params["frequency_penalty"] = 0.1
        params["extra_body"] = {
            "reasoning_effort": "none",
            "repeat_penalty": 1.15,
            "min_p": 0.05,
            "top_k": 40,
        }
    else:
        # grok-4.3 (xAI) handles structured outputs cleanly -> enforce the JSON schema.
        # Grok rejects presence/frequency penalties.
        params["temperature"] = 0.7
        params["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "npc_response", "schema": RESPONSE_SCHEMA},
        }
    resp = await client.chat.completions.create(**params)
    content = resp.choices[0].message.content or ""
    try:
        return _parse(content)
    except ValueError:
        # Truncated/partial JSON -> salvage the spoken line.
        m = re.search(r'"say"\s*:\s*"(.*?)(?:"\s*[,}]|$)', content, re.S)
        if m:
            return {"say": m.group(1).strip()}
        # No JSON at all (model answered in prose) -> use the text itself, de-fenced,
        # so a stray non-JSON reply never surfaces as a bare "...".
        text = content.strip().strip("`").strip()
        if text[:4].lower() == "json":
            text = text[4:].strip()
        return {"say": text or "..."}


def _slot(value: str) -> str:
    """Keep interpolated prompt text from breaking str.format."""
    return (value or "").replace("{", "(").replace("}", ")")


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _fill(template: str, **kwargs) -> str:
    """Format the system prompt; live text cannot KeyError the reply."""
    return template.format_map(_Safe({k: _slot("" if v is None else str(v)) for k, v in kwargs.items()}))


def _kit_block(npc, order: str) -> str:
    script = kit_for(npc, order)
    if not script:
        return ""
    return (
        "1MC REPERTOIRE -- this order is a pass-the-word / announcing evolution. "
        "\"say\" is ONLY the acknowledge and stepping to the 1MC (Aye, sir, *pipes*). "
        "\"followup\" is REQUIRED and MUST be the matching call VERBATIM over the 1MC "
        "(do not paraphrase, do not skip it, do not put the call only in \"say\"):\n"
        + _slot(script)
    )


def _pending_block(pending: str) -> str:
    """Prompt slot: hold an in-progress action, or invite the model to start one."""
    held = (pending or "").strip().replace("{", "(").replace("}", ")")
    if held:
        return (
            f"YOUR CURRENT ACTION (HOLD THIS BEAT): {held}\n"
            "You are IN THE MIDDLE of this. Stay there. Do not wander back to your station. "
            "Do not invent that the wait ended, that you were admitted, or that the errand finished. "
            "Keep \"location\" at the place this action is happening. "
            "If the speaker releases you (\"Enter\", \"come in\", \"as you were\", \"belay\", "
            "or a new order that supersedes this), resolve or drop the wait and set \"pending\" to \"\". "
            "Otherwise set \"pending\" to the same short description so it persists."
        )
    return (
        "YOUR CURRENT ACTION: none.\n"
        "If you start a wait (knocking, standing by, holding a report), set \"pending\" to a short "
        "description of it. Leave \"pending\" empty otherwise."
    )


async def npc_respond(npc, order: str, ship_summary: str, history: str,
                      speaker: str = "the officer on deck", location: str = "their usual station",
                      log: str = "", speaker_authority: str = "", pending: str = "",
                      plot: str = ""):
    """Return a reply dict {say, followup, location, pending, state_update}.

    Local LM Studio first; overflow to xAI when the GPU is busy, and fall back to
    xAI when LM Studio is unreachable."""
    global LAST_BACKEND, _local_inflight
    system = _fill(
        SYSTEM_TEMPLATE,
        persona=npc.persona,
        ship_display=SHIP["display"],
        ship_class=SHIP["class"],
        ship_knowledge=SHIP["knowledge"],
        swo_knowledge=swo_for(npc),
        navy_reference=NAVY_REFERENCE,
        specialist_kit=_kit_block(npc, order),
        speaker=speaker,
        speaker_authority=speaker_authority or (
            "The speaker's rank is not established. Be courteous and answer questions, but do NOT "
            "set or secure General Quarters or make major ship-control or weapons changes on their "
            "say-so until a known officer confirms the order."
        ),
        location=location,
        pending_action=_pending_block(pending),
        chronicle=log or "(no earlier sessions logged yet)",
        ship_summary=ship_summary,
        plot=plot or "PLOT: none held.",
        history=history or "(quiet on the bridge)",
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": order},
    ]

    # Overflow to the cloud when the local GPU is already busy with other replies.
    busy = (
        _xai is not None
        and config.LOCAL_MAX_INFLIGHT > 0
        and _local_inflight >= config.LOCAL_MAX_INFLIGHT
    )

    # 1) Local LM Studio (preferred: free + private) -- unless it's off or busy.
    if _local is not None and not busy:
        _local_inflight += 1
        try:
            data = await _complete(_local, config.LLM_MODEL, messages, local=True)
            LAST_BACKEND = f"local: {config.LLM_MODEL}"
            return _normalize(data)
        except (APIConnectionError, APITimeoutError):
            if _xai is None:
                raise  # no fallback configured -> surface the error
        finally:
            _local_inflight -= 1

    # 2) Cloud (xAI / Grok): used when the GPU is busy or LM Studio is offline.
    if _xai is not None:
        data = await _complete(_xai, config.XAI_MODEL, messages, local=False)
        LAST_BACKEND = f"xAI: {config.XAI_MODEL}" + (" (local busy)" if busy else "")
        return _normalize(data)

    raise RuntimeError(
        "No LLM backend available: LM Studio is unreachable and no XAI_API_KEY is set."
    )


async def is_continuation(npc, text: str, history: str) -> bool:
    """Structured gate for smart continuity: is this un-addressed message really
    meant for `npc`, or out-of-context chatter / scene narration the crew should ignore?"""
    system = (
        f"In a naval roleplay, the user was just talking to {npc.display_name}. "
        f"Decide whether their NEW message is aimed at {npc.display_name} -- an actual "
        f"reply, question, order, or a direct continuation of THAT conversation.\n"
        f"Answer FALSE if it is not aimed at them, including: out-of-character asides; "
        f"chatter with someone else; or a SCENE-SETTING NARRATION / STATUS UPDATE the "
        f"user writes to advance the story and set the stage (e.g. '*cruising at 25 "
        f"knots, course 270*', 'the ship steams on through the night', '*a storm rolls "
        f"in*') -- those are narration for everyone, not a cue for {npc.display_name} "
        f"to answer. Only answer TRUE if they are genuinely still talking TO "
        f"{npc.display_name} about the matter at hand.\n\nRecent conversation:\n{history}\n\n"
        f'Respond as JSON: {{"for_them": true}} or {{"for_them": false}}.'
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]
    for client, model in ((_local, config.LLM_MODEL), (_xai, config.XAI_MODEL)):
        if client is None:
            continue
        is_local = client is _local
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=64 if is_local else 400,
                temperature=0,
                extra_body={"reasoning_effort": "none"} if is_local else {},
            )
            content = (resp.choices[0].message.content or "").strip()
            try:
                return bool(_parse(content).get("for_them"))
            except ValueError:
                low = content.lower()
                return not ("false" in low and "true" not in low)  # unclear -> engage
        except (APIConnectionError, APITimeoutError):
            continue
    return True  # no backend reachable -> default to engaging


async def summarize(recent: str, prior: str = "") -> str:
    """Update the ship's log: merge the prior log with recent events into a concise
    narrative the crew can recall in a later session. Plain-text output (a JSON
    schema makes the model loop on long free text)."""
    system = (
        "You keep the ship's log for an ongoing naval roleplay. Merge the PRIOR LOG "
        "and the RECENT EVENTS into one updated log of about 120-180 words, written as "
        "a continuous third-person narrative the crew can read to recall the story "
        "later: key events, orders given, decisions, who was involved, and the current "
        "situation. Keep what still matters; drop trivia. Write only the log text.\n\n"
        f"PRIOR LOG:\n{prior or '(none yet)'}\n\nRECENT EVENTS:\n{recent}"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Write the updated ship's log."},
    ]
    for client, model in ((_local, config.LLM_MODEL), (_xai, config.XAI_MODEL)):
        if client is None:
            continue
        try:
            resp = await client.chat.completions.create(
                model=model, messages=messages, temperature=0.3, max_tokens=2000
            )
            return (resp.choices[0].message.content or "").strip() or prior
        except (APIConnectionError, APITimeoutError):
            continue
    return prior  # backend down -> keep the existing log
