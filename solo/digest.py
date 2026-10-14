"""What the GM and the player read about the table, as text: the scene digest, where the table
stopped, a person's card, what the campaign recalls and its whole story, and the lines they are
made of (the hero, a clock, the fight, how long ago). `solo scene`, `resume`, `npc`, `recall` and
`history` print it, and the Book's first prompt carries the first two. It lives apart from the
commands, so what the GM reads can be found and changed in one place."""

import json

from . import SoloError, campaign, combat, oracle, packs
from .packs import ATTITUDES


def scene_digest(c):
    """What the GM needs for this turn. GM-only text stays inside its ::: gm fences."""
    state, adventure = c.state, c.adventure
    scene_id = state["scene"]
    scene = adventure["scenes"][scene_id]
    lines = [f"# {scene.get('title', scene_id)} ({scene_id})", ""]
    lines += _prefs_lines(state)
    lines += _problem_lines(c)
    if state["ended"]:
        lines += [f"The adventure has ended: {state['ended']['text']}", ""]
    if scene.get("climax"):
        lines += ["This is a climax scene.", ""]
    lines += _scene_check_lines(c)
    lines += [packs.scene_text(adventure, scene_id).strip(), ""]
    lines += _light_lines(c)
    if state["voices"]:
        lines += ["## What the hero noticed (their skills spoke up; the player has read these)",
                  *[f"- {v['label']}: {v['text']}" for v in state["voices"]], ""]
    lines += _back_here_lines(c)
    lines += _due_lines(c)
    true_now = [b["text"] for b in scene.get("branches", []) if packs.evaluate(b["when"], state)]
    if true_now:
        lines += ["## True now", *[f"- {text}" for text in true_now], ""]
    every = packs.exits(adventure, scene_id)
    shut = {sid: spec for sid, spec in every.items() if not packs.is_open(spec, state)}
    lines += ["## Exits", *([f"- {sid}: {spec['label']}" + _travel(c, spec) for sid, spec in every.items() if sid not in shut] or ["- none"]), ""]
    if shut:
        lines += ["## Closed for now (GM only: don't mention a way the hero hasn't found)",
                  *[f"- {sid}: {spec['label']}; opens when {spec['when']}" for sid, spec in shut.items()], ""]
    here = campaign.people_here(adventure, state)
    # The text may name someone the story has since taken elsewhere: they aren't here any more.
    moved = [nid for nid in scene.get("npcs", []) if nid in state["npcs"] and nid not in here]
    if here or moved:
        lines += ["## People here", *[_npc_line(c, nid) for nid in here]]
        if moved:
            lines.append("- Not here any more, though the text names them (the story has put them elsewhere): " + ", ".join(
                f"{state['npcs'][nid]['name']} (now at {_scene_title(c, state['npcs'][nid]['location'])})" for nid in moved))
        lines.append("")
    if scene.get("tables"):
        lines += ["## Tables for this scene", *[f"- {t}" for t in scene["tables"]], ""]
    if state["clocks"]:
        lines += ["## Clocks", *[_clock_line(c, cid) for cid in state["clocks"]], ""]
    lines += _fact_lines(c)
    if state["combat"]:
        lines += ["## Fight", *[f"- {line}" for line in _now(c) if not line.startswith("ended")], ""]
    lines += _progress_lines(state)
    chaos = [] if c.system.get("oracle", {}).get("chart") in ("fortune", "odds") else [f"Chaos factor: {state['chaos']}"]
    story = _hero_story(state)
    load = combat.encumbrance(c.system, state["pc"])
    lines += ["## Character", _pc_line(state), *([f"Load: {load['carried']:g} of {load['capacity']}" + ("; OVER-ENCUMBERED (solo rule encumbrance)" if load["over"] else "")] if load else []),
              _skills_line(state), *(["Their story (hero.* facts): " + "; ".join(story)] if story else []), *chaos, ""]
    nudge = _chronicle_nudge(c)
    if nudge:
        lines += ["## Your chronicle", nudge, ""]
    recent = [e for e in c.events if e["type"] != "said"][-6:]
    lines += ["## Recent", *[f"- #{e['seq']} {campaign.gm_line(e)}" for e in recent]]
    return "\n".join(lines)


def _back_here_lines(c):
    """A place the hero comes back to holds what they left there. How long they were away,
    and what happened here before, from the log."""
    state, entries = c.state, c.chronology()
    arrivals = [e for e in entries if any(m["kind"] in ("arrive", "return") for m in e["moments"])]
    if not arrivals or arrivals[-1]["scene"] != state["scene"]:
        return []
    now = arrivals[-1]
    before = [a for a in arrivals[:-1] if a["scene"] == state["scene"]]
    if not before:
        return []
    after_last = next(a for a in arrivals if a["seq"] > before[-1]["seq"])
    left = max(e["time"] for e in entries if before[-1]["seq"] <= e["seq"] < after_last["seq"])
    happened = [m for m in campaign.moments(entries) if m["scene"] == state["scene"] and m["seq"] < now["seq"]
                and m["kind"] not in ("arrive", "return", "begin", "chronicle")]
    visits = {1: "once", 2: "twice"}.get(len(before), f"{len(before)} times")
    lines = [f"## Back here (the hero was here {visits} before, and left {_ago(state['time'] - left)} ago)"]
    if happened:
        lines += ["What happened here then, latest last:", *[_moment_line(m, where=False) for m in happened[-8:]]]
    lines += ["The place and its people lived on while the hero was away: show what they left and what changed since "
              "(the people and facts below, anything due), not the text as if it were new.", ""]
    return lines


def _due_lines(c):
    due = [(cid, k) for cid, k in c.state["consequences"].items() if campaign.ready(c.adventure, c.state, k)]
    if not due:
        return []
    return ["## Due now (GM only: what the hero did comes back. Pay it off in the story, this turn or the next, "
            "then commit it done: {\"consequence\": {\"id\": \"<id>\", \"status\": \"done\"}})",
            *[f"- {cid}: {k['text']}" + (f" (concerns {c.state['npcs'].get(k['npc'], {}).get('name', k['npc'])})" if k["npc"] else "")
              for cid, k in due], ""]


def _fact_lines(c):
    """What the story has settled (puzzles solved, doors forced, names given), so the GM never
    has to remember it: the facts about this place, the people here and what this scene's
    conditions read, however old, then the latest set elsewhere. The hero's own facts are
    under Character."""
    state = c.state
    facts = {k: v for k, v in state["facts"].items() if not k.startswith("hero.")}
    if not facts:
        return []
    near = {state["scene"], *campaign.people_here(c.adventure, state)}
    read = packs.scene_facts(c.adventure, state["scene"])
    relevant = [k for k in facts if k in read or k.split(".")[0] in near]
    last_set = {}
    for event in c.events:
        for key in (event.get("changes") or {}).get("facts", {}):
            last_set[key] = event["seq"]
    others = sorted((k for k in facts if k not in relevant), key=lambda k: last_set.get(k, 0))
    room = max(0, _FACTS_SHOWN - len(relevant))
    latest = others[-room:] if room else []
    lines = ["## Facts (settled by the story: this place and the people here first, then the latest)",
             *[f"- {key}: {json.dumps(facts[key], ensure_ascii=False)}" for key in relevant + latest]]
    if len(others) > len(latest):
        lines.append(f"- and {len(others) - len(latest)} more, settled earlier elsewhere: solo recall <word> finds them")
    return lines + [""]


_FACTS_SHOWN = 40


def _hero_story(state):
    """The hero.* facts: what the player has made of their hero (a lost brother, an oath, a
    fear of deep water). The story should come back to them."""
    return [f"{key[5:]}: {value}" for key, value in state["facts"].items() if key.startswith("hero.")]


def _chronicle_nudge(c):
    """A GM that plays for hours without a chronicle entry leaves the next session with only
    the log. After CHRONICLE_EVERY of its messages, it is asked for one."""
    state = c.state
    since = state["chronicle"][-1]["seq"] if state["chronicle"] else 0
    count = sum(1 for e in c.events if e["type"] == "said" and e["by"] == "gm" and e["seq"] > since)
    if count >= campaign.CHRONICLE_EVERY:
        return (f"{count} of your messages since the last chronicle entry: put a \"chronicle\" in your next commit, a paragraph "
                "a GM who wasn't here could pick the story up from (what happened, who matters now and why, what is unresolved).")
    return None


def _moment_line(m, where=True):
    place = "" if not where or m["kind"] in ("arrive", "return", "begin") else f", {m['title']}"
    return f"- [{_elapsed(m['time'])}{place}] {m['text']}"


def _scene_title(c, scene_id):
    return c.adventure["scenes"].get(scene_id or "", {}).get("title", scene_id or "somewhere")


def _ago(seconds):
    """Game time in the words a GM would use: 40 minutes, 5 hours, 3 days."""
    minutes = max(0, int(seconds)) // 60
    if minutes < 1:
        return "moments"
    elif minutes < 60:
        return f"{minutes} minute{'s' * (minutes != 1)}"
    elif minutes < 48 * 60:
        return f"{minutes // 60} hour{'s' * (minutes // 60 != 1)}"
    else:
        return f"{minutes // 1440} days"


def resume_digest(c, book=False, scene=False):
    """What the GM needs to pick up exactly where the table stopped: its own last words,
    to repeat as they were, and what happened after them. In the Book the player has
    already read them, so the GM carries on instead of repeating itself. `scene`: the
    scene digest comes right after this (the Book's first prompt), so it isn't run."""
    state, events = c.state, c.events
    speech = [e for e in events if e["type"] == "said" and e["seq"] not in state["struck"]]  # what the player cut is gone
    last = next((e for e in reversed(speech) if e["by"] == "gm"), None)
    lines = [f"# {state['title']}: {state['pc']['name']} in {state['scene_title']} ({state['scene']})", ""]
    lines += _prefs_lines(state)
    lines += _cut_lines(c)
    lines += _problem_lines(c)
    lines += [f"- {line}" for line in _now(c)] + ([""] if _now(c) else [])
    if last is None:
        opening = "Open the adventure from the scene below" if scene else "Run `solo scene`, then open the adventure"
        # The player can write before the GM has said a word: in a Book opened on a new campaign, or after an opening
        # turn that ended before its agent had a session. The opening answers them.
        words = [e["text"] for e in speech if e["by"] == "player"]
        if words:
            lines += ["You haven't said anything at this table yet: this is the opening, and the player has already spoken (under \"Player so far\").",
                      "", f"{opening}: describe the first scene so that it answers the player's words, and end with a question to the player.",
                      "", "## Player so far", *[f"{text}\n" for text in words]]
        else:
            lines += ["Nothing has been said at this table yet: this is the opening.", "",
                      f"{opening}: describe the first scene and end with a question to the player.", ""]
        return "\n".join(lines + _threads(c)).rstrip() + "\n"
    hidden = set(state["hidden"])
    since = [e for e in events if e["seq"] > last["seq"] and e["type"] != "said"]
    answer = [e for e in speech if e["seq"] > last["seq"] and e["by"] == "player"]
    earlier = [e for e in speech if e["seq"] < last["seq"]][-4:]
    if book:
        steps = ["The player is reading the Book, which already shows your last message (under \"Last said\") and every roll since. Don't repeat or recap it."]
    else:
        steps = ["Send the text under \"Last said\" to the player word for word, as your whole first message: no greeting, no recap, no new description."]
    if since:
        steps.append("After it, narrate only what is listed under \"Since then\", briefly and without naming hidden things.")
    steps.append("The player already answered (under \"Player since\"): carry on from their words." if answer
                 else "Answer with a short line that hands the scene back to the player." if book else "Wait for the player's answer.")
    lines += [f"Resume exactly where the table stopped. {'Read the scene below' if scene else 'Run `solo scene` for yourself'}, then:", ""]
    lines += [f"{number}. {step}" for number, step in enumerate(steps, 1)]
    lines += ["", "## Last said", "", last["text"], ""]
    if since:
        lines += ["## Since then", *[f"- #{e['seq']} {campaign.gm_line(e)}" + (" (hidden from the player)" if e["seq"] in hidden else "") for e in since], ""]
    if answer:
        lines += ["## Player since", *[f"{e['text']}\n" for e in answer]]
    if earlier:
        lines += ["## Earlier (for you, don't repeat)", *[f"{'GM' if e['by'] == 'gm' else 'Player'}: {e['text']}\n" for e in earlier]]
    lines += _threads(c)
    return "\n".join(lines).rstrip() + "\n"


def _cut_lines(c):
    """What the player cut with the X-card (the last few), for the GM to stay clear of: what it had said, what the
    player asked, and what it had committed that turn (a cut doesn't undo it)."""
    said = {e["seq"]: e["text"] for e in c.events if e["type"] == "said"}
    cuts = [e for e in c.events if e["type"] == "struck"][-3:]
    if not cuts:
        return []
    lines = ["## Cut by the player (an X-card: never come back to these, and don't repeat them)"]
    for e in cuts:
        first = " ".join(said.get(e["target"], "").split())
        lines.append(f"- You had said (#{e['target']}): \"{first[:240] + '...' if len(first) > 240 else first}\"" + (f". The player said: {e['note']}" if e.get("note") else ""))
        lines += [f"  - it had committed, and that stands unless you retract it in the story: {kept}" for kept in e.get("committed") or []]
    return lines + [""]


_RECENT_MOMENTS = 25
_CHRONICLE_SHOWN = 6
_PEOPLE_SHOWN = 12


def _threads(c):
    """The long memory of a campaign, for a GM starting a session cold, however long it has
    run: where the hero comes from, the chronicle, what has happened since its last entry (from
    the log, so it's there even when no entry was written), what is waiting to come back,
    promises, clues, the people the hero knows, what word has spread, and who is gone."""
    state, adventure, entries = c.state, c.adventure, c.chronology()
    lines = []
    if state["past"]:
        lines.append("## Before this adventure (the hero's earlier stories; the people in them may turn up again)")
        for record in state["past"]:
            lines.append(f"- {record.get('title', 'An adventure')}" + (f": {record['ended']}" if record.get("ended") else ""))
            lines += [f"  - {text}" for text in record.get("chronicle", [])]
            if record.get("loose_ends"):
                lines.append("  - left open: " + "; ".join(record["loose_ends"]))
            if record.get("people"):
                lines.append("  - people who will remember them: " + "; ".join(record["people"]))
        lines.append("")
    lines += ["## The hero, as the player made them (hero.* facts)", *[f"- {line}" for line in _hero_story(state)], ""] if _hero_story(state) else []
    at = {e["seq"]: e for e in entries}
    if state["chronicle"]:
        older = len(state["chronicle"]) - _CHRONICLE_SHOWN
        lines += ["## The story so far (your chronicle, latest last)", *([f"- ({older} earlier entries: solo history)"] if older > 0 else [])]
        lines += [f"- [{_elapsed(at[e['seq']]['time'])}, {at[e['seq']]['title']}] {e['text']}" if e["seq"] in at else f"- {e['text']}"
                  for e in state["chronicle"][-_CHRONICLE_SHOWN:]]
        lines.append("")
    since = state["chronicle"][-1]["seq"] if state["chronicle"] else 0
    recent = [m for m in campaign.moments(entries, after=since) if m["kind"] not in ("chronicle", "begin")]
    if recent and state["last_said"]:
        heading = "## Since your last chronicle entry" if since else "## What has happened so far"
        lines += [f"{heading} (from the log, latest last)",
                  *([f"- ({len(recent) - _RECENT_MOMENTS} earlier: solo history)"] if len(recent) > _RECENT_MOMENTS else []),
                  *[_moment_line(m) for m in recent[-_RECENT_MOMENTS:]], ""]
    waiting = [(cid, k) for cid, k in state["consequences"].items() if k["status"] == "open"]
    if waiting:
        lines += ["## Loose ends (what the hero did that will come back; GM only)", *[_consequence_line(c, cid, k) for cid, k in waiting], ""]
    promises = [f"- {pid} (to {p['npc']}): {p['terms']}" for pid, p in state["promises"].items() if p["status"] == "open"]
    if promises:
        lines += ["## Promises still open", *promises, ""]
    if state["clues"]:
        lines += ["## Clues the hero holds", f"- {', '.join(state['clues'])}", ""]
    seen = {}
    for m in campaign.moments(entries):
        for npc_id in m["npcs"]:
            seen[npc_id] = m["seq"]
    known = sorted((nid for nid, n in state["npcs"].items() if n["met"] and n["fate"] == "alive"
                    and not campaign.profile_of(adventure, state, nid).get("many")), key=lambda nid: -seen.get(nid, 0))
    if known:
        lines += ["## People the hero knows (the latest met first)", *[_known_line(c, nid) for nid in known[:_PEOPLE_SHOWN]],
                  *([f"- and {len(known) - _PEOPLE_SHOWN} more: solo npc <id>"] if len(known) > _PEOPLE_SHOWN else []), ""]
    factions = [_faction_line(state, fid) for fid, f in state["factions"].items()
                if f.get("memories") or f["standing"] != int(adventure["factions"].get(fid, {}).get("standing", 0))]
    if factions:
        lines += ["## Factions (where the hero stands, and what word has reached them)", *factions, ""]
    gone = [f"{n['name']} ({n['fate']})" for nid, n in state["npcs"].items()
            if n["met"] and n["fate"] != "alive" and not campaign.profile_of(adventure, state, nid).get("many")]
    if gone:
        lines += ["## No longer in the story", f"- {', '.join(gone)}", ""]
    fallen = state.get("heroes") or []
    if fallen:
        lines += ["## Heroes before this one", *[f"- {h['name']}: {h['fate']}" for h in fallen], ""]
    if any(e["type"] == "said" for e in c.events):
        lines += ["Anything older or not listed: `solo recall <words>` searches every word said at this table, and "
                  "`solo history` tells the whole story in order. Look it up before you invent it.", ""]
    return lines


def _consequence_line(c, consequence_id, consequence):
    """A loose end as the GM reads it: what, about whom, and when it comes back."""
    state = c.state
    npc = state["npcs"].get(consequence["npc"] or "")
    when = []
    if consequence["at"]:
        when.append("at " + " or ".join(_scene_title(c, s) for s in consequence["at"]))
    if consequence["when"]:
        when.append(f"when {consequence['when']}")
    if consequence["due_at"] is not None:
        when.append(f"from {_elapsed(consequence['due_at'])} of game time")
    if not when:
        when.append(f"the next time the hero meets {npc['name']}" if npc else "no trigger: bring it in when it fits")
    line = f"- {consequence_id}: {consequence['text']} ({'; '.join(when)})"
    if npc and (consequence["at"] or consequence["when"] or consequence["due_at"] is not None):
        line += f"; concerns {npc['name']}"
    if npc and npc["fate"] != "alive":
        line += f"; {npc['name']} is {npc['fate']}: drop it, or let someone else carry it"
    if campaign.ready(c.adventure, state, consequence):
        line += " [due now]"
    elif consequence["due"]:
        line += " [came due earlier, not yet paid off]"
    return line


def _known_line(c, npc_id):
    state = c.state
    npc, profile = state["npcs"][npc_id], campaign.profile_of(c.adventure, state, npc_id)
    line = f"- {npc_id}: {npc['name']}" + (f", {profile['role']}" if profile.get("role") else "") + f" ({_attitude_name(npc['attitude'])})"
    if npc.get("location"):
        line += f", at {_scene_title(c, npc['location'])}"
    if npc["memories"]:
        line += "; remembers: " + " / ".join(npc["memories"][-2:])
    return line


def _faction_line(state, faction_id):
    faction = state["factions"][faction_id]
    heard = faction.get("memories") or []
    return f"- {faction_id}: {faction['name']} ({_attitude_name(faction['standing'])})" + (f"; they've heard: {' / '.join(heard[-3:])}" if heard else "")


def npc_card(c, npc_id):
    state, adventure = c.state, c.adventure
    if npc_id not in state["npcs"]:
        raise SoloError(f"unknown npc {npc_id!r}; npcs: {', '.join(state['npcs']) or 'none'}")
    npc, profile = state["npcs"][npc_id], campaign.profile_of(adventure, state, npc_id)
    faction = state["factions"].get(npc.get("faction") or "", {})
    lines = [f"# {npc['name']} ({npc_id})", ""]
    if profile.get("role"):
        lines.append(profile["role"])
    if profile.get("many"):
        lines.append("A kind of foe the hero meets again and again: every fight brings new ones, and no one fate covers them all.")
    if faction:
        lines.append(f"Faction: {faction['name']} (standing {_attitude_name(faction['standing'])})"
                     + (f"; they've heard: {' / '.join(faction['memories'][-3:])}" if faction.get("memories") else ""))
    lines += [
        f"Now: {npc['fate']}, {_attitude_name(npc['attitude'])} toward the PC"
        + (f", at {npc['location']}" if npc.get("location") else ""),
        "",
    ]
    if npc.get("profile"):
        lines += [f"(You made up {', '.join(npc['profile'])} in play: keep to it.)", ""]
    for key in ("wants", "fears", "voice", "description"):
        if profile.get(key):
            lines.append(f"{key.capitalize()}: {profile[key]}")
    secrets = profile.get("secrets", [])
    if secrets:
        lines += ["", "## Secrets (GM only)"]
        for secret in secrets:
            when = secret.get("reveal")
            status = "" if not when else (" [can be revealed now]" if packs.evaluate(when, state) else f" [reveal when {when}]")
            lines.append(f"- {secret.get('id', 'secret')}: {secret.get('text', '')}{status}")
    promises = [f"- {pid} ({p['status']}): {p['terms']}" for pid, p in state["promises"].items() if p["npc"] == npc_id]
    if promises:
        lines += ["", "## Promises", *promises]
    waiting = [_consequence_line(c, cid, k) for cid, k in state["consequences"].items() if k["npc"] == npc_id and k["status"] == "open"]
    if waiting:
        lines += ["", "## Waiting on them (consequences, GM only)", *waiting]
    if npc["memories"]:
        lines += ["", "## Remembers", *[f"- {m}" for m in npc["memories"]]]
    for key in ("stats", "skills"):
        if profile.get(key):
            lines += ["", f"## {key.capitalize()}", ", ".join(f"{k} {v}" for k, v in profile[key].items())]
    shown = {"name", "role", "faction", "attitude", "wants", "fears", "voice", "description", "secrets", "stats", "skills", "kind", "many"}
    rest = {k: v for k, v in profile.items() if k not in shown}
    if rest:
        lines += ["", "## Other", *[f"- {k}: {v}" for k, v in rest.items()]]
    return "\n".join(lines)


def recall_text(c, query, limit=8):
    """What the campaign holds about something, for a GM about to bring it back: the words
    said at the table first of all, then notes, facts, memories and oracle answers."""
    found = campaign.recall(c.chronology(), c.state, query, limit=limit)
    if not found:
        return (f"Nothing at this table mentions {query!r}. If it matters now, the story hasn't settled it yet: "
                "decide it (or ask the oracle), and write it down so it stays the same.")
    lines = [f"# Recall: {query}", ""]
    for hit in found:
        where = f"[{_elapsed(hit['time'])}, {hit['title']}]" if hit["time"] is not None else f"[{hit['title']}]"
        lines.append(f"- {'#' + str(hit['seq']) + ' ' if hit['seq'] else ''}{where} {hit['label']}: {hit['text']}")
    return "\n".join(lines)


def history_text(c):
    """The whole campaign in order, for the GM (spoilers and GM notes included): chapters that
    close on each chronicle entry, the moments in between from the log."""
    state = c.state
    lines = [f"# {state['title']}: the story so far", "", f"{_hero_line(state['pc'])}; {_elapsed(state['time'])} of game time.", ""]
    for record in state["past"]:
        lines += [f"## Before: {record.get('title', 'an adventure')}", *([record["ended"]] if record.get("ended") else []),
                  *[f"- {text}" for text in record.get("chronicle", [])], ""]
    chapter, number = [], 1
    for m in campaign.moments(c.chronology()):
        if m["kind"] == "chronicle":
            lines += [f"## Chapter {number}", *chapter, "", f"Chronicle: {m['text']}", ""]
            chapter, number = [], number + 1
        else:
            chapter.append(_moment_line(m))
    if chapter:
        lines += [f"## Chapter {number}" + (" (since the last chronicle entry)" if number > 1 else ""), *chapter, ""]
    return "\n".join(lines).rstrip() + "\n"


def _prefs_lines(state):
    """The player's table settings, first in everything the GM reads."""
    prefs = state["prefs"]
    lines = [f"- Tone: {prefs['tone']}"] if prefs["tone"] else []
    lines += [f"- Line (never in the story): {line}" for line in prefs["lines"]]
    lines += [f"- Veil (happens off screen only): {veil}" for veil in prefs["veils"]]
    return ["## Table settings (the player's; always respect them)", *lines, ""] if lines else []


def _problem_lines(c):
    """What's wrong with the packs under the campaign (one edited since it began, say). The
    GM plays on around it, and tells the player once, plainly, so they can fix the pack."""
    problems = c.problems
    if problems:
        return ["## Pack problems (tell the player once: `solo validate` in a terminal shows them)",
                *[f"- {problem}" for problem in problems], ""]
    else:
        return []


def _light_lines(c):
    """Darkness and the light the hero carries, when either matters."""
    state = c.state
    lit = state["light"]
    dark = c.adventure["scenes"][state["scene"]].get("dark", False)
    if lit:
        left = lit["lit_at"] + lit["burns"] - state["time"]
        return ["## Light", f"The hero's {lit['label'].lower()} burns: {_duration_text(left)} left.", ""]
    elif dark:
        return ["## Light", "It's dark here and nothing is burning: rolls that need sight get a bane, or can't be made. "
                "The hero can light something they carry (solo light).", ""]
    else:
        return []


def _travel(c, spec):
    spent = spec["time"] or c.adventure["move_time"]
    return f" (takes {packs.spent_text(spent)})" if spent else ""


def _duration_text(seconds):
    hours, minutes = divmod(max(0, int(seconds)) // 60, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


def _scene_check_lines(c):
    """How the scene check went when the hero came in, while they are still here."""
    move = next((e for e in reversed(c.events) if e["type"] == "move"), None)
    check = (move or {}).get("scene_check") or {}
    if move is None or move["to"] != c.state["scene"] or check.get("result", "expected") == "expected":
        return []
    elif check["result"] == "altered":
        return ["## Scene check: altered", "The scene isn't quite what the hero expects: change one detail of the text below (who is here, what they're doing, the weather, a door) and keep the rest.", ""]
    else:
        return ["## Scene check: interrupted", f"Something gets in first: {oracle.describe_event(check['event'])}. Open the scene with it, then carry on with the text below.", ""]


def _npc_line(c, npc_id):
    state = c.state
    npc = state["npcs"].get(npc_id)
    if npc is None:
        return f"- {npc_id}: (unknown)"
    profile = campaign.profile_of(c.adventure, state, npc_id)
    line = f"- {npc_id}: {npc['name']}" + (f", {profile['role']}" if profile.get("role") else "")
    line += " (a kind of foe: every fight brings new ones)" if profile.get("many") else f" ({npc['fate']}, {_attitude_name(npc['attitude'])})"
    promises = [f"{pid} {p['status']}" for pid, p in state["promises"].items() if p["npc"] == npc_id]
    if promises:
        line += f"; promises: {', '.join(promises)}"
    waiting = [cid for cid, k in state["consequences"].items() if k["npc"] == npc_id and k["status"] == "open"]
    if waiting:
        line += f"; waiting on them: {', '.join(waiting)}"
    if npc["memories"]:
        # The last few, not the last one: what matters most between them is rarely the latest.
        line += "; remembers: " + " / ".join(npc["memories"][-3:])
    heard = state["factions"].get(npc.get("faction") or "", {}).get("memories")
    if heard:
        line += f"; their people have heard: {heard[-1]}"
    return line + f". More: solo npc {npc_id}"


def _clock_line(c, clock_id):
    clock, spec = c.state["clocks"][clock_id], c._clock_spec(clock_id)
    line = f"- {clock['label']} ({clock_id}): {clock['value']}/{clock['segments']}"
    if clock.get("threat"):
        line += f", a threat: at {clock['segments']} it comes to pass" + (", then starts over" if clock["threat"]["recurring"] else "")
        if c.adventure["scenes"].get(c.state["scene"], {}).get("safe") and not clock["stopped"]:
            line += "; the hero is somewhere safe, so time here doesn't bring it closer"
    if clock["hidden"]:
        line += ", hidden from the player"
    if clock["stopped"]:
        line += ", stopped for good"
    elif clock["full"] and spec.get("at_full"):
        line += f". FULL: run scene {spec['at_full']} (solo move {spec['at_full']} --force \"{clock_id} filled\")"
    elif spec.get("while") and not packs.evaluate(spec["while"], c.state):
        line += f", not running (runs while {spec['while']})"
    reached = [s for s in spec.get("stages", []) if s.get("at", 0) <= clock["value"] and (s.get("note") or s.get("text"))]
    if reached:
        line += f". Reached {reached[-1]['at']}: {(reached[-1].get('note') or reached[-1].get('text')).rstrip('.')}"
    upcoming = [s for s in spec.get("stages", []) if s.get("at", 0) > clock["value"]]
    if upcoming:
        line += f". Next stage at {upcoming[0]['at']}"
    return line


def _progress_lines(state):
    """The progress tracks still open, as the rules count them: full boxes, and the ticks toward the next."""
    spec, lines = state["labels"]["progress"], []
    for track_id, track in state["progress"].items():
        if not track["ended"]:
            boxes, part = divmod(track["ticks"], spec["ticks"])
            rank = f" ({track['rank']} {track['kind']})" if track["rank"] else ""
            lines.append(f"- {track_id}: {track['name']}{rank}: {boxes} of {spec['boxes']} boxes" + (f" and {part} tick{'s' * (part != 1)}" if part else ""))
    return ["## Progress tracks", *lines, ""] if lines else []


def _pc_line(state):
    pc = state["pc"]
    tracks = ", ".join(_track_text(name, t) for name, t in pc["tracks"].items())
    line = f"{pc['name']}: {tracks}; conditions: {', '.join(pc['conditions']) or 'none'}"
    if pc["dead"]:
        line += "; DEAD"
    elif pc["dying"]:
        line += f"; DYING ({_tally(pc['dying'])})"
    if pc["marks"]:
        line += f"; marked for advancement: {', '.join(pc['marks'])}"
    return line + f"; carrying: {', '.join(pc['items']) or 'nothing'}; time elapsed: {_elapsed(state['time'])}"


def _track_text(name, track):
    """hp 9/14; momentum, which runs below zero, as +2 (up to 10, back to 2 after a burn)."""
    if "min" in track:
        return f"{name} {track['value']:+d} (to {track['max']}, resets to {track['reset']})"
    else:
        return f"{name} {track['value']}/{track['max']}"


def _skills_line(state):
    """The names to roll with: the hero's trained skills with their values, then the rest.
    GMs who know other games reach for "search" or "insight"; these are the ones that exist."""
    if state["family"] == "action-roll":
        pc = state["pc"]
        return "Stats: " + ", ".join(f"{name} {value}" for name, value in pc["attributes"].items()) + (f"; assets: {', '.join(pc['abilities'])}" if pc["abilities"] else "")
    skills = state["pc"]["skills"]
    trained = [f"{key} {s['value']}" for key, s in skills.items() if s["trained"]]
    other = [f"{key} {s['value']}" for key, s in skills.items() if not s["trained"]]
    return f"Skills: {', '.join(trained) or 'none trained'}" + (f"; untrained: {', '.join(other)}" if other else "")


def _now(c):
    """What stands after an action, when it matters: the fight, dying, the end."""
    state, pc = c.state, c.state["pc"]
    now = []
    if state["combat"]:
        fight = state["combat"]
        now.append(f"round {fight['round']}; " + ", ".join(_foe_text(f) for f in fight["foes"].values()))
        waiting = c.to_act()
        now.append(f"to act, in order: {', '.join(waiting)}" if waiting else "everyone has acted: deal the next round (solo fight --round)")
        if fight["incoming"]:
            hit = fight["incoming"]
            if pc["dying"]:
                now.append(f"incoming: {hit['damage']} from {hit['name']} ({hit['label']}); the hero is dying and can't defend: solo defend take (a failed death roll)")
            else:
                how = ("evade, parry or take" if hit.get("can_parry", True) else "evade or take (no parrying this)") if hit.get("can_defend", True) else "take only"
                now.append(f"incoming: {hit['damage']} from {hit['name']} ({hit['label']}); the player chooses: {how}")
        scene = c.adventure["scenes"].get(state["scene"], {})
        if scene.get("each_round"):
            # What this place asks every round (holding your breath under water), so it isn't forgotten.
            now.append(f"each round here: {scene['each_round']}")
    if pc["dying"]:
        now.append(f"{pc['name']} is dying: {_tally(pc['dying'])} (solo death-roll)")
    if state["ended"]:
        now.append(f"ended: {state['ended']['text']}")
    return now


def _tally(dying):
    s, f = dying["successes"], dying["failures"]
    return f"{s} success{'es' * (s != 1)}, {f} failure{'s' * (f != 1)}"


def _foe_text(foe):
    return f"{foe['name']} " + ("down" if foe["down"] else f"HP {foe['hp']}/{foe['max']}, armor {foe['armor']}")


def _hero_line(pc):
    """Ragna, Dwarf, Fighter, Adult: HP 14/14, WP 11/11"""
    who = ", ".join([pc["name"], *map(str, pc.get("info", {}).values())])
    return who + ": " + ", ".join(f"{t.upper()} {v['value']:+d}" if "min" in v else f"{t.upper()} {v['value']}/{v['max']}" for t, v in pc["tracks"].items())


def _attitude_name(value):
    return next((name for name, number in ATTITUDES.items() if number == value), str(value))


def _elapsed(seconds):
    days, rest = divmod(int(seconds), 86400)
    return f"{days}d {rest // 3600:02d}:{rest % 3600 // 60:02d}"
