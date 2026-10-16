"""A campaign's folder as the engine reads and writes it: the event log, state.json and the kept replay.

events.jsonl is the campaign. Each event is one line, on the disk (fsynced) before the command goes on,
and a write that fails takes back what it wrote; a last line cut off mid-write is set aside the next
time the log is read. state.json is what the Table and the Book read: the state reducer.py folds from
the log, with what the packs add to it (snapshot), rewritten after each command and safe to delete.
.solo/replay.marshal keeps a long campaign's replay for the next command, used while the log's first
events, the packs and the engine's files are the ones it was made from (_replay_key).

Log is the part of Campaign that opens a campaign from its folder and writes to it. session(), in
campaign.py, takes the folder's lock around it, and the commands that append events are there too.
"""

import json
import marshal
import os
import re
import sys
import zlib
from datetime import datetime
from pathlib import Path

from . import SoloError, combat, dice, library, magic, packs, portrait
from .reducer import _advance, burn_option, codex, replay, route

# State the GM reads through `solo`, never the panel: it stays out of state.json.
_GM_ONLY = ("consequences", "hidden", "problems")
# A long campaign's log replayed from the start for every command took longer than anything else the command
# did (a tenth of a second at four thousand events, half a second at twenty thousand). So the replay is kept
# in .solo/replay.marshal: the state and the chronology after the log's first `count` events. It stands while
# those events are the same bytes (their crc32) and the packs and the engine are the ones it was made from,
# and it is kept again once the log has grown this many events past it.
_KEEP_EVERY = 50


class Log:
    """The part of Campaign its folder holds: opening a campaign (its packs, its log, and the state
    replayed from them or from the replay kept) and writing to it (an event, the kept replay, state.json).
    Campaign takes these methods from here; session() in campaign.py opens one under the folder's lock."""

    def __init__(self, root, new=False):
        self.root = Path(root)
        self.config = packs.load_data(self.root / "campaign.toml")
        self.system = packs.load_system(_pack(self.root, self.config["system"], library.find_system))
        self.adventure = packs.with_system(self.system, packs.load_adventure(_pack(self.root, self.config["adventure"], library.find_adventure), drafts=False))
        if self.adventure.get("weapons"):
            self.system["weapons"] = {**self.system.get("weapons", {}), **self.adventure["weapons"]}
        self.events, log = _read_events(self.root / "events.jsonl")
        if not self.events and not new:
            raise SoloError(f"{self.root} has a campaign.toml and no events: it stopped while it was being created. "
                            f"Start it again: solo new <adventure> --dir {self.root}")
        # Where this session's own events begin: what one command did, whatever came first.
        self.opened = len(self.events)
        # The error of a write to the log that failed: the command stops there, and nothing more is written.
        self.unwritten = None
        # What the state is made from (this Python, the engine, the packs as read), as a kept replay and state.json record it.
        self.key = _replay_key(self)
        self.made_from = zlib.crc32(json.dumps(self.key).encode())
        # The state after every event, and the chronology: from the replay kept for a long
        # campaign while it stands, and the events since, else from the start.
        kept = _read_kept(self, log) if len(self.events) >= _KEEP_EVERY else None
        if kept:
            self.kept = kept["count"]
            self.state, self.entries = replay(self.system, self.adventure, self.events[self.kept:], kept["state"], kept["entries"])
        else:
            self.kept = 0
            self.state, self.entries = replay(self.system, self.adventure, self.events)

    def append(self, event_type, /, **data):
        event = {
            "seq": len(self.events) + 1,
            "at": datetime.now().isoformat(timespec="seconds"),
            "type": event_type,
            **{k: v for k, v in data.items() if v is not None},
        }
        # Dice fixed by SOLO_SEED say so in the log (and the Book shows it): otherwise a GM
        # could try seeds on a copy of the campaign and roll the one that lands well here.
        seed = dice.fixed_seed()
        if seed is not None:
            event["seed"] = seed
        line = _line(event)
        # Applied before it is written: an event the state can't take is refused, never left
        # in the log for every later replay to trip over.
        _advance(self.state, self.entries, event, self.adventure, strict=True)
        try:
            _write_line(self.root / "events.jsonl", line)
        except OSError as error:
            self.unwritten = error
            raise SoloError(f"couldn't write to {self.root / 'events.jsonl'} ({error.strerror or error}), so the command stopped there "
                            "(solo log shows what it recorded): free some disk space, or fix what stops the write, and go on") from None
        self.events.append(event)
        return event

    def keep(self):
        """Keep the replay for the next command, once the log has grown _KEEP_EVERY events past the one kept."""
        if len(self.events) - self.kept >= _KEEP_EVERY:
            log = (self.root / "events.jsonl").read_bytes()
            kept = {"key": self.key, "count": len(self.events), "size": len(log), "crc": zlib.crc32(log), "state": self.state,
                    "entries": [{k: v for k, v in entry.items() if k != "event"} for entry in self.entries]}
            path = self.root / ".solo" / "replay.marshal"
            try:
                path.parent.mkdir(exist_ok=True)
                path.with_name("replay.marshal.tmp").write_bytes(marshal.dumps(kept))
                os.replace(path.with_name("replay.marshal.tmp"), path)
            except (OSError, ValueError):  # it only saves time: the command stands without it
                return
            self.kept = len(self.events)

    def save(self):
        """Write state.json. It keeps up with the log whatever the packs make of it: what they add (the
        kit, the map, the codex, the art) is left out when it can't be worked out, and said, rather than
        failing a command whose events are written (its retry would roll again) and leaving the panel behind."""
        path = self.root / "state.json"
        temporary = path.with_name("state.json.tmp")
        try:
            view = snapshot(self.system, self.state, self.adventure)
        except Exception as error:  # whatever it was, the log stands and the state follows it
            reason = error if isinstance(error, SoloError) else f"{type(error).__name__}: {error}"
            print(f"solo: state.json is written without what the packs add to it ({reason}); solo validate says what to fix", file=sys.stderr)
            view = {k: v for k, v in self.state.items() if k not in _GM_ONLY}
        # First, with the seq, what it was made from: a command reads both to see whether state.json is behind (see session).
        view = {"seq": view["seq"], "made_from": self.made_from, **view}
        temporary.write_text(json.dumps(view, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporary, path)


def snapshot(system, state, adventure=None):
    """state.json: the folded state plus what the panel and the Book need derived from the
    packs (the weapons the hero carries, the codex, the route, the art), so they compute no
    rules. Nothing here is GM-only: unknown things are counted, never shown."""
    view = {**{k: v for k, v in state.items() if k not in _GM_ONLY}, "kit": combat.kit(system, state["pc"]) if state["pc"] else None,
            "load": combat.encumbrance(system, state["pc"]) if state["pc"] else None, "burn": burn_option(state),
            "magic": magic.sheet(system, state["pc"]) if state["pc"] else None, "abilities": combat.powers(system, state["pc"]) if state["pc"] else []}
    if adventure is not None:
        # Counted, not listed: what they name would give the adventure away (`solo validate` says).
        view["pack_problems"] = len(packs.validate(system, adventure)) + len(state["problems"])
    if adventure is not None and state["pc"]:
        lit = state["light"]
        view.update(
            codex=codex(adventure, state),
            route=route(adventure, state),
            dark=bool(adventure["scenes"].get(state["scene"], {}).get("dark")),
            light=lit and {**lit, "left": max(0, lit["lit_at"] + lit["burns"] - state["time"])},
            **portrait.art(system, adventure, state),
        )
    return view


def _pack(root, recorded, find):
    """A pack path from campaign.toml. If the pack moved (the plugin was reinstalled
    somewhere else), find it again in the library by its folder name."""
    path = root / recorded
    return path if path.exists() else find(Path(recorded).name)


def _read_events(path):
    """The log's events, and its bytes (what a kept replay is checked against). Events are split at
    newlines only: a message may hold a line separator (U+2028) that str.splitlines would cut at."""
    if not path.exists():
        return [], b""
    _mend_tail(path)
    data = path.read_bytes()
    try:
        filled = [line for line in data.decode("utf-8").split("\n") if line.strip()]
        events = json.loads(f"[{','.join(filled)}]")  # the log in one parse, a third faster than a line at a time
    except (UnicodeDecodeError, json.JSONDecodeError):
        events = None
    if events is None or len(events) != len(filled) or not all(isinstance(event, dict) for event in events):
        # Which line is damaged: read them one at a time.
        events = []
        for number, line in enumerate(data.split(b"\n"), 1):
            if line.strip():
                try:
                    event = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise SoloError(_damaged(path, number, error)) from None
                if not isinstance(event, dict):
                    raise SoloError(_damaged(path, number, "it isn't an event"))
                events.append(event)
    return events, data


def _line(event):
    """An event as the line the log holds. Text that isn't Unicode the log can hold (a lone surrogate: half an emoji cut
    off, or a byte that wasn't UTF-8 on the command line), and lists nested deeper than Python writes them, are refused
    with a sentence, not met by the write."""
    try:
        return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
    except UnicodeEncodeError as error:
        raise SoloError(f"the text holds {error.object[error.start:error.end]!r}, half of a character (or a byte that wasn't UTF-8), "
                        "which the log can't hold: write it again without it") from None
    except RecursionError:
        raise SoloError("it nests lists or objects deeper than the log can hold (a commit is an object a few levels deep)") from None


def _damaged(path, number, error):
    """What to do about a line of the log that can't be read. (A last line cut off mid-write never gets here: _mend_tail sets it aside.)"""
    return (f"{path} line {number} is damaged ({error}), and the campaign is read from its log: mend that line by hand, "
            "or put back a copy of the file from before it broke (state.json is made from the log, so it is no help)")


def _write_line(path, line):
    """Add a line to the end of the log and onto the disk before the command goes on: the log is the
    campaign. A write that fails takes back what it wrote, so the log never ends in half an event."""
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o666)
    try:
        size = os.fstat(fd).st_size
        try:
            written = 0
            while written < len(line):
                written += os.write(fd, line[written:])
            os.fsync(fd)
        except BaseException:
            os.ftruncate(fd, size)
            raise
    finally:
        os.close(fd)


def _saved(path):
    """(the seq state.json was written at, what it was made from): the first things in it. None when there are none to read."""
    try:
        with open(path, "rb") as saved:
            found = re.match(rb'\{\s*"seq":\s*(\d+),\s*"made_from":\s*(\d+)', saved.read(96))
    except OSError:
        return None
    return (int(found.group(1)), int(found.group(2))) if found else None


def _read_kept(c, log):
    """The replay kept for the next command, if it stands: the log's first `size` bytes are the
    ones it was made from, and so are the packs and the engine."""
    try:
        kept = marshal.loads((c.root / ".solo" / "replay.marshal").read_bytes())
    except (OSError, EOFError, ValueError, TypeError):
        return None
    if not (isinstance(kept, dict) and kept.get("count", len(c.events) + 1) <= len(c.events) and kept.get("size", len(log) + 1) <= len(log)
            and zlib.crc32(memoryview(log)[:kept["size"]]) == kept.get("crc") and kept.get("key") == c.key):
        return None
    for entry, event in zip(kept["entries"], c.events):
        entry["event"] = event
    return kept


def _replay_key(c):
    """What a kept replay was made from: this Python, the engine's code, and the packs as read."""
    engine = [(path.name, stat.st_mtime_ns, stat.st_size) for path in sorted(Path(__file__).parent.glob("*.py")) for stat in [path.stat()]]
    return [list(sys.version_info[:3]), engine, zlib.crc32(json.dumps([c.system, c.adventure], default=str).encode())]


def _mend_tail(path):
    """Every event is written as one line ending in a newline, so a last line without one
    was cut off mid-write (a crash, a power cut). Nothing has read it yet: set it aside in
    events.jsonl.torn and carry on. A complete event that only lost its newline gets it
    back, or the next event would be written onto the same line."""
    data = path.read_bytes()
    if not data or data.endswith(b"\n"):
        return
    cut = data.rfind(b"\n") + 1
    try:
        json.loads(data[cut:].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        with open(path.with_name(path.name + ".torn"), "ab") as torn:
            torn.write(data[cut:] + b"\n")
        with open(path, "r+b") as log:
            log.truncate(cut)
    else:
        with open(path, "ab") as log:
            log.write(b"\n")
