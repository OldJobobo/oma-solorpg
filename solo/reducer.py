"""How a campaign's events fold into its state, and the line each event is told in.

initial_state is the state before anything happened, and apply puts one event onto it. replay runs a
log through apply and keeps the chronology beside it: the moments of each event that matter later.
describe and gm_line tell an event in one line, to the player and to the GM. The rest reads the state
and the chronology without changing them: the codex, the route, what burning momentum would do,
whether a consequence's moment has come, recall.

Nothing here reads or writes a file, looks at the clock or rolls a die: the state is fold(packs,
events) and nothing else, which is why `solo rebuild` makes state.json again from the log alone. A long
campaign keeps what this module made of its log's first events (.solo/replay.marshal) and starts from
it while the log, the packs and the engine's files are the ones it was made from, this file among them.
That kept replay is only valid while this module stays pure: a fold that read anything but the packs
and the events would give the kept replay and a replay from the start two different states. So nothing
here does I/O (of packs it uses only what reads no file), and nothing here imports the campaign or the
code that reads and writes its folder.
"""

import copy
import json
import unicodedata

from . import SoloError, mechanics, oracle, packs
from .packs import ATTITUDES

LIKELIHOOD = {
    "impossible": 5, "very unlikely": 15, "unlikely": 30, "even": 50,
    "likely": 70, "very likely": 85, "certain": 95,
}
# What a player can learn about an NPC besides its secrets (by id): the codex blanks them out until then.
LEARNABLE = ("wants", "fears")
_LOG_SIZE = 40
# The Book's feed: speech and what the player saw happen, oldest first.
_STORY_SIZE = 150
# What the story going on is, after a roll: a commit, a move, time passing in a rest or on the road, a torch lit,
# a fight begun, gone on a round or ended. The roll before it stands as it fell, and can't be pushed any more.
_GOES_ON = ("commit", "move", "rest", "journey", "light", "fight", "round", "fight_end")


# Folding events into state --------------------------------------------------------

def fold(system, adventure, events):
    state = initial_state(system, adventure)
    for event in events:
        _replay(state, event, adventure)
    return state


def replay(system, adventure, events, state=None, entries=None):
    """The state after the events, and the chronology (see `chronology`), in one pass: from the
    start, or from a state and a chronology already replayed up to the first of them."""
    if state is None:
        state, entries = initial_state(system, adventure), []
    for event in events:
        _advance(state, entries, event, adventure)
    return state, entries


def _advance(state, entries, event, adventure, strict=False):
    """One event on the state, and its entry in the chronology. A new event the state can't take
    is refused (`strict`); one already in the log is passed over and said so (`_replay`)."""
    seen = set(state["visited"])
    was_dead = bool(state["pc"] and state["pc"]["dead"])
    if strict:
        apply(state, event, adventure)
    else:
        _replay(state, event, adventure)
    entries.append({"seq": event["seq"], "event": event, "time": state["time"], "scene": state["scene"],
                    "title": state["scene_title"], "moments": _moments(event, state, adventure, seen, was_dead)})


def _replay(state, event, adventure):
    """`apply` for an event already in the log. The packs are read afresh each time, and one
    edited since (a clock renamed, an NPC taken out) may no longer hold what an old event
    names: that event is passed over and said so, rather than locking the player out."""
    try:
        apply(state, event, adventure)
    except KeyError as error:
        state["problems"].append(f"#{event['seq']} {event['type']} was passed over: the packs no longer have {error}")


def burn_option(state):
    """What burning momentum would do to the roll just made, when it would do anything:
    {momentum, reset, hit}. The table and the GM's report offer the burn from this, so
    neither computes a rule."""
    last, momentum = state["last_check"], ((state["pc"] or {}).get("tracks") or {}).get("momentum")
    burned = None
    if last and last["type"] == "act" and last["seq"] == state["open_roll"] and "track" not in last and momentum and momentum["value"] > 0:
        burned = mechanics.burn(last["outcome"], momentum["value"])
    if burned:
        return {"momentum": momentum["value"], "reset": momentum["reset"], "hit": burned["hit"]}
    else:
        return None


def codex(adventure, state):
    """The people the hero has met, as the player knows them. Wants, fears and secrets
    stay blanked out (counted under `unknown`) until a commit's `learn` reveals them;
    a foe's numbers show once the hero has fought it."""
    entries = []
    for npc_id, npc in state["npcs"].items():
        if not npc["met"]:
            continue
        profile = profile_of(adventure, state, npc_id)
        learned = set(state["learned"])
        known = {k: profile[k] for k in LEARNABLE if profile.get(k) and f"{npc_id}.{k}" in learned}
        secrets = [s.get("text", "") for s in profile.get("secrets", []) if f"{npc_id}.{s.get('id')}" in learned]
        knowable = sum(1 for k in LEARNABLE if profile.get(k)) + len(profile.get("secrets", []))
        stats = profile.get("stats", {})
        entries.append({
            "id": npc_id, "name": npc["name"], "role": profile.get("role", ""),
            "faction": state["factions"].get(npc.get("faction") or "", {}).get("name", ""),
            "attitude": next((name for name, value in ATTITUDES.items() if value == npc["attitude"]), str(npc["attitude"])),
            "fate": npc["fate"], "memories": npc["memories"], "known": known, "secrets": secrets,
            "unknown": knowable - len(known) - len(secrets),
            "fought": npc.get("fought", False),
            "stats": {"hp": stats.get("hp"), "armor": stats.get("armor", 0)} if npc.get("fought") and "hp" in stats else None,
        })
    return entries


def chronology(system, adventure, events):
    """The campaign as it happened, replayed from the log: one entry per event, with where the
    hero was and the game time after it, and the moments in it that matter to the story later
    (arrivals, people met and what they now think, fates, promises, consequences, gear won and
    lost, fights, deaths, the chronicle). The GM's long memory is read from this, so it holds
    for campaigns begun before it existed, and needs no one to have written anything down."""
    return replay(system, adventure, events)[1]


def moments(entries, after=0, kinds=None):
    """The moments of a chronology after a seq, flat, oldest first: {seq, time, scene, title,
    kind, text, npcs}."""
    return [{"seq": e["seq"], "time": e["time"], "scene": e["scene"], "title": e["title"], **m}
            for e in entries if e["seq"] > after for m in e["moments"] if kinds is None or m["kind"] in kinds]


def _moments(event, state, adventure, seen, was_dead):
    kind, changes = event["type"], event.get("changes") or {}
    name = lambda npc_id: state["npcs"].get(npc_id, {}).get("name", npc_id)
    found = []

    def say(what, text, npcs=()):
        found.append({"kind": what, "text": text, "npcs": list(npcs)})

    if kind == "created":
        say("begin", f"{event['pc']['name']} begins {event['title']}")
    if kind in ("created", "move"):
        back = state["scene"] in seen
        say("return" if back else "arrive", f"{'came back to' if back else 'reached'} {state['scene_title']}", people_here(adventure, state))
    elif kind == "hero":
        say("hero", f"{event['pc']['name']} takes up the story")
    elif kind == "commit":
        if changes.get("note"):
            say("note", changes["note"], changes.get("npc", {}))
        if changes.get("chronicle"):
            say("chronicle", changes["chronicle"])
        if changes.get("end"):
            say("end", f"the adventure ends: {changes['end']}")
    elif kind == "stage":
        say("stage", f"{event['label']} reached {event['at']}/{event['segments']}: {event.get('text') or event.get('note') or ''}".rstrip(": "))
    elif kind in ("fight", "join"):
        say("fight", ("a fight: " if kind == "fight" else "joining the fight: ") + ", ".join(f["name"] for f in event["foes"].values()),
            {f["npc"] for f in event["foes"].values()})
    elif kind in ("damage", "wound", "ally") and event.get("down"):
        say("fight", f"{event.get('name') or event.get('target_name')} down")
    elif kind == "fight_end" and event.get("standing"):
        say("fight", f"the fight ends; still standing: {', '.join(event['standing'])}")
    elif kind == "threat" and event["action"] in ("add", "triggered"):
        say("threat", f"a threat looms: {event['label']}" if event["action"] == "add" else f"a threat came to pass: {event.get('text') or event['label']}")
    elif kind == "clock" and event.get("full") and not event.get("stopped"):
        say("clock", f"{event['label']} filled")
    elif kind == "progress" and event["action"] in ("add", "end"):
        say("progress", _progress_text(event))
    elif kind == "advance" and any(r["now"] > r["was"] for r in event["results"]):
        say("advance", "grew: " + ", ".join(f"{r['name']} {r['now']}" for r in event["results"] if r["now"] > r["was"]))
    elif kind == "due":
        say("due", f"a consequence came due: {event['text']}", [event["npc"]] if event.get("npc") else [])
    if kind in ("commit", "stage"):
        for npc_id, change in changes.get("npc", {}).items():
            bits = []
            if "fate" in change and change["fate"] != change.get("fate_was"):
                bits.append(change["fate"])
            if "attitude" in change and change["attitude"] != change.get("attitude_was"):
                bits.append(f"now {_attitude_word(change['attitude'])}")
            if change.get("location"):
                bits.append(f"now at {adventure['scenes'].get(change['location'], {}).get('title', change['location'])}")
            if change.get("memory"):
                bits.append(f"remembers: {_memory(change['memory'])}")
            if change.get("new"):
                role = (change.get("profile") or {}).get("role")
                say("npc", "; ".join([f"met {name(npc_id)}" + (f", {role}" if role else ""), *bits]), [npc_id])
            elif bits:
                say("npc", f"{name(npc_id)}: {'; '.join(bits)}", [npc_id])
        for faction_id, change in changes.get("faction", {}).items():
            bits = [f"now {_attitude_word(change['standing'])}"] if change["standing"] != change["standing_was"] else []
            bits += [f"heard: {_memory(change['memory'])}"] if change.get("memory") else []
            if bits:
                say("faction", f"{state['factions'].get(faction_id, {}).get('name', faction_id)}: {'; '.join(bits)}")
        for promise in changes.get("promise", {}).values():
            if promise["status"] != promise.get("status_was"):
                say("promise", f"a promise to {name(promise['npc'])} ({promise['status']}): {promise['terms']}", [promise["npc"]])
        for consequence_id, change in changes.get("consequence", {}).items():
            if change["status"] != change.get("status_was"):
                text = state["consequences"].get(consequence_id, {}).get("text", "")
                say("consequence", f"consequence {consequence_id} ({change['status']}): {text}",
                    [state["consequences"][consequence_id]["npc"]] if state["consequences"].get(consequence_id, {}).get("npc") else [])
        pc = changes.get("pc", {})
        if pc.get("items_add") or pc.get("items_remove"):
            say("gear", "; ".join(filter(None, [pc.get("items_add") and "gained " + ", ".join(pc["items_add"]),
                                                pc.get("items_remove") and "lost " + ", ".join(pc["items_remove"])])))
        if changes.get("learn"):
            say("learn", "found out " + ", ".join(changes["learn"]), {k.partition(".")[0] for k in changes["learn"]})
    if state["pc"] and state["pc"]["dead"] and not was_dead:
        say("death", f"{state['pc']['name']} died" + (f" ({state['last_blow']})" if state.get("last_blow") else ""))
    return found


def recall(entries, state, query, limit=8):
    """Everything the campaign holds that mentions these words: every message said at the
    table, the GM's notes, facts, memories, what word has spread, consequences, oracle
    answers, table results, the chronicle, and the hero's earlier adventures. Best matches
    first (the most words found), newest first among equals. Accents and case don't count."""
    words = [w for w in _fold(query).split() if len(w) > 2] or _fold(query).split()
    if not words:
        raise SoloError("recall what? give a word or two: solo recall smith hammer")
    found = []
    for entry in entries:
        for label, text in _recallable(entry["event"], state):
            folded, folded_label = _fold(text), _fold(label)
            # The label counts too: "Bram remembers" is about Bram, whatever he remembers.
            hits = sum(1 for w in words if w in folded or w in folded_label)
            if hits:
                found.append({"hits": hits, "seq": entry["seq"], "time": entry["time"], "title": entry["title"],
                              "label": label, "text": _snippet(text, folded, words)})
    for number, record in enumerate(state.get("past") or [], 1):
        for label, text in [("the ending", record.get("ended") or ""), *[("chronicle", t) for t in record.get("chronicle", [])],
                            *[("left open", t) for t in record.get("loose_ends", [])], *[("people", t) for t in record.get("people", [])]]:
            folded = _fold(text)
            hits = sum(1 for w in words if w in folded)
            if hits:
                found.append({"hits": hits, "seq": 0, "time": None, "title": record.get("title", f"adventure {number}"),
                              "label": f"before this adventure, {label}", "text": _snippet(text, folded, words)})
    found.sort(key=lambda f: (-f["hits"], -f["seq"]))
    best = found[0]["hits"] if found else 0
    # When some matches hold every word, the ones that hold only a few are noise.
    return [f for f in found if f["hits"] == best or best < len(words)][:limit]


def _recallable(event, state):
    """(label, text) for what an event put into the story in words."""
    kind, changes = event["type"], event.get("changes") or {}
    npc_name = lambda npc_id: state["npcs"].get(npc_id, {}).get("name", npc_id)
    if kind == "said":
        return [] if event["seq"] in state["struck"] else [("you said" if event["by"] == "gm" else "the player said", event["text"])]
    elif kind in ("oracle", "meaning"):
        answer = event.get("answer") or " / ".join(event.get("words", []))
        return [("the oracle", f"{event.get('question') or 'meaning'}: {answer}")]
    elif kind == "table":
        return [(event["name"], event["text"])]
    elif kind == "voice" and event["heard"]:
        return [(event["label"], event["text"])]
    elif kind == "threat" and event["action"] in ("add", "triggered"):
        return [("threat", event.get("text") or event["label"])]
    elif kind == "due":
        return [("came due", event["text"])]
    elif kind == "progress" and event["action"] in ("add", "end"):
        return [("a vow, road or fight", _progress_text(event))]
    items = []
    if kind == "stage":
        items += [(event["label"], " ".join(filter(None, [event.get("text"), event.get("note")])))]
    if kind in ("commit", "stage"):
        items += [(key, changes[key]) for key in ("note", "chronicle", "end") if changes.get(key)]
        items += [("fact", f"{k}: {v}") for k, v in changes.get("facts", {}).items()]
        for npc_id, change in changes.get("npc", {}).items():
            items += [(f"{npc_name(npc_id)} remembers", _memory(change["memory"]))] if change.get("memory") else []
            items += [(f"{npc_name(npc_id)}, {field}", text) for field, text in (change.get("profile") or {}).items()]
            items += [("met", f"{npc_name(npc_id)} ({npc_id})")] if change.get("new") else []
        for faction_id, change in changes.get("faction", {}).items():
            items += [(f"{state['factions'].get(faction_id, {}).get('name', faction_id)} heard", _memory(change["memory"]))] if change.get("memory") else []
        for promise_id, promise in changes.get("promise", {}).items():
            items += [(f"promise {promise_id} ({promise['status']})", f"{npc_name(promise['npc'])}: {promise['terms']}")]
        for consequence_id, change in changes.get("consequence", {}).items():
            items += [(f"consequence {consequence_id}", change["text"])] if change.get("text") else []
        items += [("gained", item) for item in changes.get("pc", {}).get("items_add", [])]
    return items


def _fold(text):
    """Lowercase, accents gone, one character for one, so a match found in the folded text
    points at the same place in the original: Kjölvik is kjolvik. Most of what a campaign holds
    is plain ASCII, which lower() alone folds; the rest goes a character at a time, each worked
    out once (recall folds every word ever said, and that was most of its time)."""
    text = str(text)
    return text.lower() if text.isascii() else text.translate(_FOLDED)


class _Folded(dict):
    """A character's code point to the character it folds to, worked out when first asked for."""

    def __missing__(self, point):
        ch = chr(point)
        self[point] = folded = (unicodedata.normalize("NFKD", ch)[:1] or ch).lower()[:1]
        return folded


_FOLDED = _Folded()


def _snippet(text, folded, words, before=90, after=170):
    at = min((folded.find(w) for w in words if w in folded), default=0)
    start, end = max(0, at - before), min(len(text), at + after)
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    return ("..." if start else "") + " ".join(text[start:end].split()) + ("..." if end < len(text) else "")


def _attitude_word(value):
    return next((name for name, number in ATTITUDES.items() if number == value), str(value))


def route(adventure, state):
    """The scenes visited, in order, each with how many of its ways on are still unexplored
    (never where they lead: that would spoil scenes the hero hasn't reached). A way that
    hasn't opened yet (hidden stairs) isn't counted, or the map would give it away."""
    visited = state["visited"]
    return [
        {"id": sid, "title": adventure["scenes"][sid].get("title", sid), "here": sid == state["scene"],
         "unexplored": sum(1 for target, spec in packs.exits(adventure, sid).items()
                           if target not in visited and packs.is_open(spec, state))}
        for sid in visited if sid in adventure["scenes"]
    ]


def initial_state(system, adventure):
    return {
        "seq": 0,
        "title": adventure["title"],
        "system": system["name"],
        "family": system["family"],
        "labels": {
            "attributes": system["attributes"],
            "tracks": system["tracks"],
            "conditions": list(system["conditions"]),
            "push": system["push"].get("cost", "condition"),
            # limit: seconds per time unit, so the panel can tell a rest taken this shift
            "rests": {
                rid: {"label": r.get("label", rid.capitalize()), "limit": system["time"].get(r.get("limit")), **({"tend": True} if r.get("tend") else {})}
                for rid, r in system["rest"].items()
            },
            # A heroic ability that pays for a push instead of a condition (Sole Survivor): name and cost.
            "push_ability": next(({"name": a.get("name", aid), "cost": ", ".join(f"{v} {t.upper()}" for t, v in a["push"].items())}
                                  for aid, a in system.get("abilities", {}).items() if a.get("push")), None),
            "likelihood": (["unlikely", "even", "likely"] if system.get("oracle", {}).get("chart") == "fortune"
                           else _odds_levels(system) if system.get("oracle", {}).get("chart") == "odds" else list(LIKELIHOOD)),
            # The fortune chart's columns (yes_no, number, scale ...), when the system has one.
            "fortune": [k for k in system.get("oracle", {}).get("fortune", {}) if k != "bands"] or None,
            # Death rolls and advancement, when the system has them.
            "dying": _dying_rules(system),
            "advancement": list(system.get("advancement", {}).get("mark_on", [])) if system.get("advancement") else None,
            # action-roll systems: momentum's range, the progress tracks a game keeps (and what a
            # mark fills at each rank) and the moves the hero can make, for the panel's buttons.
            "momentum": system.get("momentum") or None,
            "progress": system.get("progress") or None,
            "moves": {move_id: {k: move[k] for k in ("name", "kind", "category", "stats", "pick", "track") if k in move}
                      for move_id, move in system.get("moves", {}).items()} or None,
        },
        "scene": None,
        "scene_title": None,
        "visited": [],
        "time": 0,
        "pc": None,
        "npcs": {
            nid: {
                "name": npc.get("name", nid), "faction": npc.get("faction"), "fate": npc.get("fate", "alive"),
                "attitude": _attitude(npc.get("attitude", 0)), "location": npc.get("location"),
                "met": False, "fought": False, "memories": [],
            }
            for nid, npc in adventure["npcs"].items()
        },
        "factions": {
            fid: {"name": f.get("name", fid), "standing": int(f.get("standing", 0)), "memories": []}
            for fid, f in adventure["factions"].items()
        },
        "promises": {},
        # Progress tracks (vows, journeys, fights, bonds): {id: {name, kind, rank, ticks, ended}}.
        "progress": {},
        # What the hero did that will come back: {id: text, npc, at, when, due_at, status, due ...}. GM only.
        "consequences": {},
        # How many times the hero has come into a scene, so a consequence can wait for the next time.
        "arrivals": 0,
        # The hero's earlier adventures, when they came from another campaign (see `hero`).
        "past": [],
        "clocks": {
            cid: {
                "label": c.get("label", cid), "value": 0, "segments": int(c.get("segments", 1)),
                "full": False, "hidden": bool(c.get("hidden", False)), "stopped": False,
            }
            for cid, c in adventure["clocks"].items()
        },
        "facts": {},
        "clues": [],
        "chronicle": [],
        "rests": {},
        "last_check": None,
        # The seq of an action roll the player could still burn momentum on, until the story goes on.
        "open_roll": None,
        # 1-9: how likely surprises are. The GM raises it when the story runs away from the hero.
        "chaos": int(adventure.get("chaos", 5)),
        "combat": None,
        # The shifts the hero has travelled on the day the game is in: {day, shifts}.
        "travel": {"day": 0, "shifts": 0},
        # A Dragon waiting for the player's choice: {of: the roll's seq, kind: attack or spell, options, target}.
        "choice": None,
        # The player's table settings, read by the GM every session.
        "prefs": {"tone": "", "lines": [], "veils": []},
        # Set when the hero dies or the GM commits an "end".
        "ended": None,
        # The GM's last words to the player, and whether the player has answered them. `gm_said` keeps the
        # last few, so cutting the latest brings back the one before as "last said".
        "last_said": None,
        "gm_said": [],
        # The seqs of GM messages the player cut (an X-card): the Book and `solo recall` leave them out.
        "struck": [],
        "awaiting_player": False,
        # The torch (or other light) burning now: {source, label, lit_at, burns}.
        "light": None,
        # What the player has found out about NPCs (learn in a commit), for the codex.
        "learned": [],
        # Lines the hero's skills said in this scene (voices heard).
        "voices": [],
        # For the epitaph: the player's last words and who dealt the last blow.
        "last_player_said": None,
        "last_blow": None,
        "fallen": None,
        # Heroes who came before this one in the same story (a death, then a replacement).
        "heroes": [],
        "story": [],
        "log": [],
        # Every event the player never saw, by seq: the log keeps only the last few.
        "hidden": [],
        # Events the replay passed over, because the packs no longer hold what they name.
        "problems": [],
    }


def apply(state, event, adventure):
    kind = event["type"]
    state["seq"] = event["seq"]
    if kind == "said":
        # Speech stays out of the dice log: the panel shows it in its own card, the Book in its story.
        if event["by"] == "gm":
            state["last_said"] = {k: event[k] for k in ("seq", "at", "scene", "text")}
            state["gm_said"] = (state["gm_said"] + [state["last_said"]])[-8:]
        else:
            state["last_player_said"] = event["text"]
        state["awaiting_player"] = event["by"] == "gm"
        _tell(state, {"seq": event["seq"], "kind": event["by"], "text": event["text"]})
        return
    if kind == "struck":
        # The log keeps the words (it is append-only); the Book and the GM's memory of the table lose them.
        state["struck"].append(event["target"])
        state["story"] = [b for b in state["story"] if not (b.get("kind") == "gm" and b.get("seq") == event["target"])]
        state["gm_said"] = [m for m in state["gm_said"] if m["seq"] != event["target"]]
        state["last_said"] = state["gm_said"][-1] if state["gm_said"] else None
        state["awaiting_player"] = False
        return
    fight = state["combat"]
    if kind == "created":
        state["pc"] = {**copy.deepcopy(event["pc"]), "marks": [], "dying": None, "dead": False, "damaged": {}}
        state["past"] = copy.deepcopy(event.get("past") or [])
        state["facts"].update(event.get("facts") or {})
        # Every hero keeps the unranked tracks (bonds); a hero carried from another campaign brings theirs.
        for track_kind, label in ((state["labels"]["progress"] or {}).get("unranked") or {}).items():
            state["progress"][track_kind] = {"name": label, "kind": track_kind, "rank": None, "ticks": (event.get("kept") or {}).get(track_kind, 0), "ended": None}
        _enter(state, event["scene"], adventure)
    elif kind == "hero":
        old = state["pc"]
        state["heroes"].append({"name": old["name"], "info": old["info"], "fate": "died" if old["dead"] else "stepped aside",
                                "fallen": state["fallen"]})
        state["pc"] = {**copy.deepcopy(event["pc"]), "marks": [], "dying": None, "dead": False, "damaged": {}}
        state.update(ended=None, fallen=None, last_blow=None, last_check=None, voices=[])
        if event.get("npc") in state["npcs"]:
            state["npcs"][event["npc"]].update(fate="gone", location=None)
    elif kind == "move":
        state["time"] += event.get("time") or 0
        _enter(state, event["to"], adventure)
    elif kind == "check":
        state["last_check"] = event
        _mark(state, event)
        if event.get("defend") and event["outcome"]["success"] and fight:
            fight["incoming"] = None
    elif kind == "push":
        _apply_changes(state, event["changes"], event)
        state["last_check"] = event
        _mark(state, event)
    elif kind == "journey":
        _apply_changes(state, event["changes"], event)
        state["travel"] = {"day": event["day"], "shifts": event["shifts"]}
    elif kind in ("ability", "spell", "spell_effect", "prepare"):
        _apply_changes(state, event["changes"], event)
    elif kind == "learn":
        _apply_changes(state, event["changes"], event)
        if event.get("mark") in state["pc"]["marks"]:
            state["pc"]["marks"].remove(event["mark"])
    elif kind == "choice":
        state["choice"] = {"of": event["of"], "kind": event.get("kind", "attack"), "options": event["options"], "target": event.get("target")}
    elif kind == "dragon":
        state["choice"] = None
    elif kind == "heal" and fight:
        fight["foes"][event["target"]].update(hp=event["hp"])
    elif kind == "act":
        state["last_check"] = event
        state["open_roll"] = event["seq"] if event.get("open") else None
    elif kind == "burn":
        _apply_changes(state, event["changes"], event)
        state["last_check"] = event
        state["open_roll"] = None
    elif kind == "settled":
        state["open_roll"] = None
    elif kind == "progress":
        _track(state["progress"], event)
    elif kind == "stage":
        _apply_changes(state, event["changes"], event)
    elif kind in ("commit", "harm"):
        if kind == "harm":
            state["last_blow"] = event.get("by")
            if fight:
                # Only the blow that was coming (it has a source) is answered by this; a stone
                # falling on the hero mid-fight leaves the foe's axe still on its way.
                if event.get("source"):
                    fight["incoming"] = None
                fight["last"] = {"seq": event["seq"], "from": event.get("source"), "to": "pc", "hit": True, "dealt": event["dealt"], "text": describe(event)}
        _apply_changes(state, event["changes"], event)
    elif kind == "durability":
        if event["broke"]:
            state["pc"].setdefault("damaged", {})[event["weapon"]] = "broken"
        elif event.get("damaged"):
            state["pc"].setdefault("damaged", {}).setdefault(event["weapon"], "damaged")
    elif kind == "repair":
        state["pc"].setdefault("damaged", {}).pop(event["weapon"], None)
    elif kind == "rally":
        if event["rallied"] and state["pc"]["dying"]:
            state["pc"]["dying"]["rallied"] = True
    elif kind == "save_self":
        _apply_changes(state, event["changes"], event)
    elif kind == "death_roll":
        _dying(state, event, successes=event["successes"], failures=event["failures"])
        _apply_changes(state, event["changes"], event)
    elif kind == "fight":
        state["combat"] = {"round": event["round"], "foes": copy.deepcopy(event["foes"]), "order": event["order"], "incoming": None}
    elif kind == "join" and fight:
        fight["foes"].update(copy.deepcopy(event["foes"]))
        fight["order"] = event["order"]
    elif kind == "round" and fight:
        fight.update(round=event["round"], order=event["order"])
        state["time"] += event.get("time") or 0
    elif kind == "fight_end":
        state["combat"] = None
        state["choice"] = None
    elif kind == "damage" and fight:
        fight["foes"][event["target"]].update(hp=event["hp"], down=event["down"])
        fight["last"] = {"seq": event["seq"], "from": "pc", "to": event["target"], "hit": True, "dealt": event["dealt"], "text": describe(event)}
    elif kind == "wound" and fight:
        fight["foes"][event["target"]].update(hp=event["hp"], down=event["down"])
        fight["last"] = {"seq": event["seq"], "from": "pc", "to": event["target"], "hit": True, "dealt": event["dealt"], "text": describe(event)}
    elif kind == "ally" and fight:
        if "dealt" in event:
            fight["foes"][event["target"]].update(hp=event["hp"], down=event["down"])
        # Drawn from the hero's side of the tableau, like the hero's own blows.
        fight["last"] = {"seq": event["seq"], "from": "pc", "to": event["target"], "hit": "dealt" in event, "dealt": event.get("dealt", 0), "text": describe(event)}
        state["npcs"][event["npc"]]["met"] = True
    elif kind == "enemy" and fight:
        fight["incoming"] = event.get("incoming")
        fight["foes"][event["foe"]]["last_attack"] = event.get("index")
        pending = fight.setdefault("pending", {})
        if event.get("queued"):
            pending[event["foe"]] = event["queued"]
        else:
            pending.pop(event["foe"], None)
        if not event.get("incoming"):
            fight["last"] = {"seq": event["seq"], "from": event["foe"], "to": "pc", "hit": False, "dealt": 0, "text": describe(event)}
    elif kind == "voice":
        if event["heard"]:
            state["voices"].append({"label": event["label"], "text": event["text"]})
            if event.get("clue") and event["clue"] not in state["clues"]:
                state["clues"].append(event["clue"])
    elif kind == "light":
        _apply_changes(state, event.get("changes", {}), event)
        state["light"] = {"source": event["source"], "label": event["label"], "lit_at": state["time"], "burns": event["burns"]} if event["lit"] else None
    elif kind == "mark":
        state["pc"]["marks"].append(event["skill"])
    elif kind == "advance":
        for result in event["results"]:
            state["pc"]["skills"][result["skill"]]["value"] = result["now"]
        state["pc"]["marks"] = []
    elif kind == "prefs":
        state["prefs"] = {k: event[k] for k in ("tone", "lines", "veils")}
    elif kind == "rest":
        state["rests"][event["rest"]] = state["time"]
        _apply_changes(state, event["changes"], event)
    elif kind == "clock":
        state["clocks"][event["clock"]].update(value=event["value"], full=event["full"], stopped=bool(event.get("stopped")))
    elif kind == "threat" and event["action"] == "add":
        state["clocks"][event["clock"]] = {
            "label": event["label"], "value": event["value"], "segments": event["segments"], "full": False,
            "hidden": False, "stopped": False, "threat": {"recurring": bool(event.get("recurring")), "text": event.get("text") or event["label"]},
        }
    elif kind == "threat" and event["action"] == "end":
        state["clocks"][event["clock"]]["stopped"] = True
    elif kind == "due" and event["consequence"] in state["consequences"]:
        state["consequences"][event["consequence"]]["due"] = True
    if kind in _GOES_ON and (state["last_check"] or {}).get("outcome", {}).get("pushable"):
        # The story went on: the roll stands as it fell, and its push is no longer on offer (the panel reads pushable).
        last = state["last_check"]
        state["last_check"] = {**last, "outcome": {**last["outcome"], "pushable": False}, "stood": True}
    if kind in ("fight", "join"):
        for foe in event["foes"].values():
            if foe["npc"] in state["npcs"]:
                state["npcs"][foe["npc"]].update(met=True, fought=True)
    if kind in ("check", "push") and fight and (event.get("attack") or event.get("defend")) and not event["outcome"]["success"]:
        attack = event.get("attack")
        fight["last"] = ({"seq": event["seq"], "from": "pc", "to": attack["target"], "hit": False, "dealt": 0, "text": describe(event)} if attack
                         else fight.get("last"))
    entry = {"seq": event["seq"], "type": kind, "text": describe(event)}
    if kind == "clock":
        entry["clock"] = event["clock"]
    # The player's panel skips hidden clocks and the tables their ticks roll, unless the
    # clock is an omen clock: then what its tick rolls is felt, though the clock stays hidden.
    cause = next((e for e in state["log"] if e["seq"] == event.get("cause")), None) if kind == "table" else None
    omen = cause is not None and bool(adventure["clocks"].get(cause.get("clock", ""), {}).get("omen"))
    hidden_clock = kind == "clock" and state["clocks"][event["clock"]]["hidden"]
    hidden_cause = cause is not None and cause.get("hidden") and not omen
    if kind == "stage":
        # A stage of a hidden clock stays hidden, unless it is an omen clock with something to feel.
        spec = adventure["clocks"].get(event["clock"], {})
        omen = bool(spec.get("omen") and event.get("text"))
        hidden_clock = state["clocks"][event["clock"]]["hidden"] and not omen or not event.get("text")
    # A consequence coming due is the GM's, and so is a commit with nothing the player can see
    # (facts, a consequence): the table's log would only say "commit".
    gm_only = kind in ("due", "settled") or (kind == "commit" and entry["text"] == "commit")
    if hidden_clock or hidden_cause or gm_only or (kind == "voice" and not event["heard"]):
        entry["hidden"] = True
        state["hidden"].append(event["seq"])
    elif omen:
        entry["omen"] = True
    state["log"] = (state["log"] + [entry])[-_LOG_SIZE:]
    if not entry.get("hidden"):
        _tell(state, _story_entry(state, event, entry))


def _enter(state, scene_id, adventure):
    scene = adventure["scenes"].get(scene_id, {})
    state["scene"] = scene_id
    state["scene_title"] = scene.get("title", scene_id)
    state["voices"] = []
    state["arrivals"] = state.get("arrivals", 0) + 1
    if scene_id not in state["visited"]:
        state["visited"].append(scene_id)
    for npc_id in people_here(adventure, state):
        state["npcs"][npc_id]["met"] = True


def people_here(adventure, state):
    """Who is in the current scene: the people its text lists, unless the story has since put
    them somewhere else (a committed location wins over the adventure's lists), and anyone the
    story has put here."""
    scene_id = state["scene"]
    listed = [nid for nid in adventure["scenes"].get(scene_id, {}).get("npcs", []) if nid in state["npcs"]]
    here = [nid for nid in listed if state["npcs"][nid].get("location") in (None, scene_id)]
    return here + [nid for nid, npc in state["npcs"].items() if npc.get("location") == scene_id and nid not in here]


def profile_of(adventure, state, npc_id):
    """An NPC as the GM knows them: the adventure's profile (a bestiary monster under it, when
    it names one), what a commit made them in play (a monster), and what the GM wrote down
    about one it made up (role, looks, voice, wants, fears)."""
    live = state["npcs"].get(npc_id, {})
    profile = adventure["npcs"].get(npc_id, {})
    monster = (adventure.get("bestiary") or {}).get(live.get("monster") or "")
    if monster:
        profile = packs._layered(monster, profile)
    return {**profile, **(live.get("profile") or {})}


def ready(adventure, state, consequence):
    """Whether a consequence's moment has come. `at`, `when` and `after` must all hold, those
    it names; with none of them, `npc` alone says when: the next time the hero meets them.
    `at` and `npc` count only from the hero's next arrival somewhere, so a consequence made
    in front of the smith waits for the hero to come back. With no trigger at all it is a
    loose end the GM keeps in mind, never announced."""
    if consequence["status"] != "open":
        return False
    later = state["arrivals"] > consequence["arrivals"]
    timed = [consequence.get(k) for k in ("at", "when", "due_at") if consequence.get(k) not in (None, [])]
    if consequence["at"] and not (later and state["scene"] in consequence["at"]):
        return False
    elif consequence["due_at"] is not None and state["time"] < consequence["due_at"]:
        return False
    elif consequence["when"]:
        try:
            if not packs.evaluate(consequence["when"], state):
                return False
        except SoloError:
            return False
    if timed:
        return True
    npc = state["npcs"].get(consequence["npc"] or "")
    return bool(npc and later and npc["fate"] == "alive" and consequence["npc"] in people_here(adventure, state))


def _apply_changes(state, changes, event):
    state["facts"].update(changes.get("facts", {}))
    for npc_id, change in changes.get("npc", {}).items():
        if change.get("new") and npc_id in state["npcs"] and "location" not in change:
            # Someone the GM made up in play whom the pack has written down since (a generated
            # campaign's next mission brings them back): met here, as when the GM made them up.
            state["npcs"][npc_id]["location"] = state["scene"]
        npc = state["npcs"].setdefault(npc_id, {
            "name": change.get("name", npc_id), "faction": None, "fate": "alive", "attitude": 0,
            "location": state["scene"], "met": True, "memories": [],
        })
        npc.update({k: change[k] for k in ("name", "faction", "fate", "attitude", "location", "template", "attacker", "monster") if k in change})
        npc["met"] = True
        if change.get("memory"):
            npc["memories"].append(_memory(change["memory"]))
        if change.get("profile"):
            npc["profile"] = {**npc.get("profile", {}), **change["profile"]}
    for faction_id, change in changes.get("faction", {}).items():
        faction = state["factions"].setdefault(faction_id, {"name": change.get("name", faction_id), "standing": 0, "memories": []})
        faction["standing"] = change["standing"]
        if change.get("memory"):
            faction.setdefault("memories", []).append(_memory(change["memory"]))
    for promise_id, promise in changes.get("promise", {}).items():
        state["promises"][promise_id] = {k: promise[k] for k in ("npc", "terms", "status")}
    for consequence_id, change in changes.get("consequence", {}).items():
        consequence = state["consequences"].setdefault(consequence_id, {
            "text": "", "npc": None, "at": [], "when": None, "due_at": None, "status": "open",
            "made": event["seq"], "scene": state["scene"], "arrivals": 0, "due": False,
        })
        consequence.update({k: v for k, v in change.items() if k != "status_was"})
    pc = state["pc"]
    update = changes.get("pc", {})
    for track, value in update.get("tracks", {}).items():
        pc["tracks"][track]["value"] = value
    pc["conditions"] = [c for c in pc["conditions"] if c not in update.get("conditions_remove", [])]
    pc["conditions"] += [c for c in update.get("conditions_add", []) if c not in pc["conditions"]]
    for track, more in update.get("max_up", {}).items():
        # An ability that raises a track's ceiling (Robust: hit points) raises what the hero has by as much.
        pc["tracks"][track]["max"] += more
        pc["tracks"][track]["value"] += more
    for item in update.get("items_remove", []):
        if item in pc["items"]:
            pc["items"].remove(item)
    pc["items"] += update.get("items_add", [])
    pc["abilities"] = [a for a in pc["abilities"] if a not in update.get("abilities_remove", [])] + update.get("abilities_add", [])
    for key in ("spells", "prepared"):
        pc[key] = [a for a in pc.get(key, []) if a not in update.get(f"{key}_remove", [])] + update.get(f"{key}_add", [])
    if update.get("conditions_add") or update.get("conditions_remove"):
        _fit_momentum(state)
    state["time"] += changes.get("time", 0)
    state["clues"] += [c for c in changes.get("clues", []) if c not in state["clues"]]
    state["learned"] += [k for k in changes.get("learn", []) if k not in state["learned"]]
    if changes.get("chronicle"):
        state["chronicle"].append({"seq": event["seq"], "at": event["at"], "text": changes["chronicle"]})
    if changes.get("chaos"):
        state["chaos"] = changes["chaos"]["value"]
    if changes.get("end"):
        state["ended"] = {"seq": event["seq"], "at": event["at"], "text": changes["end"]}
    if pc["dead"] and changes.get("override") and update.get("tracks"):
        pc["dead"] = False
        state["ended"] = None
        state["fallen"] = None
    _dying(state, event, failures=update.get("death_failures", 0))


def _fit_momentum(state):
    """Each impact lowers momentum's ceiling and its reset; what the hero holds stays under it."""
    spec, momentum = state["labels"]["momentum"], state["pc"]["tracks"].get("momentum")
    if spec and momentum:
        momentum.update(mechanics.momentum_limits(spec, len(state["pc"]["conditions"])))
        momentum["value"] = min(momentum["value"], momentum["max"])


def _track(tracks, event):
    """A progress event: a track started, marked, corrected or closed."""
    if event["action"] == "add":
        tracks[event["id"]] = {"name": event["name"], "kind": event["kind"], "rank": event.get("rank"), "ticks": 0, "ended": None}
    elif event["action"] == "end":
        tracks[event["id"]]["ended"] = event["how"]
    else:
        tracks[event["id"]].update(event["now"])


def _tell(state, entry):
    if entry:
        state["story"] = (state["story"] + [entry])[-_STORY_SIZE:]


# What each event looks like in the Book. Commits are the GM's bookkeeping and stay out:
# the GM narrates them. Everything here is already in the player's log.
_STORY_KINDS = {
    "check": "roll", "push": "roll", "act": "roll", "burn": "roll", "progress": "event", "death_roll": "roll", "rally": "roll", "save_self": "roll", "voice": "voice", "damage": "hit", "wound": "hit", "harm": "hurt",
    "enemy": "foe", "ally": "hit", "oracle": "oracle", "meaning": "oracle", "fight": "fight", "join": "fight", "round": "fight",
    "fight_end": "fight", "rest": "event", "light": "light", "advance": "event", "mark": "event", "roll": "event",
    "table": "event", "clock": "clock", "threat": "event",
}


def _story_entry(state, event, entry):
    kind = event["type"]
    if kind in ("created", "move"):
        story = {"kind": "scene", "scene": state["scene"], "title": state["scene_title"]}
    elif kind == "hero":
        story = {"kind": "event", "text": entry["text"]}
    elif kind == "commit" and event["changes"].get("end"):
        story = {"kind": "end", "text": event["changes"]["end"]}
    elif kind in ("table", "stage") and entry.get("omen"):
        story = {"kind": "omen", "text": event["text"]}
    elif kind == "stage":
        story = {"kind": "event", "text": event["text"]}
    elif kind in _STORY_KINDS:
        story = {"kind": _STORY_KINDS[kind], "text": entry["text"]}
    else:
        return None
    if kind in ("check", "push", "death_roll", "voice", "rally", "save_self"):
        outcome = event["outcome"]
        story.update(label=event["label"], pushed=kind == "push", death=kind in ("death_roll", "save_self"),
                     outcome={k: outcome[k] for k in ("result", "target", "success", "dragon", "demon", "rolls", "successes", "groups", "triggers") if k in outcome},
                     boons=event.get("boons", 0), banes=event.get("banes", 0))
        if kind == "voice":
            story["text"] = event["text"]
        elif event.get("attack"):
            foe = ((state["combat"] or {}).get("foes") or {}).get(event["attack"]["target"], {})
            story["purpose"] = f"{event['attack']['label']} at {foe.get('name', event['attack']['target'])}"
        elif event.get("defend"):
            story["purpose"] = event["defend"]["how"]
    elif kind in ("act", "burn"):
        story.update(label=event["label"], burned=kind == "burn", outcome=event["outcome"],
                     purpose=f"+{event['stat']}" if event.get("stat") else event.get("track_name"))
    elif kind in ("damage", "wound", "harm"):
        story.update(dealt=event["dealt"], down=event.get("down", False))
    if "seed" in event:
        story["seed"] = event["seed"]
    return {"seq": event["seq"], **story}


def _odds_levels(system):
    """The odds an odds oracle reads, least likely first."""
    return [level for level, chance in sorted(system["oracle"]["odds"].items(), key=lambda level: level[1])]


def _dying_rules(system):
    spec = system.get("dying")
    if spec:
        return {"track": spec["track"], "rally": int(spec.get("rally", 3)), "die": int(spec.get("die", 3)),
                "self_rally": bool(spec.get("self_rally")), "self_save": bool(spec.get("self_save"))}
    else:
        return None


def _dying(state, event, successes=0, failures=0):
    """At 0 on the dying track the hero starts dying; above it they stop. Counts past the
    pack's limits end it one way or the other (a rally restores the track in the same event)."""
    rules, pc = state["labels"]["dying"], state["pc"]
    if not rules or pc["dead"]:
        return
    elif pc["tracks"][rules["track"]]["value"] > 0:
        pc["dying"] = None
    elif pc["dying"] is None:
        pc["dying"] = {"successes": 0, "failures": 0}
    else:
        pc["dying"]["successes"] += successes
        pc["dying"]["failures"] += failures
        if pc["dying"]["failures"] >= rules["die"]:
            pc.update(dying=None, dead=True)
            state["ended"] = {"seq": event["seq"], "at": event["at"], "text": f"{pc['name']} died."}
            state["fallen"] = {"at": event["at"], "scene": state["scene_title"], "by": state["last_blow"], "epitaph": state["last_player_said"]}


def _mark(state, event):
    """A Dragon or Demon on a skill roll marks the skill for advancement."""
    mark_on = state["labels"]["advancement"]
    outcome = event["outcome"]
    if mark_on and event["kind"] == "skill" and any(outcome.get(m) for m in mark_on) and event["stat"] not in state["pc"]["marks"]:
        state["pc"]["marks"].append(event["stat"])


def describe(event):
    """One line per event, for the log and the panel."""
    kind = event["type"]
    if kind == "created":
        return f"{event['pc']['name']} begins {event['title']}"
    elif kind == "move":
        text = f"moved to {event['to']}" + (f" (forced: {event['forced']})" if event.get("forced") else "")
        check = event.get("scene_check") or {}
        if check.get("result") == "altered":
            text += f" (scene check {check['roll']}: altered)"
        elif check.get("result") == "interrupted":
            text += f" (scene check {check['roll']}: interrupted. {oracle.describe_event(check['event'])})"
        return text
    elif kind in ("check", "push"):
        attack, defend = event.get("attack"), event.get("defend")
        cast = event.get("cast")
        purpose = (f" (attack {attack['target']} with {attack['label']})" if attack else f" ({defend['how']})" if defend
                   else f" (casting {cast['name']}, power {cast['power']})" if cast else "")
        text = ("pushed " if kind == "push" else "") + f"{event['label']}{purpose}: {_outcome_text(event)}"
        return text + (_push_cost(event.get("changes") or {}) if kind == "push" else "")
    elif kind == "act":
        return _act_text(event)
    elif kind == "burn":
        outcome = event["outcome"]
        return (f"burned momentum {outcome['burned']} on {event['label']}: it cancels {len(outcome['cancelled'])} of the challenge dice, "
                f"{_HITS[outcome['hit']]} now; momentum back to {event['changes']['pc']['tracks']['momentum']}")
    elif kind == "progress":
        return _progress_text(event)
    elif kind == "settled":
        return "the roll stands"
    elif kind == "roll":
        return f"rolled {event['expr']} = {event['result']['total']}" + (f" ({event['reason']})" if event.get("reason") else "")
    elif kind == "table":
        return f"{event['name']} ({event['total']}): {event['text']}"
    elif kind == "oracle" and event.get("chart") == "odds":
        text = f"asked \"{event['question']}\" (odds {event['likely']}, rolled {event['roll']}): {event['answer']}"
        return text + (" (a match: an extreme result or a twist)" if event.get("match") else "")
    elif kind == "oracle" and event.get("chart") == "fortune":
        tilt = {"high": ", likely high", "low": ", likely low"}.get(event.get("tilt"), "")
        text = f"asked \"{event['question']}\" (fortune, {event['kind'].replace('_', '/')}{tilt}, rolled {event['roll']}): {event['answer']}"
        return text + (" (an extreme result, or a twist)" if event.get("extreme") else "")
    elif kind == "oracle":
        text = f"asked \"{event['question']}\" ({event['likely']}, rolled {event['roll']}): {event['answer']}"
        return text + (f". Random event: {oracle.describe_event(event['random_event'])}" if event.get("random_event") else "")
    elif kind == "meaning":
        return (f"meaning of \"{event['question']}\"" if event.get("question") else "meaning") + f": {' / '.join(event['words'])}"
    elif kind == "fight":
        return "fight: " + _order_text(event["order"])
    elif kind == "join":
        return f"{', '.join(f['name'] for f in event['foes'].values())} join the fight: " + _order_text(event["order"])
    elif kind == "round":
        return f"round {event['round']}: " + _order_text(event["order"])
    elif kind == "fight_end":
        return "the fight ends" + (f"; still standing: {', '.join(event['standing'])}" if event["standing"] else "")
    elif kind == "damage" and event.get("immune"):
        return f"{event['weapon']} hits {event['name']}: no effect (only {event['immune']} can harm it)"
    elif kind == "damage":
        how = {"counter": " (a counterattack)", "pierce": " (through the armor)"}.get(event.get("how"), "")
        how += {"half": f" ({event.get('kind') or 'that'} damage is halved)", "immune": f" (immune to {event.get('kind') or 'that'})"}.get(event.get("resisted"), "")
        text = f"{event['weapon']} hits {event['name']}{how}: {event['roll']['total']} - armor {event['armor']} = {event['dealt']} damage"
        return text + (", down!" if event["down"] else f", HP {event['hp']}")
    elif kind == "wound":
        if event.get("roll") is None:
            return f"{event['why']}: {event['name']} is down!"
        amount = f"{event['roll']['total']}" + (" x2" if event.get("double") else "") + (f" - armor {event['armor']}" if event["armor"] else "")
        return f"{event['why']}: {amount} = {event['dealt']} damage to {event['name']}" + (", down!" if event["down"] else f", HP {event['hp']}")
    elif kind == "enemy":
        if "outcome" in event:
            outcome = event["outcome"]
            verdict = "Dragon!" if outcome["dragon"] else "Demon!" if outcome["demon"] else "hits" if outcome["success"] else "misses"
            text = f"{event['name']} attacks ({event['label']}, {outcome['result']} vs {outcome['target']}): {verdict}"
            return text + (f"; {event['incoming']['damage']} damage coming" if event.get("incoming") else "")
        text = f"{event['name']} ({event['total']}): {event['text']}"
        again = " (the same attack twice in a row, so the next on the table)" if event.get("again") else ""
        return text.rstrip(". ") + again + (f" ({event['incoming']['damage']} damage coming)" if event.get("incoming") else "")
    elif kind == "ally":
        outcome = event["outcome"]
        verdict = "Dragon!" if outcome["dragon"] else "Demon!" if outcome["demon"] else "hits" if outcome["success"] else "misses"
        text = f"{event['name']} attacks {event['target_name']} ({event['label']}, {outcome['result']} vs {outcome['target']}): {verdict}"
        if "dealt" in event:
            text += f"; {event['roll']['total']} - armor {event['armor']} = {event['dealt']} damage" + (", down!" if event["down"] else f", HP {event['hp']}")
        return text
    elif kind == "journey":
        return event["changes"]["note"] + (" (a forced march: Exhausted)" if event.get("forced") else "") + (f"; {event['left']} to go" if event["left"] else "; arrived")
    elif kind == "spell":
        body = f", {event['body']} drawn from the body" if event.get("body") else ""
        metal = f" (metal at hand: {', '.join(event['metal'])}: the rules say magic fails around it)" if event.get("metal") else ""
        return f"casts {event['name']} at power {event['power']} for {event['cost']} WP{body}{metal}"
    elif kind == "spell_effect":
        return event["changes"].get("note", "a spell's effect")
    elif kind == "prepare":
        return f"prepares {event['name']}" + (f", putting {event['dropped']} aside" if event.get("dropped") else "")
    elif kind == "learn":
        return (f"learns {event['name']}" if event.get("learned", True) else f"fails to learn {event['name']}")
    elif kind == "ability":
        paid = ", ".join(f"{n} {t.upper()}" for t, n in (event.get("cost") or {}).items())
        return f"uses {event['name']}" + (f" (pays {paid})" if paid else "")
    elif kind == "choice":
        return f"a Dragon on the blow: choose {', '.join(event['options'])} (solo dragon <choice>)"
    elif kind == "defence":
        how = {"dodge": "dodges", "parry": "parries"}[event["how"]]
        against = ", against a critical hit" if event.get("critical") else ""
        return f"{event['name']} {how} ({event['outcome']['result']} vs {event['outcome']['target']}{against}): " + ("the blow is avoided" if event["avoided"] else "the blow lands")
    elif kind == "heal":
        return f"{event['name']} heals {event['hp'] - event['hp_was']} HP by {event['by']}: HP {event['hp']}"
    elif kind == "dragon":
        return {"double": "the Dragon doubles the damage", "attack": "the Dragon gives a second attack on another foe",
                "pierce": "the Dragon finds a gap in the armor", "free": "the Dragon pays for the spell",
                "another": "the Dragon lets the mage cast another spell at once, with a bane"}[event["choice"]]
    elif kind == "durability" and event.get("damaged"):
        return f"{event['label']} is damaged: a bane on every use until it is repaired"
    elif kind == "durability":
        how = {"parry": "takes the parried blow", "armor": "takes the blow the armor stopped"}[event["how"]]
        return f"{event['label']} {how} ({event['expr']} = {event['damage']} against durability {event['durability']}): " + ("it breaks!" if event["broke"] else "it holds")
    elif kind == "repair":
        return f"{event['label']} is mended by {event['by'].lower() if event['by'][:1].isupper() and ' ' not in event['by'] else event['by']}"
    elif kind == "harm":
        sums = f"{event['roll']['total']} - armor {event['armor']} = " if event["armor"] else ""
        return f"{event['changes'].get('note', 'hit')}: {sums}{event['dealt']} damage"
    elif kind == "death_roll":
        tally = f"{event['successes']} success{'es' * (event['successes'] != 1)}, {event['failures']} failure{'s' * (event['failures'] != 1)}"
        after = {"rallies": ": rallies!", "dies": ": dies."}.get(event.get("result"), "")
        return f"death roll ({event['label']}, {_outcome_text(event)}): {tally}{after}"
    elif kind == "rally":
        return f"rallies alone ({event['label']}, {_outcome_text(event)})" + (": back on their feet, still dying" if event["rallied"] else "")
    elif kind == "save_self":
        return f"tries to save their own life ({event['label']}, {_outcome_text(event)})" + (": saved!" if event["saved"] else "")
    elif kind == "mark":
        return f"marked {event['label']} for advancement" + (f" ({event['reason']})" if event.get("reason") else "")
    elif kind == "advance":
        return "advancement: " + "; ".join(
            f"{r['name']} {r['was']} -> {r['now']} (rolled {r['roll']})" if r["now"] > r["was"] else f"{r['name']} stays {r['was']} (rolled {r['roll']})"
            for r in event["results"]
        )
    elif kind == "prefs":
        return "table settings changed"
    elif kind == "hero":
        return f"{event['pc']['name']} takes up the story"
    elif kind == "threat":
        if event["action"] == "triggered":
            return "the threat comes to pass: " + (event.get("text") or event["label"])
        return {"add": "a threat looms: ", "end": "the threat is gone: "}[event["action"]] + event["label"]
    elif kind == "stage":
        # Only what the player notices: the GM's note travels separately (gm_line).
        return event.get("text") or f"{event['label']} {event['at']}/{event['segments']}"
    elif kind == "clock" and event.get("stopped"):
        return f"{event['label']} stops at {event['value']}/{event['segments']}"
    elif kind == "clock":
        return f"{event['label']} {event['value']}/{event['segments']}" + (", full" if event["full"] else "")
    elif kind in ("commit", "rest"):
        return _commit_text(event["changes"])
    elif kind == "voice":
        return f"{event['label']} ({_outcome_text(event)}): " + (event["text"] if event["heard"] else "stays silent")
    elif kind == "light":
        label = event["label"].lower()
        return f"lit a {label}" if event["lit"] else f"put out the {label}" if event.get("reason") == "put out" else f"the {label} burns out"
    elif kind == "said":
        first = " ".join(event["text"].split())
        return ("GM" if event["by"] == "gm" else "Player") + f': "{first[:77] + "..." if len(first) > 80 else first}"'
    elif kind == "struck":
        kept = event.get("committed") or []
        return (f"the player cut your message #{event['target']}: it is gone from their Book. Don't repeat it or come back to it"
                + (f" (they said: {event['note']})" if event.get("note") else "")
                + (f". What you committed in that turn still stands unless you retract it in the story: {'; '.join(kept)}" if kept else ""))
    elif kind == "due":
        return f"a consequence comes due ({event['consequence']}): {event['text']}"
    else:
        return kind


def gm_line(event):
    """An event as the GM reads it: the player's line, plus what only the GM should read (what
    a clock's stage asks of them, facts, consequences, what word has spread)."""
    notes = [event["note"]] if event.get("note") else []
    changes = event.get("changes") or {}
    if changes.get("facts"):
        notes.append("facts " + ", ".join(f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in changes["facts"].items()))
    for faction_id, change in changes.get("faction", {}).items():
        if change.get("memory"):
            notes.append(f"{faction_id} heard: {_memory(change['memory'])}")
    for consequence_id, change in changes.get("consequence", {}).items():
        notes.append(f"consequence {consequence_id} {change['status']}" + (f": {change['text']}" if change.get("text") else ""))
    return describe(event) + "".join(f" [for the GM: {note}]" for note in notes)


_HITS = {"strong_hit": "a strong hit", "weak_hit": "a weak hit", "miss": "a miss"}


def _act_text(event):
    """A move's roll on one line: what it added up to, against which dice, and the result."""
    outcome = event["outcome"]
    against = f"against {outcome['challenge'][0]} and {outcome['challenge'][1]}"
    if "progress" in outcome:
        text = f"{event['label']} ({event['track_name']}): {outcome['progress']} boxes filled {against}"
    else:
        die = f"{outcome['action']} (cancelled by negative momentum)" if outcome["dulled"] else str(outcome["action"])
        adds = f" + {outcome['adds']}" if outcome["adds"] else ""
        text = f"{event['label']} +{event['stat']}: {die} + {outcome['stat']}{adds} = {outcome['score']} {against}"
    return f"{text}: {_HITS[outcome['hit']]}" + (", and the dice match: a twist" if outcome["match"] else "")


def filled(boxes, part):
    """What a progress track holds: "4 boxes and 2 ticks", "1 tick", "nothing yet"."""
    held = [f"{n} {word}{'es' if word == 'box' and n != 1 else 's' if n != 1 else ''}" for n, word in ((boxes, "box"), (part, "tick")) if n]
    return " and ".join(held) or "nothing yet"


def _progress_text(event):
    name = event["name"]
    if event["action"] == "add":
        return f"{event['kind']} begun: {name}" + (f" ({event['rank']})" if event.get("rank") else "")
    elif event["action"] == "mark":
        return f"progress on {name}: {filled(event['boxes'], event['part'])}" + (f" (marked {event['times']} times)" if event["times"] > 1 else "")
    elif event["action"] == "set":
        changes = [f"{key} {event['was'][key]} -> {value}" for key, value in event["now"].items() if value != event["was"][key]]
        return f"{name} set: {', '.join(changes) or 'no change'}"
    else:
        return f"{name} ends: {event['how']}"


def _outcome_text(event):
    outcome = event["outcome"]
    extras = []
    if event.get("boons"):
        extras.append(f"boons {event['boons']}")
    if event.get("banes"):
        extras.append(f"banes {event['banes']}" + (f" [{', '.join(event['gear_banes'])}]" if event.get("gear_banes") else ""))
    if "result" in outcome:
        verdict = "Dragon!" if outcome["dragon"] else "Demon!" if outcome["demon"] else "success" if outcome["success"] else "failure"
        text = f"{outcome['result']} vs {outcome['target']}, {verdict}"
    else:
        hits = outcome["successes"]
        text = f"{hits} success{'es' * (hits != 1)}" + (f", {', '.join(outcome['triggers'])}!" if outcome["triggers"] else "")
    return text + (f" ({', '.join(extras)})" if extras else "")


def _push_cost(changes):
    """What pushing took: "; took angry", "; paid 3 WP" (Sole Survivor) or "; STRESS +1"
    (Alien). A push recorded before the old value was kept says what the track came to."""
    pc = changes.get("pc", {})
    was = pc.get("tracks_was", {})
    parts = [f"took {c}" for c in pc.get("conditions_add", [])]
    for track, now in pc.get("tracks", {}).items():
        if track not in was:
            parts.append(f"{track.upper()} now {now}")
        elif now < was[track]:
            parts.append(f"paid {was[track] - now} {track.upper()}")
        else:
            parts.append(f"{track.upper()} +{now - was[track]}")
    return f"; {', '.join(parts)}" if parts else ""


def _commit_text(changes):
    parts = [changes["note"]] if changes.get("note") else []
    for npc_id, change in changes.get("npc", {}).items():
        if "attitude" in change:
            parts.append(f"{npc_id} attitude {change['attitude_was']} -> {change['attitude']}")
        if "fate" in change:
            parts.append(f"{npc_id} {change['fate']}")
    for faction_id, change in changes.get("faction", {}).items():
        if change["standing"] != change["standing_was"]:
            parts.append(f"{faction_id} standing {change['standing_was']} -> {change['standing']}")
    for promise_id, promise in changes.get("promise", {}).items():
        parts.append(f"promise {promise_id} {promise['status']}")
    pc = changes.get("pc", {})
    for track, value in pc.get("tracks", {}).items():
        parts.append(f"{track} {pc['tracks_was'][track]} -> {value}")
    parts += [f"+{c}" for c in pc.get("conditions_add", [])] + [f"-{c}" for c in pc.get("conditions_remove", [])]
    parts += [f"+{i}" for i in pc.get("items_add", [])] + [f"-{i}" for i in pc.get("items_remove", [])]
    parts += [f"learns {a}" for a in pc.get("abilities_add", [])] + [f"loses {a}" for a in pc.get("abilities_remove", [])]
    if changes.get("time"):
        parts.append(f"{_duration(changes['time'])} pass")
    if changes.get("learn"):
        parts.append(f"learned {', '.join(changes['learn'])}")
    if changes.get("chronicle"):
        parts.append("chronicle entry")
    if changes.get("chaos"):
        parts.append(f"chaos {changes['chaos']['was']} -> {changes['chaos']['value']}")
    if changes.get("end"):
        parts.append("the adventure ends")
    return "; ".join(parts) or "commit"


def _order_text(order):
    return ", ".join(f"{f['name']} ({f['card']})" for f in order)


def _duration(seconds):
    if seconds % 3600 == 0:
        return f"{seconds // 3600} h"
    elif seconds % 60 == 0:
        return f"{seconds // 60} min"
    else:
        return f"{seconds} s"


def _memory(value):
    """A memory as the line of text it is, its line breaks folded into spaces: on a line of its own, its "## Loose ends"
    would be a heading in what the next GM reads. A log written before memories were checked may hold a list: its lines, joined."""
    return "; ".join(" ".join(str(line).split()) for line in (value if isinstance(value, list) else [value]))


def _attitude(value):
    return ATTITUDES[value] if isinstance(value, str) else int(value)
