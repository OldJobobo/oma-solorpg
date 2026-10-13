"""`solo review`: the checks a play test runs, over a campaign played for real.

`tests/gm_eval` plays scenarios with a real GM and checks each message and the campaign's state in
code. The same checks apply to a campaign someone actually played, offline and at no cost: this
module holds them, and the harness imports them. What they find in real play is what a scenario
should be written about.

Every check is a function returning findings, (kind, detail) pairs.
"""

import json
import re
from pathlib import Path

from . import campaign

# What a GM message must never carry: the engine's words and the GM's own bookkeeping.
BOOKKEEPING = [
    (re.compile(r"::: ?gm"), "a GM fence"),
    (re.compile(r"\bsolo (scene|check|commit|move|fight|enemy|attack|defend|table|roll|ask|npc|resume|log|state|wound|voice|light|rest|push)\b"), "a solo command"),
    (re.compile(r'\{\s*"'), "JSON"),
    (re.compile(r"\b(commit it|the engine|the log says|hidden clock|fact key)\b", re.I), "bookkeeping words"),
    (re.compile(r"^#{1,6} ", re.M), "a Markdown heading"),
    (re.compile(r"\b(narrate|narration|the player|time to narrate|is now open)\b", re.I), "the GM's notes to itself"),
    (re.compile(r"\b\d+ vs \d+\b|\bdown to \d+ HP\b", re.I), "dice restated (the Book shows them)"),
]
# A consequence that came due and is still open after this many GM messages was never paid.
_PAID_WITHIN = 2


def hygiene(text, c):
    """Problems in one GM message that code can see. Each is (kind, detail)."""
    problems = []
    for pattern, what in BOOKKEEPING:
        found = pattern.search(text)
        if found:
            problems.append(("bookkeeping", f"{what}: {found.group(0)!r}"))
    # Only ids no narration would write: dotted facts and snake_case names ("hours" is a word).
    ids = [*c.state["facts"], *c.adventure["clocks"], *c.adventure["npcs"], *c.adventure["scenes"]]
    for key in [k for k in ids if "_" in k or "." in k]:
        if re.search(rf"(?<![\w.]){re.escape(key)}(?![\w])", text):
            problems.append(("bookkeeping", f"an engine id: {key}"))
    if len(text.split()) > 40 and not re.search(r"\byou(r|rs|rself)?\b", text, re.I):
        problems.append(("third_person", "never speaks to the player as you"))
    tail = text.strip()[-300:]
    if "?" not in tail and not re.search(r"\b(what do you do|your move|what now)\b", tail, re.I):
        problems.append(("no_question", "doesn't end with a question or a prompt for the player"))
    if len(text.split()) > 400:
        problems.append(("too_long", f"{len(text.split())} words"))
    return problems


def fight_checks(events):
    """Every round a foe stood through, it should have attacked: a GM that forgets
    `solo enemy` lets the hero fight unopposed."""
    problems, rounds = [], []
    current = None
    for event in events:
        if event["type"] in ("fight", "round"):
            current = {"seq": event["seq"], "enemy": 0, "hero": 0}
            rounds.append(current)
        elif event["type"] == "fight_end":
            current = None
        elif current is not None and event["type"] == "enemy":
            current["enemy"] += 1
        elif current is not None and event["type"] == "check" and event.get("attack"):
            current["hero"] += 1
    for r in rounds[:-1] if rounds and _open_fight(events) else rounds:
        if r["hero"] and not r["enemy"]:
            problems.append(("fight", f"the round starting at #{r['seq']}: the hero attacked and no foe attacked back"))
    return problems


def _open_fight(events):
    kinds = [e["type"] for e in events if e["type"] in ("fight", "fight_end")]
    return bool(kinds) and kinds[-1] == "fight"


def forced_moves(events):
    return [f"#{e['seq']} to {e['to']}: {e['forced']}" for e in events if e["type"] == "move" and e.get("forced")]


def repeated_messages(events):
    """Two GM messages with no player words between them: the Book shows the story twice."""
    said = [e for e in events if e["type"] == "said"]
    return [("repeat", f"#{b['seq']} follows GM message #{a['seq']} with no player words between")
            for a, b in zip(said, said[1:]) if a["by"] == b["by"] == "gm"]


def unpaid_consequences(c):
    """A consequence that came due (`due`) and is still open two GM messages later: the GM was told
    and never paid it off in the story, or never committed it done."""
    findings = []
    for event in c.events:
        if event["type"] != "due":
            continue
        consequence = c.state["consequences"].get(event["consequence"], {})
        spoken = sum(1 for e in c.events if e["type"] == "said" and e["by"] == "gm" and e["seq"] > event["seq"] and e["seq"] not in c.state["struck"])
        if consequence.get("status") == "open" and spoken >= _PAID_WITHIN:
            findings.append(("unpaid", f"{event['consequence']} came due at #{event['seq']} and is still open after {spoken} GM messages: {' '.join(str(event.get('text', '')).split())[:90]}"))
    return findings


def two_names(events):
    """One person under two names (a commit renamed someone, which needs an override; a rename that was
    refused shows under `refused`), and one name under two ids (except a foe met in numbers, cultist and
    cultist_2)."""
    findings, owners = [], {}
    for event in events:
        if event["type"] != "commit":
            continue
        for nid, change in (event.get("changes", {}).get("npc") or {}).items():
            if change.get("name_was"):
                findings.append(("two_names", f"#{event['seq']}: {nid} was {change['name_was']!r}, and is now {change['name']!r}"))
            name = (change.get("name") or "").strip()
            if not name:
                continue
            stem = re.sub(r"_\d+$", "", nid)
            other = owners.setdefault(name.casefold(), (nid, stem))
            if other[1] != stem:
                findings.append(("two_names", f"#{event['seq']}: {name!r} is {other[0]} and {nid}"))
    return findings


def refused_commands(trace):
    """Commands the engine refused, from a trace file (`SOLO_TRACE`, or the Book's `.solo/trace.jsonl`), and those
    Claude Code's permissions refused before they ran (a `solo gm turn` adds them; one that isn't solo has no argv)."""
    findings = []
    try:
        lines = Path(trace).read_text(encoding="utf-8").splitlines()
    except OSError:
        return findings
    for raw in lines:
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if item.get("error") and item.get("argv"):
            findings.append(("refused", f"solo {' '.join(item['argv'])[:80]}: {item['error'][:120]}"))
        elif item.get("error"):
            findings.append(("refused", item["error"][:200]))
    return findings


def review(c, trace=None):
    """Everything code can see wrong in a campaign played for real, as (kind, detail) findings."""
    trace = trace or Path(c.root) / ".solo" / "trace.jsonl"
    findings = []
    for event in c.events:
        if event["type"] == "said" and event["by"] == "gm" and event["seq"] not in c.state["struck"]:
            findings += [(kind, f"#{event['seq']}: {detail}") for kind, detail in hygiene(event["text"], c)]
    findings += fight_checks(c.events) + repeated_messages(c.events) + unpaid_consequences(c) + two_names(c.events)
    findings += [("forced", detail) for detail in forced_moves(c.events)]
    findings += refused_commands(trace)
    return findings


def render(findings, title):
    """The findings as Markdown, a group for each kind."""
    if not findings:
        return f"# Review of {title}\n\nNothing found: no refused commands, no bookkeeping in the story, every foe struck back, every consequence paid.\n"
    lines = [f"# Review of {title}", "", f"{len(findings)} thing{'s' if len(findings) != 1 else ''} worth a look. Each is a scenario waiting to be written (tests/gm_eval).", ""]
    for kind in dict.fromkeys(kind for kind, _ in findings):
        lines += [f"## {kind}", *[f"- {detail}" for k, detail in findings if k == kind], ""]
    return "\n".join(lines)
