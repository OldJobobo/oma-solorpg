"""`solo report`: what a bug report needs about a campaign, safe to post in a public issue.

An issue is public, and a campaign is built from books the player owns: rules pages, table
results, scene text and monster tables are the publisher's. So the report shows what happened
by ids, numbers and dice only. Every free-text field of an event (a table's result, an oracle's
answer, a threat's words, a note) is left out, and so are the packs' text and the rules pages.
The last messages of the story are the one exception, since a bug about the GM is a bug about
what it said: the report says to read them before posting, and `--no-messages` leaves them out.
"""

import json
import platform
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import campaign
from .library import REPO

# What a slug or an enum looks like: an id, a column of the fortune chart, a track. Anything else
# that is a string is words, and words in an event may be the book's.
_IDLIKE = re.compile(r"^[a-z0-9_.:+\-]{1,40}$")
_LEFT_OUT = "…"


def bare(value):
    """A value with its words left out: numbers, booleans, ids and dice stay."""
    if isinstance(value, dict):
        return {key: bare(inner) for key, inner in value.items()}
    elif isinstance(value, list):
        return [bare(inner) for inner in value]
    elif isinstance(value, str):
        return value if _IDLIKE.match(value) else _LEFT_OUT
    else:
        return value


def event_line(event):
    """One event as ids, numbers and dice: `#12 table {"table": "treasure", "total": 9, ...}`."""
    fields = {k: v for k, v in event.items() if k not in ("seq", "type", "at")}
    if event["type"] == "said":
        return f"#{event['seq']} said by {event.get('by')} ({len(event.get('text', ''))} characters)"
    return f"#{event['seq']} {event['type']} " + json.dumps(bare(fields), ensure_ascii=False, separators=(",", ":"))[:600]


def commit():
    """The engine's version: the repository's commit, when it is a git checkout."""
    try:
        done = subprocess.run(["git", "-C", str(REPO), "describe", "--always", "--dirty"], capture_output=True, text=True, timeout=5)
        return done.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def trace_lines(root, limit):
    """The last `limit` commands the GM ran in this campaign (the Book's turns write them), arguments cut short."""
    path = Path(root) / ".solo" / "trace.jsonl"
    lines = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines()[-limit:]:
            item = json.loads(raw)
            argv = [a if len(a) <= 80 else a[:79] + _LEFT_OUT for a in item.get("argv", [])]
            # A command Claude Code's own permissions refused isn't a solo command, and has no argv.
            command = f"solo {' '.join(argv)}" if argv else "(not a solo command)"
            lines.append(f"- {item.get('at', '')} {command}" + (f"  -> refused: {item['error']}" if item.get("error") else ""))
    except (OSError, ValueError):
        pass
    return lines


def report(c, events=25, messages=6, commands=40):
    """The report, as Markdown."""
    formats = [f"{root.name} {fmt if fmt is not None else 'none'}" for root, fmt in c.system.get("formats", [])]
    said = [e for e in c.events if e["type"] == "said"]
    trace = trace_lines(c.root, commands)
    lines = [
        "# oma-solorpg report", "",
        f"Written {datetime.now().isoformat(timespec='minutes')}. It shows what happened by ids, numbers and dice, and leaves out "
        "rules pages, tables' words, scene text and every free-text field of an event."
        + (" **The last messages below are the story as it was told: read them before you post.**" if messages else ""), "",
        "## Engine", f"- oma-solorpg {commit()}", f"- Python {platform.python_version()} on {platform.system()} {platform.machine()}", "",
        "## Packs",
        f"- system {c.system.get('name', '?')}, family {c.system.get('family', '?')}; pack format of each layer, base first: {', '.join(formats) or 'none'}",
        f"- adventure {Path(c.adventure['dir']).name}, format {c.adventure.get('format', 'none')}", "",
        "## The campaign",
        f"- {len(c.events)} events, {len(said)} messages; scene {c.state.get('scene')}",
        f"- the hero's tracks: {json.dumps(bare({k: v.get('value') for k, v in c.state['pc']['tracks'].items()}), separators=(',', ':'))}"
        f"; conditions: {', '.join(c.state['pc']['conditions']) or 'none'}", "",
        f"## The last {min(events, len(c.events))} events", *[f"- {event_line(e)}" for e in c.events[-events:]], "",
        "## What the GM ran (the Book's turns write this)", *(trace or ["- no trace in this campaign yet"]), "",
    ]
    if messages:
        shown = min(messages, len(said))
        lines += [f"## The last {shown} message{'s' if shown != 1 else ''}", ""]
        for e in said[-messages:]:
            lines += [f"**{e['by']}** (#{e['seq']}):", "", *[f"> {part}" for part in e["text"].splitlines() or [""]], ""]
    return "\n".join(lines).rstrip() + "\n"
