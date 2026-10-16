"""A campaign folder: the event log, the state derived from it, and every action that appends to it.

events.jsonl is the source of truth. state.json is fold(packs, events), rewritten after
each command for the panel, and safe to delete: `solo rebuild` recreates it. So is
.solo/replay.marshal, where a long campaign keeps its replay for the next command.

This file holds session(), which opens a campaign under the folder's lock, and Campaign's
commands: rolls, moves, fights, magic, rests, the oracle, tracks, clocks and threats. The
rest of it lives beside it. reducer.py folds the events into the state and tells each in a
line, and does no I/O. eventlog.py reads and writes the folder: Campaign takes its opening,
append, keep and save from eventlog.Log. commits.py checks what a commit says: Campaign
takes that from commits.Commits. The names the engine and the tests read here
(campaign.apply, campaign.describe, campaign.snapshot ...) are imported back.
"""

import copy
import fcntl
import re
import sys
from collections import Counter
from contextlib import contextmanager
from difflib import get_close_matches
from pathlib import Path

from . import SoloError, combat, creation, dice, library, magic, mechanics, oracle, packs
from .commits import Commits, _clamp, _listed, _plural, _shift
from .eventlog import Log, _saved
from .packs import _attitude_word, slug
from .reducer import LIKELIHOOD, _odds_levels, gm_line, profile_of, ready, replay
# The rest of the engine and the tests read these here, where they were before reducer.py, eventlog.py and commits.py.
from .commits import _CLOCK, _COMMIT_KEYS, _CONSEQUENCE_KEYS, _NPC_FIELDS, _PROMISE_KEYS, PROFILE_FIELDS  # noqa: F401
from .eventlog import _KEEP_EVERY, snapshot  # noqa: F401
from .reducer import _GOES_ON, _fold, apply, burn_option, chronology, codex, describe, fold, moments, people_here, recall, route  # noqa: F401

_ODDS = ["very unlikely", "unlikely", "even", "likely", "very likely"]
SPEAKERS = ("gm", "player")
# The GM is reminded to write a chronicle entry after this many of its messages without one.
CHRONICLE_EVERY = 12
# The event log's format, written into `created`, so a later change to what events hold can
# tell the logs written before it apart.
FORMAT = 1
# The campaigns open in this process, the innermost last (see session): a command's dice fixed by
# SOLO_SEED are seeded by the event it writes first (next_seq).
_OPEN = []


def find(start=None):
    """The campaign folder at or above `start`, or else at or above the working directory,
    falling back to the current campaign recorded by `solo use`. A folder named on purpose
    (-C) never falls back: a stale path must not roll dice in some other game."""
    here = Path(start or Path.cwd()).expanduser().resolve()
    found = next((f for f in (here, *here.parents) if (f / "campaign.toml").exists()), None)
    if found is None and not start:
        found = library.current()
    if found is not None:
        return found
    elif start:
        raise SoloError(f"{here} isn't a campaign folder (no campaign.toml): pick one with `solo use <dir>`, or start one with `solo new <adventure>`")
    else:
        raise SoloError("no campaign here: start one with `solo new <adventure>` or pick one with `solo use <dir>`")


def next_seq():
    """The seq the next event of the campaign open now will have (1 when none is)."""
    return len(_OPEN[-1].events) + 1 if _OPEN else 1


def set_current(root):
    pointer = library.state_home() / "current"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(f"{Path(root).resolve()}\n", encoding="utf-8")


def create(root, system_path, adventure_path, character, title=None, prefs=None):
    """Start a campaign in `root` with `character`, a sheet or the path to one, and the
    player's table settings (tone, lines, veils). Refuses a folder that already holds a campaign."""
    root = Path(root).resolve()
    system = packs.load_system(system_path)
    adventure = packs.load_adventure(adventure_path, drafts=False)
    problems = packs.validate(system, adventure)
    if _taken(root):
        raise SoloError(f"{root} already holds a campaign")
    elif packs.missing(system):
        raise SoloError(packs.missing_text(system, packs.missing(system)))
    elif problems:
        raise SoloError("the packs need fixing first (solo validate):\n  " + "\n  ".join(problems))
    else:
        data = dict(character) if isinstance(character, dict) else packs.load_data(character)
        # A hero from an earlier campaign brings their story: what happened there, and the
        # hero.* facts the player gave them (see `hero`).
        past, carried, kept = data.pop("past", None), data.pop("facts", None), data.pop("kept", None)
        pc = character_sheet(data, system)
        root.mkdir(parents=True, exist_ok=True)
        config = {
            "title": title or adventure["title"],
            "system": str(Path(system_path).resolve()),
            "adventure": str(Path(adventure_path).resolve()),
        }
        with session(root, new=config) as campaign:
            event = campaign.append("created", format=FORMAT, title=config["title"], pc=pc, scene=adventure["start"],
                                    past=past or None, facts=carried or None, kept=kept or None)
            campaign._follow([f"scene:{adventure['start']}"], cause=event["seq"])
            campaign._voices(event["seq"])
            if prefs and any(prefs.values()):
                campaign.set_prefs(**prefs)
        # The Book watches the GM's turn file, and a watch set on a file that isn't there yet
        # never fires: it waits here, idle, before the first turn writes it.
        (root / ".solo").mkdir(exist_ok=True)
        (root / ".solo" / "turn.json").write_text('{"status": "idle"}\n', encoding="utf-8")
        set_current(root)
        return root


def _taken(root):
    """Whether a folder holds a campaign `solo new` must leave alone: a whole event in its log, or a campaign.toml solo
    didn't write (one without a system and an adventure). One solo wrote, with no events, is a start that stopped half
    way, begun again. Read only: a log another command is writing is never mended (see _mend_tail) from outside its lock."""
    toml = root / "campaign.toml"
    try:
        if toml.exists() and not all(isinstance(packs.load_data(toml).get(key), str) for key in ("system", "adventure")):
            return True
        return b"\n" in (root / "events.jsonl").read_bytes()
    except FileNotFoundError:
        return False
    except (SoloError, OSError):  # a campaign.toml that isn't TOML, or a folder it can't read: not one to write over
        return True


def hero(root, name=None):
    """The hero of an earlier campaign, as they stand now, to carry into a new adventure:
    skills and gear as they were earned, rested (tracks full, conditions gone). Their story
    comes too: each earlier adventure in a few lines (`past`), and the hero.* facts. The tracks
    a hero always has (bonds) come as they stand (`kept`)."""
    with session(root) as c:
        pc = copy.deepcopy(c.state["pc"])
        past = [*c.state["past"], _looking_back(c)]
        facts = {k: v for k, v in c.state["facts"].items() if k.startswith("hero.")}
        kept = {k: t["ticks"] for k, t in c.state["progress"].items() if k in ((c.state["labels"]["progress"] or {}).get("unranked") or {})}
    if pc["dead"]:
        raise SoloError(f"{pc['name']} died in {Path(root).name}; the dead stay in the Hall of the Fallen")
    return {
        "name": name or pc["name"], "info": pc["info"], "attributes": pc["attributes"], "skills": pc["skills"],
        # Momentum (the track with a reset) starts over at its own, on the new sheet.
        "tracks": {k: {"value": t["max"], "max": t["max"]} for k, t in pc["tracks"].items() if "reset" not in t},
        "conditions": [], "items": pc["items"], "abilities": pc["abilities"], "ratings": pc["ratings"],
        "past": past, "facts": facts, "kept": kept,
    }


def _looking_back(c):
    """One adventure as the hero carries it into the next: how it ended, the last chronicle
    entries, what was left open, and the people who will remember them."""
    state = c.state
    people = [
        f"{npc['name']} ({_attitude_word(npc['attitude'])}" + (f", {npc['fate']}" if npc["fate"] != "alive" else "") + ")"
        + (f": {npc['memories'][-1]}" if npc["memories"] else "")
        for nid, npc in state["npcs"].items()
        if npc["met"] and npc["memories"] and not profile_of(c.adventure, state, nid).get("many")
    ]
    loose = [f"{p['terms']} (a promise, {state['npcs'].get(p['npc'], {}).get('name', p['npc'])})"
             for p in state["promises"].values() if p["status"] == "open"]
    loose += [k["text"] for k in state["consequences"].values() if k["status"] == "open"]
    return {
        "title": c.config["title"], "ended": (state["ended"] or {}).get("text"),
        "chronicle": [entry["text"] for entry in state["chronicle"][-3:]],
        "loose_ends": loose, "people": people[-12:],
    }


def character_sheet(data, system):
    """Normalise a pc.toml / pc.json into the sheet the engine keeps in state."""
    tracks = {}
    for name, value in data.get("tracks", {}).items():
        if isinstance(value, dict):
            top = value.get("max", value.get("value", 0))
            tracks[name] = {"value": int(value.get("value", top)), "max": int(top)}
        else:
            tracks[name] = {"value": int(value), "max": int(value)}
    attributes = {k: int(v) for k, v in data.get("attributes", {}).items()}
    skills = {}
    for key, value in data.get("skills", {}).items():
        entry = value if isinstance(value, dict) else {"value": value}
        known = system["skills"].get(slug(key), {})
        skills[slug(key)] = {
            "value": int(entry.get("value", 0)),
            "attribute": entry.get("attribute") or known.get("attribute"),
            "name": entry.get("name") or known.get("name") or key,
            "trained": bool(entry.get("trained", True)),
        }
    # Every skill the system knows goes on the sheet, so the panel can offer it:
    # ones the sheet leaves out are untrained, at their base chance.
    for key, skill in system["skills"].items():
        if key not in skills and skill["untrained"]:
            value = packs.base_chance(system, attributes.get(skill["attribute"], 0))
            skills[key] = {"value": value, "attribute": skill["attribute"], "name": skill["name"], "trained": False}
    conditions = [slug(c) for c in data.get("conditions", [])]
    momentum = system.get("momentum")
    if momentum:
        # Momentum's ceiling and reset follow the hero's impacts; the value stays under the ceiling.
        limits = mechanics.momentum_limits(momentum, len(conditions))
        start = tracks.get("momentum", {}).get("value", limits["reset"])
        tracks["momentum"] = {"value": _clamp(start, momentum["min"], limits["max"]), "min": momentum["min"], **limits}
    sheet = {
        "name": data.get("name", "The hero"),
        "info": data.get("info", {}),
        "attributes": attributes,
        "skills": skills,
        "tracks": tracks,
        "conditions": conditions,
        "items": list(data.get("items", [])),
        "abilities": list(data.get("abilities", [])),
        "ratings": dict(data.get("ratings", {})),
        # The spells a mage knows (tricks among them) and the ones held ready; tricks are always ready.
        "spells": list(data.get("spells", [])),
        "prepared": list(data.get("prepared", [])),
    }
    attributes = system["attributes"]
    problems = (
        [f"missing attribute {a}" for a in attributes if a not in sheet["attributes"]]
        + [f"unknown attribute {a}" for a in sheet["attributes"] if a not in attributes]
        + [f"missing track {t}" for t in system["tracks"] if t not in tracks]
        + [f"unknown track {t}" for t in tracks if t not in system["tracks"]]
        + [f"unknown condition {c}" for c in sheet["conditions"] if c not in system["conditions"]]
        + [f"skill {k} has no attribute (add it to the system pack or give the skill an attribute)"
           for k, s in skills.items() if s["attribute"] not in attributes]
    )
    if problems:
        raise SoloError("character sheet: " + "; ".join(problems))
    else:
        return sheet


@contextmanager
def session(root, new=None):
    """Open a campaign under an exclusive lock, so the agent and the panel never write
    at the same time. state.json is rewritten on the way out if anything changed, or if it
    was behind the log or made by another engine or other packs, and a command that went
    through keeps the replay for the next one when it has fallen behind. `new`: the
    campaign.toml of a campaign being created, written here under the lock, unless a
    campaign has begun in the folder meanwhile."""
    root = Path(root)
    with open(root / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if new is not None and _taken(root):
            raise SoloError(f"{root} already holds a campaign")
        elif new is not None:
            (root / "campaign.toml").write_text("".join(f"{k} = {packs.toml_string(v)}\n" for k, v in new.items()), encoding="utf-8")
        campaign = Campaign(root, new=new is not None)
        count = len(campaign.events)
        # A crash between an event's write and state.json's leaves state.json behind the log, and an update
        # to the engine or the packs leaves it made by the old ones: any command brings it up to date, one that only reads too.
        behind = _saved(root / "state.json") != (campaign.state["seq"], campaign.made_from)
        _OPEN.append(campaign)
        try:
            yield campaign
        except BaseException:
            # What a failed command wrote before it failed stands (a roll is never taken back),
            # but the state it was changing may be half changed: take it from the log again.
            if len(campaign.events) != count or campaign.unwritten:
                campaign.state, campaign.entries = replay(campaign.system, campaign.adventure, campaign.events)
            raise
        finally:
            _OPEN.remove(campaign)
            if len(campaign.events) != count and not campaign.unwritten:
                # Whatever changed (a move, time passing, a click on the panel) may be the
                # moment a consequence was waiting for. Not after a write that failed: the
                # log ends where the command stopped.
                campaign.come_due()
            if len(campaign.events) != count or behind:
                try:
                    campaign.save()
                except OSError as error:
                    # state.json is made from the log, which stands: a disk that refuses it (a full one) fails no command, one
                    # that only reads included, and a command whose events are written isn't one to run again. The next
                    # command catches it up. The disk that refused the log refuses state.json too, and has said so already.
                    if not campaign.unwritten:
                        print(f"solo: couldn't write {root / 'state.json'} ({error.strerror or error}): the log has everything, and the next "
                              "command brings state.json up to date once the disk takes it (until then the Table shows the campaign as it was)",
                              file=sys.stderr)
        campaign.keep()


class Campaign(Log, Commits):
    @property
    def problems(self):
        """What's wrong with the packs this campaign plays on, and events the replay passed over.
        The packs are read afresh every time, so an edit to one (a book's import laid over the
        bundled pack) reaches a campaign already under way: this says when it broke something."""
        return packs.validate(self.system, self.adventure) + self.state["problems"]

    def chronology(self):
        """The campaign replayed as moments with where and when (see `chronology`)."""
        return self.entries

    def come_due(self):
        """Consequences whose moment has just come (the hero walked back into the smithy, two
        shifts went by) are announced once, as a `due` event the GM reads and the player never
        sees. The GM pays it off in the story and commits it done."""
        for consequence_id, consequence in self.state["consequences"].items():
            if not consequence["due"] and ready(self.adventure, self.state, consequence):
                self.append("due", consequence=consequence_id, text=consequence["text"], npc=consequence["npc"])

    # Rolls -----------------------------------------------------------------------

    def check(self, name, boons=0, banes=0, rng=None, pushable=True, **extra):
        """Roll a skill or attribute. A condition tied to the roll's attribute adds a bane.
        `extra` marks what the roll is for (an attack, a defence) in the log."""
        if self.system["family"] == "action-roll":
            raise SoloError(f"{self.system['name']} rolls moves, not skills: solo act <move> --stat <stat> (solo rule moves)")
        self._able("roll")
        kind, key, label, attribute = self._stat(name)
        auto = self._condition_banes(attribute)
        gear = self._gear_banes(key, extra)
        outcome = self._resolve(kind, key, attribute, boons, banes + len(auto) + len(gear), rng)
        if not pushable:
            outcome["pushable"] = False
        if (extra.get("defend") or {}).get("needs_dragon"):
            outcome["success"] = bool(outcome.get("dragon"))  # against a critical hit only a Dragon defends
        event = self.append(
            "check", stat=key, kind=kind, label=label, attribute=attribute,
            boons=boons, banes=banes + len(auto) + len(gear), condition_banes=auto or None, gear_banes=gear or None, outcome=outcome, **extra,
        )
        self._after_roll(event, rng)
        return event

    def push(self, condition=None, rng=None, sole_survivor=False):
        """Push the last check once, while it is still the result the story waits on: a commit, a move,
        a rest or anything else _GOES_ON names after it, and it stands as it fell. The cost comes from
        the system pack: a condition the character doesn't have yet (Dragonbane) or a track increase
        (stress in Alien). A hero with Sole Survivor may pay willpower instead of a condition."""
        if self.system["family"] == "action-roll":
            raise SoloError("a roll can't be pushed here: after an action roll, momentum can be burned (solo burn)")
        self._able("push a roll")
        last = self.state["last_check"]
        cost = self.system["push"].get("cost", "condition")
        pc = self.state["pc"]
        if sole_survivor:
            ability = self._ability("push")
            if ability is None:
                raise SoloError(f"{pc['name']} doesn't have a heroic ability to push without a condition (Sole Survivor)")
            cost = {t: int(v) for t, v in ability["push"].items()}
            short = [t for t, v in cost.items() if pc["tracks"][t]["value"] < v]
            if short:
                raise SoloError(f"{ability.get('name', 'that')} costs {', '.join(f'{v} {t}' for t, v in cost.items())}, and {pc['name']} has too little {short[0]}")
            cost = {t: -v for t, v in cost.items()}
        available = [c for c in self.system["conditions"] if c not in pc["conditions"]]
        if last is None:
            raise SoloError("nothing to push: make a check first")
        elif last["type"] == "push":
            raise SoloError("that roll was already pushed")
        elif last.get("stood"):
            raise SoloError("that roll stands: the story went on after it (a commit, a move, a rest, a journey, a torch lit, "
                            "or a fight begun, gone on a round or ended), so it can't be pushed any more")
        elif not last["outcome"]["pushable"]:
            why = ("it succeeded" if last["outcome"].get("success") else "it was a Demon" if last["outcome"].get("demon")
                   else "the rules don't push this kind of roll")
            raise SoloError(f"that roll can't be pushed: {why}")
        elif cost == "condition" and not available:
            raise SoloError("every condition is already taken, so the roll can't be pushed")
        elif cost == "condition" and slug(condition or "") not in available:
            raise SoloError(f"choose the condition to take: {', '.join(available)}")
        else:
            if cost == "condition":
                changes = {"pc": {"conditions_add": [slug(condition)]}}
            else:
                tracks = {t: _clamp(pc["tracks"][t]["value"] + d, 0, pc["tracks"][t]["max"]) for t, d in cost.items()}
                changes = {"pc": {"tracks": tracks, "tracks_was": {t: pc["tracks"][t]["value"] for t in cost}}}
            if self.system["family"] == "d20-under":
                outcome = mechanics.d20_under(last["outcome"]["target"], last["boons"], last["banes"], rng)
            else:
                add = self.system["push"].get("add_dice", {})
                outcome = mechanics.d6_pool_push(last["outcome"], add, self.system.get("success", 6), rng)
            outcome["pushable"] = False
            event = self.append(
                "push", of=last["seq"], stat=last["stat"], kind=last["kind"], label=last["label"],
                attribute=last["attribute"], boons=last["boons"], banes=last["banes"],
                changes=changes, outcome=outcome, attack=last.get("attack"), cast=last.get("cast"), search=last.get("search"), quiet=last.get("quiet"),
            )
            self._after_roll(event, rng)
            if last.get("search"):
                self._searched(event, rng)
            # A pushed attack that now hits deals its damage, if the target still stands.
            target = (self.state["combat"] or {}).get("foes", {}).get((last.get("attack") or {}).get("target"))
            if outcome["success"] and target and not target["down"]:
                self._land(event, rng)
            if outcome["success"] and last.get("cast"):
                self._spell_lands(event, rng)
            return event

    # Moves --------------------------------------------------------------------------
    #
    # Action-roll systems (Ironsworn): the hero makes a move, the engine rolls what it asks
    # for and gives back the move's own words for the result. What that result gives or
    # costs (momentum, health, a mark of progress) is the GM's to commit; the engine keeps
    # the rolls honest and the progress tracks and momentum where the rules put them.

    def act(self, move_id, stat=None, adds=0, track=None, rng=None):
        """Make a move. An action roll adds `stat` (or, when the move says which, the highest
        or lowest of the stats it lists) and `adds` to the action die; a progress move sets
        the full boxes of a track against the challenge dice."""
        self._moves_only("make a move")
        self._able("make a move")
        move_id, move = self._move(move_id)
        if move["kind"] == "none":
            raise SoloError(f"{move['name']} has no roll: read it (solo rule {move['name'].lower()}) and commit what it says")
        # Checked before the roll before it stands: a move refused (a typo, no track open) leaves that roll open to a burn.
        if move["kind"] == "progress":
            self._open_track(move["track"], track)
        else:
            self._stat_for(move, stat)
        self._let_stand(rng)
        if move["kind"] == "progress":
            track_id, progress = self._open_track(move["track"], track)
            outcome = mechanics.progress_roll(progress["ticks"] // self.system["progress"]["ticks"], rng)
            event = self.append("act", move=move_id, label=move["name"], track=track_id, track_name=progress["name"], outcome=outcome)
        else:
            chosen, value = self._stat_for(move, stat)
            momentum = self.state["pc"]["tracks"]["momentum"]["value"]
            outcome = mechanics.action_roll(value, adds, momentum, rng)
            # A roll the player could still burn momentum on isn't the result yet: `open` holds back
            # what it sets off (a clock that listens for a miss) until it stands (see _let_stand).
            event = self.append("act", move=move_id, label=move["name"], stat=chosen, outcome=outcome,
                                open=True if momentum > 0 and mechanics.burn(outcome, momentum) else None)
        if not event.get("open"):
            self._follow(_triggers(outcome), event["seq"], rng)
        return event

    def burn(self, rng=None):
        """Burn momentum on the last action roll, while it is still open (see act): the challenge
        dice under it are cancelled, and momentum goes back to its reset."""
        self._moves_only("burn momentum")
        self._able("burn momentum")
        last, momentum = self.state["last_check"], self.state["pc"]["tracks"]["momentum"]
        if last is None or last["type"] not in ("act", "burn"):
            raise SoloError("nothing to burn momentum on: make a move first (solo act <move>)")
        elif last["type"] == "burn":
            raise SoloError("that roll was already burned")
        elif "track" in last:
            raise SoloError("momentum is ignored on a progress roll, so it can't be burned")
        elif momentum["value"] <= 0:
            raise SoloError(f"momentum is {momentum['value']}: only positive momentum can be burned")
        else:
            burned = mechanics.burn(last["outcome"], momentum["value"])
            if burned is None:
                raise SoloError(f"burning momentum {momentum['value']} wouldn't change the roll: every challenge die the score doesn't beat is at or above it")
            elif self.state["open_roll"] != last["seq"]:
                raise SoloError("that roll stands: the story went on after it (a commit, a move or another move made), so momentum can't be burned on it any more")
            changes = {"pc": {"tracks": {"momentum": momentum["reset"]}, "tracks_was": {"momentum": momentum["value"]}}}
            event = self.append("burn", of=last["seq"], move=last["move"], label=last["label"], stat=last.get("stat"), changes=changes, outcome=burned)
            self._follow(_triggers(burned), event["seq"], rng)
            return event

    def _let_stand(self, rng=None):
        """The story goes on, so a roll the player could have burned momentum on stands as it fell:
        what it sets off happens now."""
        seq = self.state["open_roll"]
        if seq is not None:
            self.append("settled", of=seq)
            self._follow(_triggers(self.state["last_check"]["outcome"]), seq, rng)

    def track_add(self, name, kind, rank=None):
        """Start a progress track: a vow, a journey or a fight, at a rank."""
        self._moves_only("keep a progress track")
        progress, kind, rank = self.system["progress"], slug(kind), slug(rank or "")
        if kind in progress.get("unranked", {}):
            raise SoloError(f"every hero has one {kind} track already: solo track mark {kind}")
        elif kind not in progress.get("kinds", {}):
            raise SoloError(f"a track is one of: {', '.join(progress.get('kinds', {}))}")
        elif rank not in progress["ranks"]:
            raise SoloError(f"give the {kind} a rank: {', '.join(progress['ranks'])}")
        else:
            taken, track_id, number = self.state["progress"], slug(name) or kind, 1
            while track_id in taken:
                number += 1
                track_id = f"{slug(name) or kind}_{number}"
            return self.append("progress", action="add", id=track_id, name=name.strip(), kind=kind, rank=rank)

    def track_mark(self, track_id, times=1):
        """Mark progress on a track, `times` over. A mark fills what the track's rank is worth
        (an unranked track, bonds, fills one tick)."""
        track_id, track = self._track(track_id)
        step = self.system["progress"]["ranks"][track["rank"]] if track["rank"] else 1
        if times < 1:
            raise SoloError("mark progress at least once")
        else:
            return self._progress(track_id, track, "mark", {"ticks": track["ticks"] + step * times}, times=times)

    def track_set(self, track_id, ticks=None, rank=None):
        """Correct a track: its ticks (a number sets them, "+4" or "-4" moves them) or its rank."""
        track_id, track = self._track(track_id)
        ranks = self.system["progress"]["ranks"]
        if ticks is None and rank is None:
            raise SoloError("set what? --ticks <n> or --rank <rank>")
        elif rank is not None and (track["rank"] is None or slug(rank) not in ranks):
            raise SoloError(f"{track['name']} has no rank to change" if track["rank"] is None else f"a rank is one of: {', '.join(ranks)}")
        else:
            now = {"ticks": _shift(ticks, track["ticks"]) if ticks is not None else track["ticks"],
                   "rank": slug(rank) if rank is not None else track["rank"]}
            return self._progress(track_id, track, "set", now)

    def track_end(self, track_id, how):
        """Close a track for good, saying how it ended (fulfilled, forsaken, won, lost)."""
        track_id, track = self._track(track_id)
        if track["kind"] in self.system["progress"].get("unranked", {}):
            raise SoloError(f"{track['name']} goes on: mark it or set its ticks, it doesn't end")
        else:
            return self.append("progress", action="end", id=track_id, name=track["name"], how=how)

    def _moves_only(self, action):
        if self.system["family"] != "action-roll":
            raise SoloError(f"{self.system['name']} has no moves to {action}: it rolls skills (solo check)")

    def _move(self, name):
        """A move by id or by name, or the ones it might have been."""
        moves, key = self.system["moves"], slug(name)
        found = key if key in moves else next((mid for mid, move in moves.items() if slug(move["name"]) == key), None)
        if found is None:
            close = get_close_matches(key, list(moves), n=3, cutoff=0.6)
            raise SoloError(f"no move called {name!r}" + (f"; did you mean {', '.join(close)}?" if close else "") + f"; moves: {', '.join(moves)}")
        return found, moves[found]

    def _stat_for(self, move, stat):
        """(stat, value) for a move's roll: the stat asked for, else the one the move lists,
        else the highest or lowest of them when the move says so (or `stat` says: highest, lowest)."""
        pc, options = self.state["pc"], move["stats"]
        values = {name: pc["attributes"][name] if name in pc["attributes"] else pc["tracks"][name]["value"] for name in options}
        choice = slug(stat) if stat else move.get("pick") or (options[0] if len(options) == 1 else None)
        if choice in ("highest", "lowest"):
            chosen = (max if choice == "highest" else min)(values, key=values.get)
        elif choice in values:
            chosen = choice
        else:
            raise SoloError(f"{move['name']} rolls +{', +'.join(options)}: say which with --stat (or --stat highest / lowest of them)")
        return chosen, values[chosen]

    def _track(self, name):
        """(id, track) of a track still open, by its id or its name."""
        tracks = {tid: t for tid, t in self.state["progress"].items() if not t["ended"]}
        key = slug(name)
        found = key if key in tracks else next((tid for tid, t in tracks.items() if slug(t["name"]) == key), None)
        if found is None:
            raise SoloError(f"no open track called {name!r}; open: {', '.join(tracks) or 'none (solo track add)'}")
        return found, tracks[found]

    def _open_track(self, kind, name):
        """The track a progress move reads: the one named, or the only open one of its kind."""
        tracks = {tid: t for tid, t in self.state["progress"].items() if t["kind"] == kind and not t["ended"]}
        if name:
            found, track = self._track(name)
            if track["kind"] != kind:
                raise SoloError(f"{track['name']} is a {track['kind']}, and this move reads a {kind}: {', '.join(tracks) or 'none open'}")
            return found, track
        elif len(tracks) == 1:
            return next(iter(tracks.items()))
        else:
            raise SoloError(f"which {kind}? --track <id>; open: {', '.join(tracks) or 'none (solo track add)'}")

    def _progress(self, track_id, track, action, now, **extra):
        """Record a change to a track: what it held (`was`), what it holds (`now`, its ticks
        kept between none and the full track) and how many boxes that fills."""
        spec = self.system["progress"]
        now = {**now, "ticks": _clamp(now["ticks"], 0, spec["boxes"] * spec["ticks"])}
        return self.append("progress", action=action, id=track_id, name=track["name"], was={k: track[k] for k in now},
                           now=now, boxes=now["ticks"] // spec["ticks"], part=now["ticks"] % spec["ticks"], **extra)

    def roll(self, expr, reason=None, rng=None):
        """Any dice expression; @track reads a track, as in 1d6+@stress."""
        return self.append("roll", expr=expr, reason=reason, result=dice.roll(self._substitute(expr), rng))

    def table(self, table_id, rng=None, cause=None, depth=0):
        """Roll on a table. A result can finish itself: `roll` (its value, put where the text
        says {value}: "{value} silver coins"),
        `choices` (one picked: the dagger or the longsword), `then` (another table to roll,
        like a treasure card) and `again` (roll this table once more)."""
        key, table, rolled, hit = self._roll_table(table_id, rng)
        hit = hit or {}
        text = hit.get("text", "") if hit else f"(the table has no result for {rolled['total']})"
        extra = {}
        if hit.get("choices"):
            extra["choice"] = hit["choices"][dice.pick(len(hit["choices"]), rng) - 1]
            text = f"{text}: {extra['choice']}"
        if hit.get("roll"):
            value = dice.roll(hit["roll"], rng)
            extra.update(value=value["total"], value_roll=value)
            text = text.replace("{value}", str(value["total"])) if "{value}" in text else f"{text} ({hit['roll']}: {value['total']})"
        if hit.get("effect"):
            extra["effect"] = hit["effect"]
        event = self.append("table", table=key, name=table.get("name", key), roll=rolled, total=rolled["total"], text=text, cause=cause, **extra)
        if depth < 5:
            follow = [hit["then"]] if isinstance(hit.get("then"), str) else list(hit.get("then", []))
            for next_id in follow + ([key] if hit.get("again") else []):
                self.table(next_id, rng=rng, cause=event["seq"], depth=depth + 1)
        return event

    def ask(self, question, likely=None, npc=None, rng=None, kind=None):
        """Oracle for questions neither the adventure nor the rules answer. Likelihood is
        given, or read from an NPC's attitude and promises; it is never chosen to please.
        A system with a fortune chart (Dragonbane's solo rules) reads it; otherwise the
        likelihood oracle, where doubles within the chaos factor set off a random event."""
        if npc is not None and npc not in self.state["npcs"]:
            raise SoloError(f"unknown npc {npc!r}")
        elif self.system.get("oracle", {}).get("chart") == "odds":
            return self._odds(question, likely, npc, kind, rng)
        level = (likely or (self._odds_for(npc) if npc else "even")).replace("_", " ")
        if self._chart():
            return self._fortune(question, level, kind or ("reaction" if npc and not likely else "yes_no"), npc, rng)
        elif kind:
            raise SoloError(f"{self.system['name']} has no fortune chart, so questions are yes or no (or --meaning)")
        if level in LIKELIHOOD:
            chance = LIKELIHOOD[level]
            roll = dice.roll("1d100", rng)["total"]
            if roll <= chance // 5:
                answer = "yes, and"
            elif roll <= chance:
                answer = "yes"
            elif roll > 100 - (100 - chance) // 5:
                answer = "no, and"
            else:
                answer = "no"
            surprise = self._random_event(rng) if oracle.is_event(roll, self.state["chaos"]) else None
            return self.append("oracle", question=question, likely=level, chance=chance, roll=roll, answer=answer, npc=npc, random_event=surprise)
        else:
            raise SoloError(f"likelihood must be one of: {', '.join(LIKELIHOOD)}")

    def meaning(self, question=None, rng=None):
        """Words for a question a yes or no can't answer: the system's inspiration columns
        (Dragonbane: an action, an attribute and a thing), or an action and a subject."""
        columns = self.system.get("oracle", {}).get("inspiration")
        tables = self._tables()
        if columns:
            words = [self._roll_table(column, rng)[3].get("text", "") for column in columns]
        else:
            words = oracle.meaning(tables, rng)
        return self.append("meaning", question=(question or "").strip() or None, words=words)

    def _odds(self, question, likely, npc, kind, rng):
        """The odds oracle (Ironsworn): a d100 against the chance of a yes at the odds given,
        or at the ones an NPC's attitude sets. A match (11, 22 ... 99, 100) is an extreme result or a twist."""
        chances, levels = self.system["oracle"]["odds"], _odds_levels(self.system)
        even = next(level for level, chance in chances.items() if chance == 50)
        level = str(likely or (levels[self._odds_step(npc)] if npc else even)).replace("_", " ").lower()
        level = even if level == "even" else level
        if kind:
            raise SoloError(f"{self.system['name']}'s oracle has no columns, so questions are yes or no (or --meaning)")
        elif level not in chances:
            raise SoloError(f"the odds are one of: {', '.join(levels)}")
        else:
            roll = dice.roll("1d100", rng)["total"]
            return self.append("oracle", question=question, chart="odds", likely=level, chance=chances[level], roll=roll,
                               answer="yes" if roll > 100 - chances[level] else "no", match=roll % 11 == 0 or roll == 100, npc=npc)

    def _chart(self):
        return self.system.get("oracle", {}).get("fortune") if self.system.get("oracle", {}).get("chart") == "fortune" else None

    def _fortune(self, question, level, kind, npc, rng):
        """The fortune chart: a D6 read in the column that fits the question. Likely high
        results roll 2D6 and keep the highest, likely low ones keep the lowest."""
        chart = self._chart()
        columns = {k: v for k, v in chart.items() if k != "bands"}
        kind = slug(kind)
        if kind not in columns:
            raise SoloError(f"the fortune chart reads {', '.join(columns)}; not {kind!r}")
        if level not in LIKELIHOOD:
            raise SoloError(f"likelihood must be one of: {', '.join(LIKELIHOOD)}")
        tilt = "high" if LIKELIHOOD[level] > 50 else "low" if LIKELIHOOD[level] < 50 else None
        formula = {"high": "2d6kh1", "low": "2d6kl1", None: "1d6"}[tilt]
        rolled = dice.roll(formula, rng)
        band = next(i for i, (low, high) in enumerate(chart["bands"]) if low <= rolled["total"] <= high)
        return self.append("oracle", question=question, chart="fortune", kind=kind, likely=level, tilt=tilt, dice=rolled,
                           roll=rolled["total"], answer=columns[kind][band], extreme=rolled["total"] in (1, 6), npc=npc)

    # Story ------------------------------------------------------------------------

    def say(self, text, by="gm"):
        """Record what the GM told the player, or what the player said, word for word, so a
        closed session reopens exactly where it stopped. The same words twice in a row from
        the same speaker are recorded once (a hook and a GM can both report a reply)."""
        text = (text or "").strip()
        if by not in SPEAKERS:
            raise SoloError(f"a speaker is one of: {', '.join(SPEAKERS)}")
        elif not text:
            raise SoloError("nothing to record: the text is empty")
        last = next((e for e in reversed(self.events) if e["type"] == "said"), None)
        if last is not None and last["by"] == by and last["text"] == text:
            return None
        else:
            return self.append("said", by=by, text=text, scene=self.state["scene"])

    def move(self, target, force=None, rng=None):
        """Take an exit (by scene id or label). `force` jumps to any scene and records why.
        An ordinary move rolls a scene check against the chaos factor: the scene may be
        altered, or interrupted by a random event. Forced moves (a clock filled) aren't checked."""
        self._able("move")
        # Checked before the roll before it stands: a move refused (a typo, a shut door) leaves that roll open to a burn.
        self._way(target, force)
        self._let_stand(rng)
        here, every, destination = self._way(target, force)
        check = None
        if not force and self.adventure["scene_checks"] and self.system.get("oracle", {}).get("scene_checks", True):
            check = oracle.scene_check(self.state["chaos"], rng)
            if check["result"] == "interrupted":
                check["event"] = self._random_event(rng)
        spent = {} if force else (every[destination]["time"] if destination in every and every[destination]["time"] else self.adventure["move_time"])
        seconds = self._seconds(spent)
        before = self.state["time"]
        event = self.append("move", to=destination, forced=force, scene_check=check, time=seconds or None, **{"from": here})
        self._follow(Counter([f"scene:{destination}"]) + self._time_triggers(before, before + seconds), cause=event["seq"], rng=rng)
        if seconds:
            self._burn(event["seq"])
        self._voices(event["seq"], rng)
        return event

    def _way(self, target, force=None):
        """(the scene the hero is in, its exits, the scene `target` leads to), or a sentence saying why it leads nowhere."""
        here = self.state["scene"]
        every = packs.exits(self.adventure, here)
        key = slug(target)
        destination = key if key in every else self._exit_by_label(every, key, target)
        if destination is None and force and key in self.adventure["scenes"]:
            destination = key
        if destination is None:
            listed = ", ".join(f"{sid} ({spec['label']})" for sid, spec in every.items() if packs.is_open(spec, self.state)) or "none"
            raise SoloError(f"no exit {target!r} from {here}; exits: {listed}")
        elif not force and destination in every and not packs.is_open(every[destination], self.state):
            # A gated way (hidden stairs, a locked door) stays shut until the story opens it.
            raise SoloError(f"the way to {destination} isn't open yet (it opens when {every[destination]['when']}); "
                            "if the hero opened it, commit that first")
        return here, every, destination

    def _exit_by_label(self, every, key, target):
        """An exit by its label, or a word of it: a whole label first, then the one exit it
        fits, the open ones before those still shut. A word that fits two ways is refused
        rather than guessed, because a move can't be taken back."""
        fits = [sid for sid, spec in every.items() if key and key in slug(spec["label"])]
        whole = [sid for sid in fits if slug(every[sid]["label"]) == key]
        picks = whole or [sid for sid in fits if packs.is_open(every[sid], self.state)] or fits
        if len(picks) > 1:
            named = ", ".join(f"{sid} ({every[sid]['label']})" for sid in picks)
            raise SoloError(f"{target!r} could be {named}: name the exit")
        return picks[0] if picks else None

    # Voices ---------------------------------------------------------------------------
    #
    # The hero's skills speak up, the way they do in Disco Elysium. A scene lists voices
    # (a skill and what it notices); entering the scene rolls each one quietly. A success
    # puts the line in the Book and in `solo scene`; a failure stays silent, so the player
    # never learns what they missed. The GM can raise one too with `solo voice`.

    def voice(self, skill, text, rng=None):
        """The GM offers a thought one of the hero's skills might have; the dice decide
        whether the hero has it. The line is recorded (and shown) only on a success."""
        self._able("notice anything")
        text = (text or "").strip()
        if not text:
            raise SoloError("a voice needs the line the skill would say")
        return self._voice(skill, text, source="gm", rng=rng)

    def _voices(self, cause, rng=None):
        scene_id = self.state["scene"]
        if self.state["pc"]["dead"] or self.state["pc"]["dying"] or self.system["family"] == "action-roll":
            # A game of moves has no quiet skill rolls: what the hero notices is in the scene's text.
            return
        for index, spec in enumerate(self.adventure["scenes"][scene_id].get("voices", [])):
            if not spec.get("when") or packs.evaluate(spec["when"], self.state):
                self._voice(spec["skill"], spec["text"], source="scene", rng=rng, cause=cause, index=index,
                            clue=spec.get("clue"), boons=int(spec.get("boons", 0)), banes=int(spec.get("banes", 0)))

    def _voice(self, skill, text, source, rng=None, cause=None, index=None, clue=None, boons=0, banes=0):
        kind, key, label, attribute = self._stat(skill)
        auto = self._condition_banes(attribute)
        outcome = self._resolve(kind, key, attribute, boons, banes + len(auto), rng)
        outcome["pushable"] = False
        heard = bool(outcome["success"])
        return self.append(
            "voice", stat=key, label=label, text=text, heard=heard, outcome=outcome, source=source,
            scene=self.state["scene"], cause=cause, index=index, clue=slug(clue) if clue and heard else None,
        )

    # Searching and scavenging -------------------------------------------------------------

    def search(self, rng=None):
        """Search an area with care (the solo rules, p. 10): it takes a stretch, so active
        threats advance, then SPOT HIDDEN. A Dragon rolls the search table twice (the player
        picks one), a success once, a failure finds nothing, and a Demon finds nothing and
        brings a new danger."""
        self._able("search")
        spec = self.system.get("search")
        if not spec:
            raise SoloError(f"{self.system['name']} has no [search] in its system pack")
        self._record("commit", {"note": "a careful search", "time": spec.get("time", {})}, rng)
        event = self.check(spec["skill"], rng=rng, search=True, quiet=True)
        self._searched(event, rng)
        return event

    def _searched(self, event, rng):
        outcome, table = event["outcome"], self.system["search"]["table"]
        if outcome.get("success"):
            for _ in range(2 if outcome.get("dragon") else 1):
                self.table(table, rng=rng, cause=event["seq"])

    def scavenge(self, again=False, rng=None):
        """Rummage through something specific (p. 9): a minute or two, but scavenging the same
        place again takes a stretch, and active threats advance."""
        self._able("scavenge")
        spec = self.system.get("scavenge")
        if not spec:
            raise SoloError(f"{self.system['name']} has no [scavenge] in its system pack")
        if again:
            self._record("commit", {"note": "scavenging again", "time": spec.get("again_time", {})}, rng)
        return self.table(spec["table"], rng=rng)

    # Light ----------------------------------------------------------------------------
    #
    # A torch burns down as game time passes (the system pack says for how long). The Book
    # draws it; the GM reads "It's dark here" in `solo scene` when the scene is dark and
    # nothing burns.

    def light(self, source=None, rng=None):
        """Light a carried light source: one comes off the hero's gear."""
        self._able("light anything")
        sources = self.system.get("light", {})
        key = slug(source) if source else next(iter(sources), None)
        spec = sources.get(key or "")
        if not sources:
            raise SoloError(f"{self.system['name']} has no [light] section in its system pack")
        elif spec is None:
            raise SoloError(f"no light source {source!r}; the system has {', '.join(sources)}")
        elif self.state["light"]:
            raise SoloError(f"{self.state['light']['label'].lower()} is already burning")
        item = spec.get("item", key)
        carried = next((i for i in self.state["pc"]["items"] if _count_of(i, item) is not None), None)
        if carried is None:
            raise SoloError(f"{self.state['pc']['name']} isn't carrying a {item}")
        left = _count_of(carried, item) - 1
        items = {"remove": [carried], "add": [f"{left} {_plural(item)}" if left > 1 else item] if left else []}
        burns = sum(int(self.system["time"][unit] * amount) for unit, amount in spec.get("lasts", {"shift": 1}).items())
        label = spec.get("label", key.capitalize())
        return self._record("light", {"note": f"lit a {label.lower()}", "pc": {"items": items}}, rng, source=key, label=label, lit=True, burns=burns)

    def snuff(self):
        lit = self.state["light"]
        if lit is None:
            raise SoloError("nothing is burning")
        return self.append("light", source=lit["source"], label=lit["label"], lit=False, reason="put out", changes={})

    def _burn(self, cause):
        """A light that has burned its time goes out (called after time passes)."""
        lit = self.state["light"]
        if lit and self.state["time"] >= lit["lit_at"] + lit["burns"]:
            self.append("light", source=lit["source"], label=lit["label"], lit=False, reason="burned out", cause=cause, changes={})

    def commit(self, payload, rng=None):
        """Apply the consequences the agent proposes, after checking them against the packs."""
        # Checked before the roll before it stands, and again after it (what the roll set off may have moved a clock):
        # a commit refused leaves that roll open to a burn.
        self._normalize(payload)
        self._let_stand(rng)
        return self._record("commit", payload, rng)

    def rest(self, rest_id, heal=None, rng=None, tend=False, use=()):
        """A rest from the system pack: recover tracks, heal conditions, let time pass (which
        may tick clocks). A `limit` allows one per time unit: Dragonbane's round and stretch
        rests are once per shift. `heal` names the condition to heal first."""
        self._able("rest")
        key = slug(rest_id)
        spec = self.system["rest"].get(key)
        pc = self.state["pc"]
        if self.state["combat"]:
            raise SoloError("no resting in the middle of a fight")
        elif spec is None:
            raise SoloError(f"no rest {rest_id!r}; rests: {', '.join(self.system['rest']) or 'none'}")
        label = spec.get("label", key.capitalize())
        unit = self.system["time"].get(spec.get("limit"))
        taken = self.state["rests"].get(key)
        if unit and taken is not None and taken // unit == self.state["time"] // unit:
            raise SoloError(f"you've already taken a {label.lower()} this {spec['limit']}")
        elif heal and not spec.get("heal"):
            raise SoloError(f"a {label.lower()} heals no conditions; {self._healing_rests()}")
        elif heal and slug(heal) not in pc["conditions"]:
            raise SoloError(f"you don't have {heal}; conditions: {', '.join(pc['conditions']) or 'none'}")
        else:
            tracks, rolls = {}, {}
            recover = dict(spec.get("recover", {}))
            tended, more = None, {}
            for name in _listed(use):
                aid, ability = self._held(name)
                if not ability.get("heal") or ability.get("rest") != key:
                    raise SoloError(f"{ability['name']} adds nothing to a {label.lower()}")
                self._pay(aid, ability)
                more[ability.get("heals", "hp")] = more.get(ability.get("heals", "hp"), 0) + dice.roll(ability["heal"], rng)["total"]
            if tend:
                # The solo hero tends their own wounds: a skill roll, and more back on a success.
                if not spec.get("tend"):
                    raise SoloError(f"a {label.lower()} has no tending in {self.system['name']}'s rules")
                tended = self.check(spec["tend"]["skill"], rng=rng, quiet=True)
                if tended["outcome"]["success"]:
                    recover.update(spec["tend"].get("recover", {}))
                pc = self.state["pc"]
            for track, amount in recover.items():
                current = pc["tracks"][track]
                if amount == "max":
                    value = current["max"]
                else:
                    rolls[track] = dice.roll(amount, rng)["total"] + more.get(track, 0)
                    value = min(current["max"], current["value"] + rolls[track])
                if value != current["value"]:
                    tracks[track] = value
            held = ([slug(heal)] if heal else []) + [c for c in pc["conditions"] if c != slug(heal or "")]
            count = len(held) if spec.get("heal") == "all" else int(spec.get("heal", 0))
            payload = {"note": label, "pc": {**tracks, "conditions": {"remove": held[:count]}}, "time": spec.get("time", {})}
            return self._record("rest", payload, rng, rest=key, rolls=rolls or None, tended=tended and tended["seq"])

    def _healing_rests(self):
        healing = [r.get("label", rid.capitalize()).lower() for rid, r in self.system["rest"].items() if r.get("heal")]
        return f"a {' or a '.join(healing)} does" if healing else "no rest does"

    # Fights -------------------------------------------------------------------------
    #
    # The minimum a fight needs to run from code: who acts when, whether a blow lands,
    # and how much gets through armor. Tactics, morale and what a hit looks like stay
    # with the GM. Foes need stats.hp (and armor) in the adventure's NPC files, plus an
    # `attack` (a skill roll) or `attacks` (a monster table whose results carry damage).

    def fight(self, foes, rng=None):
        """Start a fight with these NPCs (repeat an id for several of the same kind) and
        deal initiative for the first round."""
        self._able("start a fight")
        if self.state["combat"]:
            raise SoloError("a fight is already on: solo fight --round for the next round, or solo fight --end")
        elif not self.system.get("combat"):
            raise SoloError(f"{self.system['name']} has no [combat] section, so fights are narrated and committed")
        elif not foes:
            raise SoloError("name who the hero fights: solo fight <npc> [<npc> ...]")
        roster = self._roster(foes, {})
        return self.append("fight", foes=roster, round=1, order=self._initiative(roster, rng))

    def join(self, foes, rng=None):
        """More foes enter the fight. They draw from the cards left this round."""
        fight = self._fight()
        joining = self._roster(foes, fight["foes"])
        used = {f["card"] for f in fight["order"]}
        left = [c for c in range(1, int(self.system["combat"].get("initiative", 10)) + 1) if c not in used]
        if len(joining) > len(left):
            raise SoloError("not enough initiative cards left this round; join them next round")
        if sum(self._cards(fid, foe) for fid, foe in joining.items()) > len(left):
            raise SoloError("not enough initiative cards left this round; join them next round")
        order = []
        for foe_id, foe in joining.items():
            for _ in range(self._cards(foe_id, foe)):
                card = left.pop(dice.pick(len(left), rng) - 1)
                order.append({"id": foe_id, "name": foe["name"], "card": card})
        order = sorted(fight["order"] + order, key=lambda f: f["card"])
        return self.append("join", foes=joining, order=order)

    def next_round(self, rng=None, use=()):
        """A new round: every fighter still standing draws a new initiative card."""
        fight = self._fight()
        self._no_choice_waiting()
        # A round is game time too (ten seconds in Dragonbane), so a clock can count rounds.
        seconds = int(self.system["time"].get("round", 0))
        before = self.state["time"]
        event = self.append("round", round=fight["round"] + 1, order=self._initiative(fight["foes"], rng, use), time=seconds or None)
        if seconds:
            self._follow(self._time_triggers(before, before + seconds), event["seq"], rng)
            self._burn(event["seq"])
        return event

    def end_fight(self):
        fight = self._fight()
        standing = [f["name"] for f in fight["foes"].values() if not f["down"]]
        return self.append("fight_end", rounds=fight["round"], standing=standing)

    def attack(self, target=None, weapon=None, boons=0, banes=0, distance=None, defended=None, kind=None, use=(), rng=None):
        """The hero attacks a foe with a carried weapon: a skill check, then on a hit the
        weapon's damage (plus the hero's damage bonus) minus the foe's armor. `distance`, in meters,
        is how far the foe is: a bow shot from too near or too far, or a blow out of reach, says so.
        `defended` is what the foe does about it (dodge or parry, using one of its actions); `kind` is the
        damage a weapon that cuts and stabs does (slashing or piercing); `use` names heroic abilities the
        blow uses (more damage), paid for when it hits."""
        self._no_choice_waiting()
        if self._fight()["incoming"]:
            raise SoloError("answer the hit coming at the hero first: defend evade, parry or take")
        foe_id = self._foe(target)
        pc = self.state["pc"]
        arm = combat.weapon(self.system, pc, weapon, "attack")
        turns = sum(1 for f in self._fight()["order"] if f["id"] == "pc")
        if self._count_this_round(lambda e: e["type"] == "check" and e.get("attack") and not e["attack"].get("free")) >= turns:
            raise SoloError(f"{pc['name']} has already attacked this round; the next round comes with solo fight --round")
        elif "requires_quiver" in arm["features"] and not any(slug(item).startswith("quiver") for item in pc["items"]):
            raise SoloError(f"the {arm['label'].lower()} needs a quiver, and {pc['name']} carries none")
        if kind and kind not in combat.damage_types(arm):
            raise SoloError(f"the {arm['label'].lower()} can't do {kind} damage: {', '.join(combat.damage_types(arm)) or 'no kind is given for it'}")
        riders = [self._rider(name, arm, foe_id) for name in _listed(use)]
        attack = {"weapon": arm["id"], "label": arm["label"], "target": foe_id, **({"distance": distance} if distance is not None else {}),
                  **({"defended": defended} if defended else {}), **({"kind": kind} if kind else {}), **({"use": riders} if riders else {})}
        event = self.check(arm["skill"], boons, banes, rng, attack=attack)
        if event["outcome"]["success"]:
            self._land(event, rng)
        return event

    def _land(self, event, rng):
        """The hero's attack hit: the foe may dodge or parry it (if the GM said so: it uses one of its
        actions), then a Dragon on the blow may wait for the player's choice, else the damage is rolled."""
        attack, outcome = event["attack"], event["outcome"]
        if attack.get("defended") and self._foe_defends(attack["target"], attack["defended"], outcome.get("dragon", False), event["seq"], rng):
            return
        for aid in attack.get("use", []):
            self._pay(aid, self.system["abilities"][aid])
        options = self._dragon_choices(attack, outcome)
        if options:
            self.append("choice", of=event["seq"], options=options, target=attack["target"])
        else:
            self._strike(event, rng)

    def _foe_defends(self, foe_id, how, critical, cause, rng):
        """A foe dodges or parries the hero's blow, which costs it one of its actions this round. A monster
        rolls the pack's [combat] monster_defense (15) and only one that carries weapons (`parries`) can
        parry; anyone else rolls their own EVADE or weapon skill, 5 where the stat block has none. Against
        a critical hit only a Dragon avoids it. True when the blow is avoided."""
        foe = self.state["combat"]["foes"][foe_id]
        profile, rules = self._profile(foe["npc"]), self.system["combat"]
        monster = bool(profile.get("attacks"))
        if how not in ("dodge", "parry"):
            raise SoloError("a foe dodges or parries: --defended dodge|parry")
        elif how == "parry" and monster and not profile.get("parries"):
            raise SoloError(f"{foe['name']} carries no weapon to parry with")
        skill = rules.get("evade", "evade") if how == "dodge" else (profile.get("attack") or {}).get("skill", rules.get("evade", "evade"))
        value = int(rules.get("monster_defense", 15)) if monster else int(profile.get("skills", {}).get(skill, 5))
        outcome = mechanics.d20_under(value, rng=rng)
        outcome["pushable"] = False
        avoided = bool(outcome["dragon"] if critical else outcome["success"])
        self.append("defence", foe=foe_id, name=foe["name"], how=how, outcome=outcome, avoided=avoided, critical=critical or None, cause=cause)
        return avoided

    def dragon(self, choice, target=None, rng=None):
        """What a Dragon on the hero's roll does, when the pack lets the player choose. On an attack: the
        weapon's dice twice (double), a second attack on another foe that costs no turn (attack), or a blow
        that armor doesn't blunt (pierce, a piercing weapon's). On a spell: its damage or range doubled
        (double), no cost in WP (free), or another spell at once, with a bane (another)."""
        waiting, choice = self.state["choice"], slug(choice)
        if not waiting:
            raise SoloError("no Dragon is waiting for a choice")
        elif choice not in waiting["options"]:
            raise SoloError(f"choose what the Dragon does: {', '.join(waiting['options'])}")
        source = next(e for e in self.events if e["seq"] == waiting["of"])
        chosen = self.append("dragon", of=waiting["of"], choice=choice)
        if waiting["kind"] == "spell":
            self._spell_lands(source, rng, choice=choice)
            return chosen
        self._strike(source, rng, choice=choice)
        if choice == "attack" and not self.state["pc"]["dead"]:
            foe_id = self._foe(target)
            if foe_id == source["attack"]["target"]:
                raise SoloError("the second attack is against another foe")
            arm = combat.weapons(self.system)[source["attack"]["weapon"]]
            free = self.check(arm["skill"], 0, 0, rng, attack={"weapon": arm["id"], "label": arm["label"], "target": foe_id, "free": True})
            if free["outcome"]["success"]:
                self._land(free, rng)
        return chosen

    def _dragon_choices(self, attack, outcome):
        """What a Dragon on the hero's attack can be, when the pack says the player chooses
        ([combat] dragon = "choice"): the weapon's dice twice; a free attack on another foe (a melee
        weapon and another foe standing); armor that doesn't count (a piercing weapon). One way to use
        it is no choice, and the blow is doubled."""
        if not (attack and outcome.get("dragon") and self.system.get("combat", {}).get("dragon") == "choice" and self.state["combat"]):
            return None
        arm = combat.weapons(self.system)[attack["weapon"]]
        others = [fid for fid, foe in self.state["combat"]["foes"].items() if not foe["down"] and fid != attack["target"]]
        options = ["double"] + ["attack"] * bool(others and not arm["ranged"]) + ["pierce"] * ("piercing" in arm["features"])
        return options if len(options) > 1 else None

    def _no_choice_waiting(self):
        if self.state["choice"]:
            raise SoloError("a Dragon is waiting for its choice first: solo dragon " + "|".join(self.state["choice"]["options"]))

    def enemy(self, foe=None, rng=None):
        """A foe attacks the hero. A monster rolls on its attack table; anyone else rolls
        their attack skill. A hit waits as `incoming` until the hero defends or takes it."""
        fight = self._fight()
        self._no_choice_waiting()
        if self.state["pc"]["dead"]:
            raise SoloError(f"{self.state['pc']['name']} is dead")
        elif fight["incoming"]:
            raise SoloError(f"{fight['incoming']['name']}'s attack is still waiting: defend evade, defend parry or defend take")
        foe_id = self._foe(foe)
        foe = fight["foes"][foe_id]
        profile = self._profile(foe["npc"])
        dragon_rule = self.system["combat"].get("dragon")
        attacker = profile.get("attacker")
        roles = attacker if isinstance(attacker, list) else [attacker] if attacker else []
        pending = (fight.get("pending") or {}).get(foe_id)
        if foe.get("regenerate") and foe["hp"] < foe["max"] and not pending:
            mended = dice.roll(foe["regenerate"], rng)
            self.append("heal", target=foe_id, name=foe["name"], roll=mended, hp=min(foe["max"], foe["hp"] + mended["total"]), hp_was=foe["hp"], by="regeneration")
        if (roles or pending) and self.system.get("npcs", {}).get("attacks"):
            return self._npc_turn(foe_id, foe, profile, roles, pending, rng)
        elif profile.get("attacks"):
            key, table, rolled, hit = self._roll_table(profile["attacks"], rng)
            results = table.get("results", [])
            index = next((i for i, r in enumerate(results) if r is hit), None)
            again = index is not None and self.system["combat"].get("monster_repeat") == "next" and foe.get("last_attack") == index
            if again:
                # A monster doesn't use one attack on two turns running: a repeated roll becomes the next on the table.
                index = (index + 1) % len(results)
                hit = results[index]
            hit = hit or {}
            damage = hit.get("damage")
            # Monster attacks can be evaded but, in Dragonbane, not parried unless the attack says so.
            parry = hit.get("parry", table.get("parry", self.system["combat"].get("monster_parry", True)))
            incoming = {"damage": damage, "can_defend": hit.get("defend", True), "can_parry": bool(parry), **({"kind": hit["kind"]} if hit.get("kind") else {})} if damage else None
            if incoming and hit.get("armor") is False:
                incoming["armor"] = False  # a ghost's hand through the chest: armor doesn't help
            detail = {"table": key, "total": rolled["total"], "text": hit.get("text", ""), "label": _attack_name(hit.get("text", ""), table.get("name", key)),
                      "index": index, **({"again": True} if again else {})}
        elif profile.get("attack"):
            spec = profile["attack"]
            if self.system["family"] != "d20-under":
                raise SoloError("skill attacks for foes are only built for d20-under systems; give the foe an attack table")
            value = int(spec.get("value") or profile.get("skills", {}).get(spec.get("skill", ""), 0))
            outcome = mechanics.d20_under(value, rng=rng)
            outcome["pushable"] = False
            damage = combat.damage_expression(spec["damage"], spec.get("bonus", ""), outcome["dragon"], "double" if dragon_rule == "choice" else dragon_rule)
            incoming = {"damage": damage, "can_defend": True, **({"critical": True} if outcome["dragon"] else {})} if outcome["success"] else None
            detail = {"outcome": outcome, "label": spec.get("label", "attack")}
        else:
            raise SoloError(f"{foe['name']} has no attack or attacks in the adventure pack; narrate it and commit the harm")
        if incoming:
            incoming.update({"from": foe_id, "name": foe["name"], "label": detail["label"]})
        return self.append("enemy", foe=foe_id, name=foe["name"], incoming=incoming, **detail)

    def _npc_turn(self, foe_id, foe, profile, roles, pending, rng):
        """A notable NPC's turn, from the solo rules' NPC attack table (p. 4): its role's
        column says what it does. An attack is a skill roll (it doesn't hit by itself), with
        the result's boons, banes and extra damage; anything else is for the GM to run."""
        if pending:
            role, entry, total = pending["role"], pending["entry"], pending["total"]
        else:
            role = roles[dice.pick(len(roles), rng) - 1] if len(roles) > 1 else roles[0]
            key, table, rolled, hit = self._roll_table(self.system["npcs"]["attacks"], rng)
            entry, total = (hit or {}).get(role, {}), rolled["total"]
        detail = {"table": "npc_attacks", "total": total, "text": entry.get("text", ""), "label": f"{role} attacker", "role": role}
        incoming, queued = None, None
        if entry.get("attack"):
            spec = profile.get("attack", {})
            value = int(spec.get("value") or profile.get("skills", {}).get(spec.get("skill", ""), 0))
            outcome = mechanics.d20_under(value, int(entry.get("boons", 0)), int(entry.get("banes", 0)), rng)
            outcome["pushable"] = False
            base = entry.get("damage") or spec.get("damage", "1d6")
            rule = self.system["combat"].get("dragon")
            damage = combat.damage_expression(base, spec.get("bonus", "") if not entry.get("damage") else "", outcome["dragon"], "double" if rule == "choice" else rule)
            if entry.get("extra"):
                damage += f"+{entry['extra']}"
            incoming = {"damage": damage, "can_defend": True, "from": foe_id, "name": foe["name"], "label": detail["label"],
                        **({"critical": True} if outcome["dragon"] else {}), **({"ranged": True} if role == "ranged" else {})} if outcome["success"] else None
            detail["outcome"] = outcome
            if int(entry.get("times", 1)) > 1 and not pending:
                # A volley: the second attack comes as the same result, without a new roll.
                queued = {"role": role, "entry": {**entry, "times": 1}, "total": total}
        return self.append("enemy", foe=foe_id, name=foe["name"], incoming=incoming, queued=queued, **detail)

    def ally(self, npc, target=None, rng=None):
        """An NPC fighting on the hero's side (Grukk, once he keeps his promise) attacks a foe
        with its own attack skill, once a round: the dice decide what an ally does, as they
        do for the hero. It isn't dealt initiative; the GM runs it when the story says."""
        fight = self._fight()
        npc_id = slug(npc)
        npc_state, profile = self.state["npcs"].get(npc_id), self._profile(npc_id)
        spec = profile.get("attack")
        if npc_state is None:
            raise SoloError(f"unknown npc {npc!r}; npcs: {', '.join(self.state['npcs']) or 'none'}")
        elif npc_state["fate"] != "alive":
            raise SoloError(f"{npc_state['name']} is {npc_state['fate']}")
        elif any(f["npc"] == npc_id and not f["down"] for f in fight["foes"].values()):
            raise SoloError(f"{npc_state['name']} is fighting against the hero in this fight")
        elif not spec or self.system["family"] != "d20-under":
            raise SoloError(f"{npc_state['name']} has no attack skill in the adventure pack; narrate what they do and commit it")
        elif self._this_round(lambda e: e["type"] == "ally" and e["npc"] == npc_id):
            raise SoloError(f"{npc_state['name']} has already attacked this round")
        foe_id = self._foe(target)
        foe = fight["foes"][foe_id]
        value = int(spec.get("value") or profile.get("skills", {}).get(spec.get("skill", ""), 0))
        outcome = mechanics.d20_under(value, rng=rng)
        outcome["pushable"] = False
        blow = {}
        if outcome["success"]:
            expr = combat.damage_expression(spec["damage"], spec.get("bonus", ""), outcome["dragon"], self.system["combat"].get("dragon"))
            rolled = dice.roll(expr, rng)
            dealt = max(0, rolled["total"] - foe["armor"])
            hp = max(0, foe["hp"] - dealt)
            blow = {"expr": expr, "roll": rolled, "armor": foe["armor"], "dealt": dealt, "hp": hp, "hp_was": foe["hp"], "down": hp == 0}
        event = self.append("ally", npc=npc_id, name=npc_state["name"], label=spec.get("label", "attack"),
                            target=foe_id, target_name=foe["name"], outcome=outcome, **blow)
        self._settle()
        return event

    def wound(self, target, amount, why, armor=True, double=False, kind=None, rng=None):
        """Harm to a foe that isn't a weapon blow: fire, a spell, a falling bookcase, one
        creature turned on another, or a power that ends it where it stands ("all").
        The GM rules that it happens; the dice (or the adventure's number) say how much."""
        if not (why or "").strip():
            raise SoloError("say what does the harm: --why \"the torch sets it alight\"")
        if slug(target) in ("hero", "pc", slug(self.state["pc"]["name"])):
            return self._hurt(amount, why, armor, double, rng)
        foe_id = self._foe(target)
        foe = self._fight()["foes"][foe_id]
        text = str(amount).strip().lower()
        if text == "all":
            rolled, dealt = None, foe["hp"]
        else:
            rolled = dice.roll(text, rng)
            dealt, resisted = combat.resisted(foe, slug(kind) if kind else None, max(0, rolled["total"] * (2 if double else 1) - (foe["armor"] if armor else 0)))
        hp = max(0, foe["hp"] - dealt)
        event = self.append("wound", target=foe_id, name=foe["name"], why=why.strip(), expr=None if rolled is None else text,
                            roll=rolled, armor=foe["armor"] if armor and rolled else 0, double=double or None,
                            dealt=dealt, hp=hp, hp_was=foe["hp"], down=hp == 0, kind=slug(kind) if kind else None,
                            resisted=None if rolled is None else resisted)
        self._settle()
        return event

    def _hurt(self, amount, why, armor, double, rng):
        """Harm to the hero that no foe's attack brings: a fall, a trap, a vent of steam.
        The dice are rolled here; the hero's armor helps unless the harm goes through it."""
        self._able("be hurt") if not self.state["pc"]["dying"] else None
        rolled = dice.roll(str(amount), rng)
        worn = combat.kit(self.system, self.state["pc"])["armor"] if armor else 0
        dealt = max(0, rolled["total"] * (2 if double else 1) - worn)
        track = (self.system.get("combat") or {}).get("track", "hp")
        payload = {"note": why.strip(), **({"pc": {track: f"-{dealt}"}} if dealt else {})}
        return self._record("harm", payload, rng, expr=str(amount), roll=rolled, armor=worn, dealt=dealt, by=why.strip())

    def defend(self, how, weapon=None, rng=None, use=()):
        """Answer an incoming hit: evade or parry (a roll that can't be pushed; it stops
        the hit on a success) or take it. A failed defence takes the hit."""
        incoming = self._fight()["incoming"]
        how = slug(how)
        if incoming is None:
            raise SoloError("nothing is coming at the hero right now")
        elif how == "take":
            return self.take(rng)
        elif how == "resist":
            # Something the adventure grants against a kind of attack (a WIL roll that nullifies a
            # demon's blow): a roll with the named stat, and the hit is gone on a success.
            if not weapon:
                raise SoloError("resist with what? defend resist --with wil")
            event = self.check(weapon, rng=rng, pushable=False, defend={"how": "resist", "weapon": None, "against": incoming["from"]})
            if not event["outcome"]["success"]:
                self.take(rng, cause=event["seq"])
            return event
        abilities = [self._held(name) for name in _listed(use)]
        # A shield wall parries the monster's blow that nothing else could.
        parryable = incoming.get("can_parry", True) or any(ability.get("unparryable") for _, ability in abilities)
        if how not in ("evade", "parry"):
            raise SoloError("defend with evade, parry, resist or take")
        elif not incoming.get("can_defend", True):
            raise SoloError(f"{incoming['label']} can't be dodged or parried: defend take")
        elif how == "parry" and not parryable:
            raise SoloError(f"{incoming['label']} can't be parried: defend evade, or take")
        if how == "evade":
            skill, arm = self.system["combat"].get("evade", "evade"), None
        else:
            arm = combat.weapon(self.system, self.state["pc"], weapon, "parry")
            skill = arm["skill"]
        for _, ability in abilities:
            if ability.get("boon") == "parry" and (how != "parry" or ability.get("weapon") not in arm["features"]):
                raise SoloError(f"{ability['name']} needs a parry with a {ability.get('weapon', 'weapon')}")
            elif not ability.get("boon") and ability.get("reaction") != ("parry" if how == "parry" else "dodge"):
                raise SoloError(f"{ability['name']} doesn't help with {how}")
        boons = 0
        for aid, ability in abilities:
            self._pay(aid, ability)
            boons += bool(ability.get("boon"))
        defence = {"how": how, "weapon": arm and arm["label"], "weapon_id": arm and arm["id"], "against": incoming["from"],
                   **({"needs_dragon": True} if incoming.get("critical") else {})}
        event = self.check(skill, boons, 0, rng, pushable=False, defend=defence)
        if not event["outcome"]["success"]:
            self.take(rng, cause=event["seq"])
        elif how == "parry":
            if arm["durability"] and incoming.get("kind") != "piercing":
                # The blow lands on the weapon: a blow worse than it can take breaks it, until it is repaired.
                rolled = dice.roll(incoming["damage"], rng)
                self.append("durability", weapon=arm["id"], label=arm["label"], how="parry", expr=incoming["damage"], roll=rolled,
                            damage=rolled["total"], durability=arm["durability"], broke=rolled["total"] > arm["durability"], cause=event["seq"])
            if (event["outcome"]["dragon"] and not incoming.get("critical") and not incoming.get("ranged") and not arm["ranged"]
                    and self.system["combat"].get("parry_dragon") == "counter" and not self.state["combat"]["foes"][incoming["from"]]["down"]):
                # A Dragon on a parry is a counterattack that can't be avoided.
                self._strike(event, rng, attack={"weapon": arm["id"], "label": arm["label"], "target": incoming["from"]}, choice="counter")
        return event

    def take(self, rng=None, cause=None):
        """The incoming hit lands: roll its damage, subtract the hero's armor."""
        incoming = self._fight()["incoming"]
        if incoming is None:
            raise SoloError("nothing is coming at the hero right now")
        track = self.system["combat"].get("track", "hp")
        armor = combat.kit(self.system, self.state["pc"])["armor"] if incoming.get("armor", True) else 0
        rolled = dice.roll(incoming["damage"], rng)
        dealt = max(0, rolled["total"] - armor)
        payload = {"note": f"hit by {incoming['name']} ({incoming['label']})"}
        if dealt:
            payload["pc"] = {track: f"-{dealt}"}
        harm = self._record("harm", payload, rng, expr=incoming["damage"], roll=rolled, armor=armor, dealt=dealt, cause=cause,
                            by=incoming["name"], source=incoming["from"])
        foe = (self.state["combat"] or {}).get("foes", {}).get(incoming["from"])
        if dealt and foe and foe.get("drain") and not foe["down"] and foe["hp"] < foe["max"]:
            self.append("heal", target=incoming["from"], name=foe["name"], roll=None, hp=min(foe["max"], foe["hp"] + dealt), hp_was=foe["hp"], by="drain")
        return harm

    def repair(self, weapon, rng=None, artisan=False):
        """Mend a weapon that broke or was damaged: a roll with the skill the pack names ([combat]
        repair: CRAFTING), or, for one an artisan sees to, no roll."""
        pc = self.state["pc"]
        arm = next((w for w in combat.weapons(self.system).values() if slug(weapon) in (w["id"], slug(w["label"]))), None)
        condition = pc.get("damaged", {}).get(arm["id"]) if arm else None
        skill = self.system.get("combat", {}).get("repair")
        if arm is None:
            raise SoloError(f"no weapon called {weapon!r}; weapons: {', '.join(pc.get('damaged', {})) or 'none need mending'}")
        elif not condition:
            raise SoloError(f"the {arm['label'].lower()} is whole")
        elif not artisan and not skill:
            raise SoloError(f"{self.system['name']} has no [combat] repair skill: an artisan mends it (solo repair {arm['id']} --artisan)")
        elif artisan:
            return self.append("repair", weapon=arm["id"], label=arm["label"], by="an artisan")
        event = self.check(skill, rng=rng, pushable=False, repair={"weapon": arm["id"]})
        return self.append("repair", weapon=arm["id"], label=arm["label"], by=event["label"], cause=event["seq"]) if event["outcome"]["success"] else event

    # Journeys -----------------------------------------------------------------------------
    #
    # Travel goes by the shift: so many kilometers on foot or mounted, two shifts a day (a third is a
    # forced march: the hero becomes Exhausted). Off a road the pathfinder rolls a skill each shift: a
    # Dragon doubles the ground covered, a failure is a mishap from the pack's table.

    def journey(self, km, mounted=False, road=False, difficult=False, use=(), rng=None):
        """Travel `km` kilometers, a shift at a time, until the hero arrives or something needs the GM. Leaving a road, the
        pathfinder (the hero) rolls each shift, with a bane for no map or hard going, a boon for a spyglass."""
        rules = self.system.get("journey")
        self._able("travel")
        if not rules:
            raise SoloError(f"{self.system['name']} has no [journey] rules: the GM reads the rules page and commits the time")
        elif self.state["combat"]:
            raise SoloError("no travelling in the middle of a fight")
        elif km <= 0:
            raise SoloError("how far? solo journey <kilometers>")
        shift, per_day = self.system["time"]["shift"], int(rules.get("shifts_per_day", 4))
        speed, left, walked = int(rules["mounted" if mounted else "foot"]), km, 0
        carried = {slug(i) for i in self.state["pc"]["items"]}
        boons, banes = int(any(i.startswith("spyglass") for i in carried)), int(not road) * int(not any(i.startswith("map") for i in carried)) + int(difficult)
        riders = [self._held(name) for name in _listed(use)]
        for _, ability in riders:
            if ability.get("boon") != "journey":
                raise SoloError(f"{ability['name']} doesn't help on a journey")
        while left > 0:
            today = self.state["travel"]["shifts"] if self.state["travel"]["day"] == self.state["time"] // (shift * per_day) else 0
            limit, pc = int(rules.get("travel_shifts", 2)), self.state["pc"]
            if today > limit or (today == limit and "exhausted" in pc["conditions"]):
                if walked:
                    break
                raise SoloError(f"{pc['name']} has walked as far as anyone does today: {today} shifts" + (" (Exhausted, no forced march)" if today == limit else ""))
            forced = today >= limit
            ground, roll, mishap = speed, None, None
            if not road:
                for aid, ability in riders:
                    self._pay(aid, ability)
                helped, riders = len(riders), []
                roll = self.check(rules.get("skill", "bushcraft"), boons + helped, banes, rng, pushable=False, journey={"left": left})
                if roll["outcome"]["success"]:
                    ground = speed * (2 if roll["outcome"].get("dragon") else 1)
                else:
                    mishap = self.table(rules["mishaps"], rng=rng, cause=roll["seq"]) if rules.get("mishaps") else None
                    effect = (mishap or {}).get("effect") or {}
                    ground = 0 if effect.get("distance") == "none" else speed // 2 if effect.get("distance") == "half" else speed
            changes = {"note": f"travels a shift, {min(ground, left)} of {left} kilometers", "time": {"shift": 1}}
            if forced:
                changes["pc"] = {"conditions": {"add": ["exhausted"]}}
            done = min(ground, left)
            self._record("journey", changes, rng, distance=done, left=left - done, day=self.state["time"] // (shift * per_day), shifts=today + 1,
                         forced=forced or None, cause=roll["seq"] if roll else None)
            left -= done
            walked += 1
            if mishap and (mishap.get("effect") or {}).get("gm"):
                break
        return self.events[-1] if walked else None

    def camp(self, use=(), rng=None):
        """Find a place to rest in the wild: a roll with the pack's journey skill, a bane without a sleeping fur, a boon with a
        tent. A success makes the shift a rest the hero can take (solo rest shift); a failure doesn't."""
        rules = (self.system.get("journey") or {}).get("camp")
        if not rules:
            raise SoloError(f"{self.system['name']} has no [journey] camp rules")
        carried = {slug(i) for i in self.state["pc"]["items"]}
        banes = int(not any(i.startswith(rules.get("needs", "sleeping_fur")) for i in carried))
        boons = int(any(i.startswith(rules.get("helps", "tent")) for i in carried))
        return self.check(rules.get("skill", "bushcraft"), boons, banes, rng, pushable=False, journey={"camp": True})

    # Magic --------------------------------------------------------------------------------
    #
    # A spell costs WP whatever comes of it; then the school is rolled. On a success it does
    # what its data says (damage, healing) and the GM the rest, from the rule page. A Dragon is the
    # player's choice, a Demon a mishap (the tables are the pack's).

    def cast(self, spell, power=1, targets=(), boons=0, banes=0, body=None, grimoire=False, school=None, defended=None, rng=None):
        """Cast a spell the hero knows, at a power level (1 to 3): pay its WP, then roll the school. `targets` are
        the foes a damage spell is for; `body` a die (d6) to draw power from the body when the hero has
        nearly none left: it gives that many WP to spend at once and costs as many HP; `grimoire` casts a
        spell that isn't prepared, which takes twice as long; `defended` is how a foe avoids it."""
        self._able("cast a spell")
        rules = self.system.get("magic")
        if not rules:
            raise SoloError(f"{self.system['name']} has no [magic] rules")
        self._no_choice_waiting()
        sid, spec = magic.find(self.system, spell)
        pc, name = self.state["pc"], spec.get("name", spell)
        trick = bool(spec.get("trick"))
        power = 1 if trick or not spec.get("power", True) else power
        track, hp_track = rules.get("track", "wp"), (self.system.get("combat") or {}).get("track", "hp")
        amount = magic.cost(self.system, spec, power)
        have, foes = pc["tracks"][track]["value"], []
        if slug(sid) not in {slug(k) for k in pc.get("spells", [])} and spec.get("name", sid) not in pc.get("spells", []):
            raise SoloError(f"{pc['name']} doesn't know {name}; spells: {', '.join(pc.get('spells', [])) or 'none'}")
        elif not trick and not self._prepared(sid, spec) and not grimoire:
            raise SoloError(f"{name} isn't prepared: cast it from the grimoire (--grimoire: it takes twice as long, and isn't for a reaction) or prepare it (solo prepare)")
        elif grimoire and spec.get("casting_time") == "reaction":
            raise SoloError(f"{name} is a reaction spell, which can't be cast from the grimoire")
        elif not 1 <= power <= int(rules.get("max_power", 3)):
            raise SoloError(f"a spell's power level is 1 to {rules.get('max_power', 3)}")
        elif defended and defended not in spec.get("avoid", []):
            raise SoloError(f"{name} can't be avoided that way" + (f" (it can be: {', '.join(spec['avoid'])})" if spec.get("avoid") else " (it can't be dodged or parried)"))
        elif body and (spec.get("heal") or have > int(rules.get("body_below", 1)) or body not in rules.get("body", [])):
            raise SoloError("power from the body is for a hero with " + f"{rules.get('body_below', 1)} {track.upper()} or none left, and not for healing; the die is one of {', '.join(rules.get('body', []))}")
        elif not body and have < amount:
            raise SoloError(f"{name} at power {power} costs {amount} {track.upper()}, and {pc['name']} has {have}" + (f" (power from the body: --body {rules['body'][1]})" if rules.get("body") and have <= int(rules.get("body_below", 1)) and not spec.get("heal") else ""))
        if spec.get("damage") and self.state["combat"]:
            foes = [self._foe(t) for t in _listed(targets)] if targets else [self._foe(None)]
        drawn = dice.roll(body, rng)["total"] if body else 0
        own = max(0, amount - drawn)
        if own > have:
            raise SoloError(f"the body gave {drawn}, and {name} at power {power} costs {amount}; {pc['name']} has {have} of their own, too little to add")
        carried = {slug(i) for i in pc["items"]}
        metal = sorted(k for k, g in self.system.get("gear", {}).items() if g.get("metal") and k in carried)
        payload = {"note": f"casts {name}", "pc": {**({track: f"-{own}"} if own else {}), **({hp_track: f"-{drawn}"} if drawn else {})}}
        paid = self._record("spell", payload, rng, spell=sid, name=name, power=power, cost=amount, body=drawn or None, metal=metal or None, grimoire=grimoire or None)
        if trick:
            return paid
        skill = magic.school(self.system, self.state["pc"], spec, school)
        event = self.check(skill, boons, banes, rng, cast={"spell": sid, "name": name, "power": power, "targets": foes, "cost": amount,
                                                          **({"defended": defended} if defended else {})})
        if event["outcome"]["success"]:
            self._spell_lands(event, rng)
        return event

    def _prepared(self, sid, spec):
        held = {slug(p) for p in self.state["pc"].get("prepared", [])}
        return sid in held or slug(spec.get("name", sid)) in held

    def _spell_lands(self, event, rng, choice=None):
        """The spell's roll succeeded: a Dragon waits for the player's choice; otherwise the damage or the healing
        the spell's data gives is done, its targets having the chance to avoid it if they can."""
        cast, outcome = event["cast"], event["outcome"]
        spec, rules = self.system["spells"][cast["spell"]], self.system["magic"]
        if choice is None and outcome.get("dragon") and rules.get("dragon"):
            self.append("choice", of=event["seq"], kind="spell", options=list(rules["dragon"]))
            return
        if choice == "free":
            self._record("spell_effect", {"note": "the Dragon pays for the spell", "pc": {rules.get("track", "wp"): f"+{cast['cost']}"}}, rng)
        double = choice == "double"
        if spec.get("damage"):
            dice_for = [spec["damage"], *spec.get("chain", [])]
            for foe_id, expr in zip(cast.get("targets", []), dice_for):
                if cast.get("defended") and self._foe_defends(foe_id, cast["defended"], outcome.get("dragon", False), event["seq"], rng):
                    continue
                self.wound(foe_id, magic.leveled(expr, spec.get("per_level"), cast["power"]), cast["name"], armor=spec.get("armor", True),
                           double=double, kind=spec.get("kind", "magic"), rng=rng)
        if spec.get("heal"):
            healed = dice.roll(magic.leveled(spec["heal"], spec.get("per_level"), cast["power"]), rng)["total"] * (2 if double else 1)
            hp_track = (self.system.get("combat") or {}).get("track", "hp")
            self._record("spell_effect", {"note": f"{cast['name']} heals", "pc": {hp_track: f"+{healed}"}}, rng, healed=healed)

    def prepare(self, spell, drop=None):
        """Hold a spell ready, in place of another when the hero is at the limit: as many as the base chance
        of the attribute the rules name (tricks are always ready). Studying takes a shift, the GM's to give."""
        sid, spec = magic.find(self.system, spell)
        pc, rules = self.state["pc"], self.system.get("magic")
        known = {slug(k) for k in pc.get("spells", [])}
        if not rules:
            raise SoloError(f"{self.system['name']} has no [magic] rules")
        elif sid not in known and slug(spec.get("name", sid)) not in known:
            raise SoloError(f"{pc['name']} doesn't know {spec.get('name', sid)}")
        elif spec.get("trick"):
            raise SoloError("a magic trick is always ready")
        elif self._prepared(sid, spec):
            raise SoloError(f"{spec.get('name', sid)} is already prepared")
        held = [p for p in pc.get("prepared", [])]
        limit = magic.limit(self.system, pc)
        out = None
        if len(held) >= limit:
            if not drop:
                raise SoloError(f"{pc['name']} can hold {limit} spells prepared: drop one (--drop <spell>): {', '.join(held)}")
            out = next((h for h in held if slug(h) in (slug(drop), slug(magic.find(self.system, drop)[1].get("name", drop)))), None)
            if out is None:
                raise SoloError(f"{drop!r} isn't prepared; prepared: {', '.join(held)}")
        payload = {"note": f"prepares {spec.get('name', sid)}", "pc": {"prepared": {"add": [spec.get("name", sid)], "remove": [out] if out else []}}}
        return self._record("prepare", payload, None, spell=sid, name=spec.get("name", sid), dropped=out)

    def learn(self, spell, source="teacher", rng=None):
        """Learn a spell, from a teacher or a grimoire. A trick needs neither a roll nor a mark. A spell takes a mark
        for its school, and a roll: the INT roll with a boon a teacher gives, or LANGUAGES from a grimoire."""
        sid, spec = magic.find(self.system, spell)
        pc, rules = self.state["pc"], self.system.get("magic")
        name, known = spec.get("name", sid), {slug(k) for k in self.state["pc"].get("spells", [])}
        if not rules:
            raise SoloError(f"{self.system['name']} has no [magic] rules")
        elif sid in known or slug(name) in known:
            raise SoloError(f"{pc['name']} already knows {name}")
        elif spec.get("trick"):
            return self._record("learn", {"note": f"learns {name}", "pc": {"spells": {"add": [name]}}, "time": dict(rules.get("trick_time", {"stretch": 1}))}, rng, spell=sid, name=name)
        elif source not in rules.get("learn", {}):
            raise SoloError(f"learn from one of: {', '.join(rules.get('learn', {})) or 'none'}")
        school, unmet = spec.get("school"), self._unmet_prerequisite(spec)
        used = magic.skill_of(self.system, school)
        if school in self.system["skills"] and not pc["skills"].get(used, {}).get("trained"):
            raise SoloError(f"{name} is of {school}, and {pc['name']} has no skill level in {'it' if used == school else used}")
        elif unmet:
            raise SoloError(f"{name} asks for {unmet} first")
        elif school in self.system["skills"] and used not in pc["marks"]:
            raise SoloError(f"learning {name} takes an advancement mark for {used}, and {pc['name']} has none (solo mark {used})")
        how = rules["learn"][source]
        event = self.check(how["roll"], int(how.get("boons", 0)), 0, rng, pushable=False, learn={"spell": sid, "source": source})
        payload = {"note": f"learns {name}", "pc": {"spells": {"add": [name]}}} if event["outcome"]["success"] else {"note": f"fails to learn {name}"}
        return self._record("learn", payload, rng, spell=sid, name=name, source=source, learned=bool(event["outcome"]["success"]),
                            mark=used if used in pc["marks"] else None, cause=event["seq"])

    def _unmet_prerequisite(self, spec):
        """What a spell asks for first that the hero lacks, in words: a school they are trained in or a spell they know. An entry
        that is a list is one of them ("PROTECTOR or DISPEL"); a school is asked before the spells."""
        pc = self.state["pc"]
        known = {slug(k) for k in pc.get("spells", [])}
        has = lambda need: bool(pc["skills"].get(magic.skill_of(self.system, need), {}).get("trained")) if need in self.system["skills"] else slug(need) in known
        lacking = [need if isinstance(need, list) else [need] for need in _listed(spec.get("prerequisite"))]
        lacking = [options for options in lacking if not any(has(option) for option in options)]
        first = next((options for options in lacking if options[0] in self.system["skills"]), None) or next(iter(lacking), None)
        return " or ".join(first) if first else None

    # Heroic abilities -----------------------------------------------------------------

    def use(self, ability, cost=None):
        """Pay for a heroic ability the hero has, and log it: for the ones the GM runs from the rule
        page. The ones the engine runs are asked for where they work: --use on an attack, a defence, a
        stretch rest or a new round."""
        aid, spec = self._held(ability)
        return self._pay(aid, spec, cost)

    def _held(self, name):
        """(id, spec) of a heroic ability the system knows and the hero has."""
        key, abilities, pc = slug(name), self.system.get("abilities", {}), self.state["pc"]
        found = next(((aid, spec) for aid, spec in abilities.items() if key in (aid, slug(spec.get("name", aid)))), None)
        held = {slug(a) for a in pc["abilities"]}
        if found is None:
            raise SoloError(f"no heroic ability {name!r} in {self.system['name']}'s rules the engine knows; they are: {', '.join(abilities) or 'none'}")
        elif found[0] not in held and slug(found[1].get("name", found[0])) not in held:
            raise SoloError(f"{pc['name']} doesn't have {found[1].get('name', found[0])}")
        return found

    def _paying(self, spec, cost=None):
        """What an ability costs: {track: amount}. A cost that "varies" is given when it is used."""
        pay = spec.get("pay", {})
        if pay == "varies":
            if not cost:
                raise SoloError(f"{spec.get('name')} costs what the hero chooses to spend: --cost <points>")
            return {spec.get("track", "wp"): int(cost)}
        return {track: int(amount) for track, amount in pay.items()}

    def _pay(self, aid, spec, cost=None):
        pc, amounts = self.state["pc"], self._paying(spec, cost)
        short = next((t for t, n in amounts.items() if pc["tracks"][t]["value"] < n), None)
        if short:
            raise SoloError(f"{spec.get('name', aid)} costs {', '.join(f'{n} {t.upper()}' for t, n in amounts.items())}, and {pc['name']} has {pc['tracks'][short]['value']}")
        changes = {"pc": {"tracks": {t: pc["tracks"][t]["value"] - n for t, n in amounts.items()}, "tracks_was": {t: pc["tracks"][t]["value"] for t in amounts}}} if amounts else {}
        return self.append("ability", ability=aid, name=spec.get("name", aid), cost=amounts or None, changes=changes)

    def _rider(self, name, arm, foe_id):
        """An ability an attack uses, checked before the roll: it adds damage, to the foes and weapons it is for."""
        aid, spec = self._held(name)
        profile = self._profile(self.state["combat"]["foes"][foe_id]["npc"])
        if not spec.get("extra_damage"):
            raise SoloError(f"{spec.get('name', aid)} doesn't add to an attack")
        elif spec.get("against") == "monster" and not profile.get("attacks"):
            raise SoloError(f"{spec['name']} is for monsters, and {self.state['combat']['foes'][foe_id]['name']} isn't one")
        elif spec.get("weapon") == "unarmed" and arm["id"] != "unarmed":
            raise SoloError(f"{spec['name']} is for an unarmed attack")
        elif spec.get("grip") and arm.get("grip") != spec["grip"]:
            raise SoloError(f"{spec['name']} needs a weapon held in {spec['grip']} hands")
        elif spec.get("melee") and arm["ranged"]:
            raise SoloError(f"{spec['name']} is for a melee weapon")
        pc, amounts = self.state["pc"], self._paying(spec)
        short = next((t for t, n in amounts.items() if pc["tracks"][t]["value"] < n), None)
        if short:  # a cost the hero can't meet is known before the roll, not after it
            raise SoloError(f"{spec['name']} costs {', '.join(f'{n} {t.upper()}' for t, n in amounts.items())}, and {pc['name']} has {pc['tracks'][short]['value']}")
        return aid

    # Dying ----------------------------------------------------------------------------

    def death_roll(self, rng=None):
        """At 0 HP the hero is dying and rolls each turn. Successes and failures count up
        to the pack's limits: enough successes and they rally, enough failures and they die.
        A Dragon counts as two successes, a Demon as two failures."""
        spec, pc = self.system.get("dying"), self.state["pc"]
        if not spec:
            raise SoloError(f"{self.system['name']} has no death rolls ([dying] in system.toml)")
        elif pc["dead"]:
            raise SoloError(f"{pc['name']} is dead")
        elif not pc["dying"]:
            raise SoloError(f"{pc['name']} isn't dying")
        elif self._this_round(lambda e: e["type"] in ("death_roll", "save_self")):
            raise SoloError(f"{pc['name']} has already made a death roll this round (or tried to save themselves); the next comes with solo fight --round")
        elif self._this_round(lambda e: e["type"] == "check" and e.get("attack")):
            # The death roll is the hero's turn: a hero struck down after attacking rolls next round.
            raise SoloError(f"{pc['name']} has already had their turn this round; the first death roll comes with solo fight --round")
        kind, key, label, attribute = self._stat(spec["roll"])
        auto = self._condition_banes(attribute)
        outcome = self._resolve(kind, key, attribute, 0, len(auto), rng)
        outcome["pushable"] = False
        successes = 2 if outcome.get("dragon") else int(outcome["success"])
        failures = 2 if outcome.get("demon") else int(not outcome["success"])
        payload, result = {}, None
        if pc["dying"]["successes"] + successes >= int(spec.get("rally", 3)):
            recovered = dice.roll(str(spec.get("recover", "1")), rng)["total"]
            payload = {"note": f"{pc['name']} rallies", "pc": {spec["track"]: f"+{recovered}"}}
            result = "rallies"
        elif pc["dying"]["failures"] + failures >= int(spec.get("die", 3)):
            result = "dies"
        return self._record(
            "death_roll", payload, rng, label=label, outcome=outcome, condition_banes=auto or None,
            successes=successes, failures=failures, result=result,
        )

    # A new hero -----------------------------------------------------------------------

    def take_over(self, character, name=None, seed=None):
        """The hero is dead but the story goes on: the player takes up another character
        where it stands (a written replacement like the dwarf in the trapdoor, a pre-made,
        or a new roll). The dead hero stays in the story's memory and the Hall of the Fallen.
        An NPC the adventure offered as the replacement leaves the cast: they are the hero now."""
        pc = self.state["pc"]
        if not pc["dead"]:
            raise SoloError(f"{pc['name']} is still alive; a new hero takes over only after a death")
        sheet = character_sheet(creation.character(self.system, character, name=name, seed=seed, adventure=self.adventure), self.system)
        npc = slug(character) if slug(character) in self.state["npcs"] else None
        return self.append("hero", pc=sheet, npc=npc)

    def rally(self, rng=None):
        """Alone at zero HP, the hero rallies themselves (the solo rules, p. 5): a roll with no
        bane, and on a success they may act again, still making death rolls each round."""
        spec, pc = (self.system.get("dying") or {}).get("self_rally"), self.state["pc"]
        if not spec:
            raise SoloError(f"{self.system['name']} has no self_rally under [dying]")
        elif not pc["dying"]:
            raise SoloError(f"{pc['name']} isn't dying")
        elif pc["dying"].get("rallied"):
            raise SoloError(f"{pc['name']} has already rallied")
        kind, key, label, attribute = self._stat(spec["skill"])
        outcome = self._resolve(kind, key, attribute, 0, len(self._condition_banes(attribute)), rng)
        outcome["pushable"] = False
        return self.append("rally", label=label, outcome=outcome, rallied=bool(outcome["success"]))

    def save_self(self, rng=None):
        """Alone at zero HP, the hero tries to save their own life (p. 5): a HEALING roll that
        stops the dying and brings a little HP back on a success. It is their turn."""
        spec, pc = (self.system.get("dying") or {}).get("self_save"), self.state["pc"]
        if not spec:
            raise SoloError(f"{self.system['name']} has no self_save under [dying]")
        elif not pc["dying"]:
            raise SoloError(f"{pc['name']} isn't dying")
        elif self._this_round(lambda e: e["type"] in ("death_roll", "save_self")):
            raise SoloError(f"{pc['name']} has already had their turn this round; the next comes with solo fight --round")
        kind, key, label, attribute = self._stat(spec["skill"])
        outcome = self._resolve(kind, key, attribute, 0, len(self._condition_banes(attribute)), rng)
        outcome["pushable"] = False
        payload = {}
        if outcome["success"]:
            # What the rulebook gives back when another saves a life, unless the solo rules say otherwise.
            recovered = dice.roll(str(spec.get("recover") or self.system["dying"].get("recover", "1")), rng)["total"]
            payload = {"note": f"{pc['name']} saves their own life", "pc": {self.system["dying"]["track"]: f"+{recovered}"}}
        return self._record("save_self", payload, rng, label=label, outcome=outcome, saved=bool(outcome["success"]))

    # Advancement ------------------------------------------------------------------------

    def mark(self, skill, reason=None):
        """Mark a skill for advancement (the end-of-session questions award these; Dragons
        and Demons on skill rolls mark them by themselves)."""
        if not self.system.get("advancement"):
            raise SoloError(f"{self.system['name']} has no [advancement] section")
        elif self.state["pc"]["dead"]:
            raise SoloError(f"{self.state['pc']['name']} is dead, so there is nothing left to learn")
        kind, key, label, _ = self._stat(skill)
        if kind != "skill":
            raise SoloError(f"only skills are marked, and {label} is an attribute")
        elif key not in self.state["pc"]["skills"]:
            raise SoloError(f"{label} can't be learned by marking it")
        elif key in self.state["pc"]["marks"]:
            raise SoloError(f"{label} is already marked")
        else:
            return self.append("mark", skill=key, label=label, reason=reason)

    def advance(self, rng=None):
        """Roll for every marked skill: above its value, it goes up one (to the pack's max).
        Every mark is used up either way."""
        spec, pc = self.system.get("advancement"), self.state["pc"]
        if not spec:
            raise SoloError(f"{self.system['name']} has no [advancement] section")
        elif pc["dead"]:
            raise SoloError(f"{pc['name']} is dead, so there is nothing left to learn")
        elif not pc["marks"]:
            raise SoloError("no skills are marked")
        results = []
        for key in pc["marks"]:
            skill = pc["skills"][key]
            total = dice.roll(spec.get("roll", "1d20"), rng)["total"]
            improves = total > skill["value"] and skill["value"] < int(spec.get("max", 18))
            results.append({"skill": key, "name": skill["name"], "roll": total, "was": skill["value"], "now": skill["value"] + improves})
        return self.append("advance", results=results)

    # Cutting a message -------------------------------------------------------------------

    def strike(self, note=None):
        """The player cuts the GM's last message (an X-card). The log stays append-only, so this is an event: the Book and
        `solo recall` leave the message out, and the GM is told it was cut and what it had committed in that turn (a cut
        doesn't undo those: the GM retracts them in the story if it has to)."""
        last = next((e for e in reversed(self.events) if e["type"] == "said" and e["by"] == "gm" and e["seq"] not in self.state["struck"]), None)
        if last is None:
            raise SoloError("the GM hasn't said anything to cut")
        began = max((e["seq"] for e in self.events if e["type"] == "said" and e["seq"] < last["seq"]), default=0)
        turn = [f"#{e['seq']} {gm_line(e)}" for e in self.events if began < e["seq"] < last["seq"] and e["type"] in ("commit", "threat", "move")]
        return self.append("struck", target=last["seq"], committed=turn or None, note=(note or "").strip() or None)

    # Table settings ---------------------------------------------------------------------

    def set_prefs(self, tone=None, lines=None, veils=None, clear=False):
        """The player's table settings: the tone they want, lines (never in the story) and
        veils (happen off screen). The GM reads them at the start of every session."""
        now = {"tone": "", "lines": [], "veils": []} if clear else copy.deepcopy(self.state["prefs"])
        if tone is not None:
            now["tone"] = tone.strip()
        now["lines"] += [t.strip() for t in lines or [] if t.strip() and t.strip() not in now["lines"]]
        now["veils"] += [t.strip() for t in veils or [] if t.strip() and t.strip() not in now["veils"]]
        return self.append("prefs", **now)

    # Internals ----------------------------------------------------------------------

    def _able(self, action):
        pc = self.state["pc"]
        if pc["dead"]:
            raise SoloError(f"{pc['name']} is dead, so there is nothing left to {action}")
        elif pc["dying"] and not pc["dying"].get("rallied"):
            raise SoloError(f"{pc['name']} is dying and can't {action}: make a death roll (solo death-roll), rally (solo rally), or be healed")

    def _condition_banes(self, attribute):
        return [c for c in self.state["pc"]["conditions"] if self.system["conditions"].get(c) == attribute]

    def _gear_banes(self, skill, extra):
        """What the hero carries that puts a bane on this roll, each as a word for the log: worn armor
        on the skills it hampers (and a helmet on ranged attacks), a weapon the hero lacks the STR for or
        that is damaged, a shot from too near or too far. A weapon they can't use at all, or can't reach
        with, refuses the roll."""
        pc, attack, defend = self.state["pc"], extra.get("attack"), extra.get("defend")
        arm = combat.weapons(self.system).get((attack or {}).get("weapon") or (defend or {}).get("weapon_id") or "")
        found = combat.armor_banes(self.system, pc, skill, ranged=bool(attack and arm and arm["ranged"]))
        if arm:
            weak, helpless = combat.strength_needed(self.system, pc, arm)
            condition = pc.get("damaged", {}).get(arm["id"])
            blow = combat.reach(self.system, pc, arm, attack["distance"]) if attack and attack.get("distance") is not None else None
            if helpless:
                raise SoloError(f"{pc['name']} is too weak for the {arm['label'].lower()}: it needs STR {arm['str']}")
            elif condition == "broken":
                raise SoloError(f"the {arm['label'].lower()} is broken: mend it first (solo repair {arm['id']})")
            elif blow and blow[0] == "out":
                raise SoloError(blow[1])
            if weak:
                found.append(f"STR {arm['str']} needed")
            if condition == "damaged":
                found.append(f"{arm['label'].lower()} damaged")
            if blow:
                found.append(blow[1])
        return found

    def _resolve(self, kind, key, attribute, boons, banes, rng):
        family = self.system["family"]
        if family == "d20-under":
            return mechanics.d20_under(self._target(kind, key, attribute), boons, banes, rng)
        elif family == "d6-pool":
            return mechanics.d6_pool(self._pool(kind, key, attribute, boons - banes), self.system.get("success", 6), rng)
        elif family == "action-roll":
            raise SoloError(f"{self.system['name']} rolls moves, not skills: solo act <move> --stat <stat> (solo rule moves)")
        else:
            raise SoloError(f"unknown mechanics family {family!r}")

    def _tables(self):
        return {**self.system["tables"], **self.adventure["tables"]}

    def _roll_table(self, table_id, rng):
        tables = self._tables()
        key = table_id if table_id in tables else slug(table_id)
        if key not in tables:
            close = [t for t in tables if key and key in t] or get_close_matches(key, list(tables), n=3)
            hint = f"; did you mean {', '.join(close)}?" if close else ""
            raise SoloError(f"no table {table_id!r}{hint}; tables: {', '.join(sorted(tables)) or 'none'}")
        table = tables[key]
        rolled = dice.roll(self._substitute(table["formula"]), rng)
        hit = next((r for r in table.get("results", []) if r["range"][0] <= rolled["total"] <= r["range"][1]), None)
        return key, table, rolled, hit

    def _random_event(self, rng):
        return oracle.random_event(self.state, self._tables(), rng)

    def _fight(self):
        if self.state["combat"] is None:
            raise SoloError("there is no fight on: start one with solo fight <npc> ...")
        return self.state["combat"]

    def to_act(self):
        """Who hasn't acted yet this round, in initiative order: the hero until they attack
        (or roll against death), each standing foe until it attacks. Anything else the hero
        does in their turn the engine can't see, so it only ever says who may still be owed one."""
        fight = self.state["combat"]
        if fight is None:
            return []
        acted = Counter()
        for event in reversed(self.events):
            if event["type"] in ("fight", "round"):
                break
            elif event["type"] in ("enemy", "defence") and not event.get("queued"):
                acted[event["foe"]] += 1
            elif event["type"] == "death_roll" or (event["type"] == "check" and event.get("attack") and not event["attack"].get("free")):
                acted["pc"] += 1
        # Each card is a turn: a monster with ferocity 2, or a hero with Army of One, holds two.
        standing = {"pc", *(fid for fid, foe in fight["foes"].items() if not foe["down"])}
        waiting = []
        for f in fight["order"]:
            if f["id"] not in standing:
                continue
            elif acted[f["id"]]:
                acted[f["id"]] -= 1
            else:
                waiting.append(f["name"])
        return waiting

    def _count_this_round(self, test):
        count = 0
        for event in reversed(self.events) if self.state["combat"] else []:
            if event["type"] in ("fight", "round"):
                break
            count += bool(test(event))
        return count

    def _this_round(self, test):
        """Whether an event of this round of the fight passes `test`. The hero acts once a
        round: without this, a button clicked again would attack (or roll against death)
        as often as the player likes. Outside a fight there are no rounds to count."""
        if self.state["combat"] is None:
            return False
        for event in reversed(self.events):
            if event["type"] in ("fight", "round"):
                return False
            elif test(event):
                return True
        return False

    def _profile(self, npc_id):
        """An NPC as it fights: the adventure's profile, with a template and a role set in play
        (the solo rules' simple NPCs: a minion or a boss; an attacker: melee, ranged, sneaky, magic)."""
        profile = copy.deepcopy(profile_of(self.adventure, self.state, npc_id))
        live = self.state["npcs"].get(npc_id, {})
        profile.update({k: live[k] for k in ("template", "attacker") if live.get(k)})
        template = self.system.get("npcs", {}).get("templates", {}).get(profile.get("template") or "")
        if template:
            profile["stats"] = {"hp": template["hp"], "armor": template.get("armor", 0), **profile.get("stats", {})}
            profile.setdefault("attack", {"label": "attack", "value": template["skill"], "damage": template["damage"]})
        return profile

    def _foe(self, name):
        """A standing foe by id or name; with none given, the only one left standing."""
        foes = self._fight()["foes"]
        standing = [fid for fid, f in foes.items() if not f["down"]]
        if name is None:
            if len(standing) == 1:
                return standing[0]
            raise SoloError(f"which foe? {', '.join(standing) or 'none are standing'}")
        key = slug(name)
        found = key if key in foes else next((fid for fid, f in foes.items() if slug(f["name"]) == key), None)
        if found is None:
            raise SoloError(f"no foe {name!r} in this fight; foes: {', '.join(foes)}")
        elif foes[found]["down"]:
            raise SoloError(f"{foes[found]['name']} is already down")
        return found

    def _roster(self, names, present):
        """Foes by NPC id, with their stats from the adventure. Repeating an id brings
        several of that kind: cultist, cultist_2 ..."""
        roster = {}
        for name in names:
            npc_id = slug(name)
            npc, profile = self.state["npcs"].get(npc_id), self._profile(npc_id)
            stats = profile.get("stats", {})
            if npc is None:
                raise SoloError(f"unknown npc {name!r}; npcs: {', '.join(self.state['npcs']) or 'none'}")
            elif npc["fate"] != "alive" and not profile.get("many"):
                # A kind of foe (cultists, skeletons) is never used up: every fight brings new ones.
                raise SoloError(f"{npc['name']} is {npc['fate']}")
            elif "hp" not in stats:
                raise SoloError(f"{npc_id} has no stats.hp in the adventure pack, so it can't be fought here: narrate it, or give it stats")
            count = sum(1 for foe in [*present.values(), *roster.values()] if foe["npc"] == npc_id)
            foe_id, number = npc_id, count + 1
            if count or foe_id in present or foe_id in roster:
                # A second cultist is cultist_2, unless that is someone else's id: an adventure's own
                # cultist_2, or a foe already in the fight. Two foes with one id would be one foe.
                foe_id = f"{npc_id}_{number}"
                while foe_id in self.state["npcs"] or foe_id in present or foe_id in roster:
                    number += 1
                    foe_id = f"{npc_id}_{number}"
            roster[foe_id] = {
                "npc": npc_id, "name": npc["name"] + (f" {number}" if foe_id != npc_id else ""),
                "hp": int(stats["hp"]), "max": int(stats["hp"]), "armor": int(stats.get("armor", 0)), "down": False,
            }
            # A monster with ferocity 2 acts twice a round; an immune one shrugs off weapons.
            if int(stats.get("ferocity", 1)) > 1:
                roster[foe_id]["ferocity"] = int(stats["ferocity"])
            if stats.get("immune"):
                roster[foe_id]["immune"] = stats["immune"] if isinstance(stats["immune"], str) else "weapons"
            # Resisting (half damage of a kind, rounded up), being immune to a kind, healing each turn, and healing by harm done.
            for key in ("resist", "immune_to"):
                if stats.get(key):
                    roster[foe_id][key] = [stats[key]] if isinstance(stats[key], str) else list(stats[key])
            if stats.get("regenerate"):
                roster[foe_id]["regenerate"] = str(stats["regenerate"])
            if stats.get("drain"):
                roster[foe_id]["drain"] = True

        return roster

    def _cards(self, fighter_id, foe=None):
        """Initiative cards a fighter draws: a monster's ferocity; the hero's Army of One, two."""
        if fighter_id == "pc":
            return int((self._ability("initiative") or {}).get("initiative", 1))
        return int(foe.get("ferocity", 1))

    def _ability(self, key):
        """The system's heroic ability that does `key` (initiative, push), if the hero has it."""
        held = {slug(a) for a in self.state["pc"]["abilities"]}
        return next((spec for aid, spec in self.system.get("abilities", {}).items()
                     if key in spec and (aid in held or slug(spec.get("name", "")) in held)), None)

    def _initiative(self, foes, rng, use=()):
        """Deal the round. The hero's abilities change it: one draws two cards and keeps the better
        (initiative_pick), one keeps last round's card (initiative_keep); each is paid for."""
        fighters = [("pc", self.state["pc"]["name"])] * self._cards("pc")
        fighters += [(fid, f["name"]) for fid, f in foes.items() if not f["down"] for _ in range(self._cards(fid, f))]
        total, picked, kept = int(self.system["combat"].get("initiative", 10)), False, False
        for name in _listed(use):
            aid, ability = self._held(name)
            if not (ability.get("initiative_pick") or ability.get("initiative_keep")):
                raise SoloError(f"{ability['name']} doesn't change the initiative")
            self._pay(aid, ability)
            picked, kept = picked or bool(ability.get("initiative_pick")), kept or bool(ability.get("initiative_keep"))
        last = next((f["card"] for f in (self.state["combat"] or {}).get("order", []) if f["id"] == "pc"), None)
        if kept and last:
            cards = [last, *combat.deal(total, len(fighters) - 1 + picked, rng, reserved=[last])]
        else:
            cards = combat.deal(total, len(fighters) + picked, rng)
        if picked:
            spare = cards.pop()
            cards[0] = min(cards[0], spare)
        return sorted(({"id": fid, "name": name, "card": card} for (fid, name), card in zip(fighters, cards)), key=lambda f: f["card"])

    def _strike(self, event, rng, attack=None, choice=None):
        """Damage from an attack that hit: weapon dice (twice on a critical hit, as the pack says:
        always, or when the player chooses it) plus the damage bonus, minus the target's armor, unless
        the player chose a blow that goes through it. `attack` is the hero's blow when the event isn't
        the attack's own (a parry's counterattack, which a Dragon doesn't double)."""
        attack = attack or event["attack"]
        arm = combat.weapons(self.system)[attack["weapon"]]
        foe = self.state["combat"]["foes"][attack["target"]]
        rule = self.system["combat"].get("dragon")
        critical = event["outcome"].get("dragon", False) and choice != "counter"
        double = critical and (rule == "double" or (rule == "choice" and choice in (None, "double")))
        armor = 0 if choice == "pierce" else foe["armor"]
        bonus = combat.damage_bonus(self.system, self.state["pc"], arm["bonus"])
        expr = combat.damage_expression(arm["damage"], bonus, double, "double")
        expr += "".join(f"+{self.system['abilities'][aid]['extra_damage']}" for aid in attack.get("use", []))
        rolled = dice.roll(expr, rng)
        kind = attack.get("kind") or next(iter(combat.damage_types(arm)), None)
        dealt, resisted = combat.resisted(foe, kind, 0 if foe.get("immune") else max(0, rolled["total"] - armor))
        hp = max(0, foe["hp"] - dealt)
        damage = self.append(
            "damage", of=event["seq"], target=attack["target"], name=foe["name"], weapon=arm["label"],
            expr=expr, roll=rolled, armor=armor, dealt=dealt, hp=hp, hp_was=foe["hp"], down=hp == 0,
            immune=foe.get("immune"), kind=kind, resisted=resisted, **({"how": choice} if choice in ("pierce", "counter") else {}),
        )
        if dealt == 0 and armor and not foe.get("immune") and arm["durability"] and not arm["ranged"]:
            # A melee blow the armor stops entirely is suffered by the weapon, which may break.
            self.append("durability", weapon=arm["id"], label=arm["label"], how="armor", expr=expr, roll=rolled,
                        damage=rolled["total"], durability=arm["durability"], broke=rolled["total"] > arm["durability"], cause=damage["seq"])
        self._settle()
        return damage

    def _settle(self):
        """A fight whose last foe is down, or whose hero is dead, is over: close it, so the
        hero can rest, the GM isn't asked to deal another round against nobody, and a hero
        who takes up the story doesn't walk into the blow that killed the last one."""
        fight = self.state["combat"]
        if fight and (all(foe["down"] for foe in fight["foes"].values()) or self.state["pc"]["dead"]):
            standing = [foe["name"] for foe in fight["foes"].values() if not foe["down"]]
            self.append("fight_end", rounds=fight["round"], standing=standing)

    def _record(self, kind, payload, rng=None, **extra):
        """Validate a commit-shaped payload, log it, move the clocks it names, and follow
        the triggers it sets off (facts, fates, promises, time passing)."""
        changes, clock_moves, warnings = self._normalize(payload)
        before = self.state["time"]
        event = self.append(kind, changes=changes, warnings=warnings or None, **extra)
        filled = Counter()
        for clock_id, delta in clock_moves:
            for _ in range(abs(delta)):
                # A clock the commit fills fires clock:<id>:full like one filled by its triggers.
                filled.update(self._tick(clock_id, 1 if delta > 0 else -1, event["seq"], rng))
        self._follow(self._commit_triggers(changes, before) + filled, event["seq"], rng)
        if changes.get("time"):
            self._burn(event["seq"])
        self._settle()
        return event

    def _stat(self, name):
        """(kind, key, label, attribute) for a skill or attribute as the player typed it."""
        key = slug(name)
        attributes = self.system["attributes"]
        by_label = {slug(label): k for k, label in attributes.items()}
        skills = {**self.system["skills"], **self.state["pc"]["skills"]}
        if key in attributes or key in by_label:
            attribute = key if key in attributes else by_label[key]
            return "attribute", attribute, attributes[attribute], attribute
        elif key in skills:
            return "skill", key, skills[key]["name"], skills[key]["attribute"]
        else:
            close = get_close_matches(key, [*skills, *attributes], n=3, cutoff=0.75)
            hint = (f"; did you mean {', '.join(close)}?" if close
                    else f"; {self.system['name']} has: {', '.join([*attributes, *sorted(skills)])}")
            raise SoloError(f"no skill or attribute called {name!r}{hint}")

    def _target(self, kind, key, attribute):
        pc = self.state["pc"]
        key = self.system["skills"].get(key, {}).get("uses", key) if kind == "skill" else key
        if kind == "attribute":
            return pc["attributes"][attribute]
        elif key in pc["skills"]:
            return pc["skills"][key]["value"]
        elif self.system["skills"].get(key, {}).get("untrained", True):
            return packs.base_chance(self.system, pc["attributes"].get(attribute, 0))
        else:
            raise SoloError(f"{self.system['skills'][key]['name']} can't be used without training")

    def _pool(self, kind, key, attribute, modifier):
        """Dice groups for a d6-pool check. Boons add dice to the last pool group, banes
        remove dice from the last groups first; extra groups (stress) are never reduced."""
        pc = self.state["pc"]
        pool = []
        for name, spec in self.system.get("pool", {"base": "attribute", "skill": "skill"}).items():
            source, mode = (spec, "count") if isinstance(spec, str) else (spec["source"], spec.get("mode", "count"))
            if source == "attribute":
                value = pc["attributes"].get(attribute, 0)
            elif source == "skill":
                value = pc["skills"].get(key, {}).get("value", 0) if kind == "skill" else 0
            else:
                value = pc["tracks"].get(source, {}).get("value", 0)
            if mode == "step":
                pool.append({"name": name, "count": 1 if value >= 2 else 0, "sides": max(value, 2), "on_one": None})
            else:
                pool.append({"name": name, "count": value, "sides": 6, "on_one": None})
        if modifier > 0 and pool:
            pool[-1]["count"] += modifier
        remaining = max(0, -modifier)
        for group in reversed(pool):
            taken = min(group["count"], remaining)
            group["count"] -= taken
            remaining -= taken
        extra = []
        for name, spec in self.system.get("extra_dice", {}).items():
            count = spec.get("count", 0)
            value = pc["tracks"].get(count, {}).get("value", 0) if isinstance(count, str) else int(count)
            extra.append({"name": name, "count": value, "sides": int(spec.get("sides", 6)), "on_one": spec.get("on_one")})
        return pool + extra

    def _after_roll(self, event, rng):
        """Dragons, Demons and pool triggers (panic) roll their tables and move clocks.
        Outside a fight, a Dragon or a Demon also rolls the system's effect for it."""
        outcome = event["outcome"]
        triggers = [f"check:{name}" for name in ("dragon", "demon") if outcome.get(name)]
        effects = self.system.get("effects", {})
        if not self.state["combat"] and not event.get("attack") and not event.get("defend") and not event.get("quiet") and not event.get("cast") and not event.get("journey"):
            for name in ("dragon", "demon"):
                if outcome.get(name) and effects.get(name):
                    self.table(effects[name], rng=rng, cause=event["seq"])
        self._mishap(event, rng)
        for name in outcome.get("triggers", []):
            triggers.append(f"check:{name}")
            table = self.system.get("triggers", {}).get(name, {}).get("table")
            if table:
                self.table(table, rng=rng, cause=event["seq"])
        self._follow(triggers, event["seq"], rng)

    def _spell_mishap(self, event, rng):
        """A Demon on a spell: the pack's magical mishap table is rolled ([magic] mishap), and what it says the
        engine can do it does: a condition (effect `condition`), harm per power level (`hurt`), WP lost per
        power level (`drain`). The rest is the GM's."""
        cast, table = event["cast"], (self.system.get("magic") or {}).get("mishap")
        if not table:
            return
        effect = self.table(table, rng=rng, cause=event["seq"]).get("effect") or {}
        if effect.get("condition"):
            held = self.state["pc"]["conditions"]
            free = [c for c in self.system["conditions"] if c not in held]
            chosen = effect["condition"] if effect["condition"] not in held else next(iter(free), None)
            if chosen:
                self._record("spell_effect", {"note": f"the mishap leaves {self.state['pc']['name']} {chosen}", "pc": {"conditions": {"add": [chosen]}}}, rng)
        if effect.get("hurt"):
            self._hurt(f"{cast['power']}{effect['hurt'].lstrip('1')}" if effect.get("per_level") else effect["hurt"], "a magical mishap", False, False, rng)
        if effect.get("drain"):
            lost = dice.roll(f"{cast['power']}{effect['drain'].lstrip('1')}" if effect.get("per_level") else effect["drain"], rng)["total"]
            self._record("spell_effect", {"note": "the mishap drains willpower", "pc": {self.system["magic"].get("track", "wp"): f"-{lost}"}}, rng)

    def _mishap(self, event, rng):
        """A Demon on an attack is a miss, and the pack may add a mishap ([combat] demon = { melee = "<table>",
        ranged = "<table>" }): the table is rolled, and what it says the engine can run it runs: the weapon
        damaged (a bane on every use until it is repaired: `weapon = "damaged"` on the result), the hero
        hitting themselves (`hurt = "self"`: the weapon's dice, no damage bonus). The rest is the GM's."""
        if event.get("cast") and event["outcome"].get("demon"):
            return self._spell_mishap(event, rng)
        attack, tables = event.get("attack"), self.system.get("combat", {}).get("demon") or {}
        if not (attack and event["outcome"].get("demon") and tables):
            return
        arm = combat.weapons(self.system)[attack["weapon"]]
        table = tables.get("ranged" if arm["ranged"] else "melee")
        if table:
            effect = self.table(table, rng=rng, cause=event["seq"]).get("effect") or {}
            if effect.get("weapon") == "damaged":
                self.append("durability", weapon=arm["id"], label=arm["label"], how="mishap", damaged=True, broke=False, cause=event["seq"])
            if effect.get("hurt") == "self":
                self._hurt(arm["damage"], f"a blunder with the {arm['label'].lower()}", True, False, rng)

    def _odds_for(self, npc_id):
        return _ODDS[self._odds_step(npc_id)]

    def _odds_step(self, npc_id):
        """An NPC's attitude sets the odds, as a step from 0 (least likely) to 4; a kept or
        open promise raises them a step, a broken one lowers them."""
        step = self.state["npcs"][npc_id]["attitude"] + 2
        for promise in self.state["promises"].values():
            if promise["npc"] == npc_id:
                step += -1 if promise["status"] == "broken" else 1
        return _clamp(step, 0, len(_ODDS) - 1)

    def _substitute(self, expr):
        tracks = (self.state["pc"] or {}).get("tracks", {})
        unknown = [name for name in re.findall(r"@(\w+)", expr) if name not in tracks]
        if unknown:
            raise SoloError(f"unknown track @{unknown[0]} in {expr!r}")
        else:
            return re.sub(r"@(\w+)", lambda m: str(tracks[m.group(1)]["value"]), expr)

    def _follow(self, triggers, cause, rng=None):
        """Advance every clock listening to these triggers. A clock that fills up fires
        clock:<id>:full, which other clocks may listen to in turn."""
        pending = Counter(triggers)
        rounds = 0
        while pending and rounds < 10:
            fired = Counter()
            # Which clocks run is settled before this batch: time that passed before a clock
            # started (the stretch whose stage set the tower sinking) doesn't count on it.
            specs = self._clock_specs()
            running = {cid for cid, spec in specs.items()
                       if not spec.get("while") or packs.evaluate(spec["while"], self.state)}
            for clock_id, spec in specs.items():
                clock = self.state["clocks"][clock_id]
                if not clock["stopped"] and any(pending[t] for t in spec.get("stop", [])):
                    # What the clock counted down to can't happen any more (the priest is dead).
                    self.append("clock", clock=clock_id, label=clock["label"], value=clock["value"],
                                segments=clock["segments"], full=clock["full"], stopped=True, cause=cause)
                if clock["stopped"]:
                    continue
                elif clock_id not in running:
                    # Not running yet (or any more): the sinking only counts rounds once it has begun.
                    continue
                times = sum(pending[t] for t in spec.get("advance", []))
                for _ in range(min(times, int(spec.get("segments", 1)))):
                    fired.update(self._tick(clock_id, 1, cause, rng))
            pending = fired
            rounds += 1

    def _clock_specs(self):
        """The adventure's clocks and the threats set in play, each with what advances it.
        A threat looms where the danger is: in a scene the adventure marks safe (the chapel,
        the village) time passes without bringing it closer. It waits for the hero's return."""
        threats = self.system.get("threats", {})
        safe = self.adventure["scenes"].get(self.state["scene"], {}).get("safe", False)
        live = {cid: {"advance": [] if safe else threats.get("advance", []), "segments": clock["segments"]}
                for cid, clock in self.state["clocks"].items() if clock.get("threat") and not clock["stopped"]}
        return {**self.adventure["clocks"], **live}

    def _clock_spec(self, clock_id):
        return self._clock_specs().get(clock_id) or self.adventure["clocks"].get(clock_id, {})

    def _tick(self, clock_id, delta, cause, rng=None):
        clock, spec = self.state["clocks"][clock_id], self._clock_spec(clock_id)
        value = _clamp(clock["value"] + delta, 0, clock["segments"])
        if value == clock["value"] or clock["stopped"]:
            return []
        else:
            was_full = clock["full"]
            full = value >= clock["segments"]
            event = self.append(
                "clock", clock=clock_id, label=clock["label"], value=value,
                segments=clock["segments"], full=full, cause=cause,
            )
            if delta > 0 and spec.get("on_tick"):
                self.table(spec["on_tick"], rng=rng, cause=event["seq"])
            if delta > 0:
                for stage in spec.get("stages", []):
                    if stage.get("at") == value:
                        self._stage(clock_id, stage, event["seq"], rng)
            if full and clock.get("threat"):
                self._threat_comes(clock_id, event["seq"])
            return [f"clock:{clock_id}:full"] if full and not was_full else []

    # Threats -------------------------------------------------------------------------
    #
    # The solo rules' looming dangers: a D6 counter from 1 that advances on delays, failures
    # and time spent (a stretch or more). At 6 it comes to pass. A threat inherent to the
    # mission resets to 1; any other is gone once it has happened.

    def threat(self, text=None, threat_id=None, recurring=False, rng=None, label=None):
        spec = self.system.get("threats")
        if not spec:
            raise SoloError(f"{self.system['name']} has no [threats] in its system pack")
        if not text:
            text = self._roll_table(spec["table"], rng)[3].get("text", "") if spec.get("table") else ""
        text = (text or "").strip()
        if not text:
            raise SoloError("a threat needs what happens when it triggers")
        key = slug(threat_id or " ".join(text.split()[:4]))
        if key in self.state["clocks"] and not self.state["clocks"][key]["stopped"]:
            raise SoloError(f"there is already a threat {key}")
        # The table shows the label ("Goblin scouts"); the text is what happens when it triggers.
        short = (label or "").strip() or key.replace("_", " ").capitalize()
        return self.append("threat", action="add", clock=key, label=short, text=text, recurring=recurring,
                           value=int(spec.get("start", 1)), segments=int(spec.get("segments", 6)))

    def advance_threat(self, threat_id=None, by=1, rng=None):
        """A delay, or an opening the hero gave it: the threat draws closer."""
        key = self._looming(threat_id)
        return self._record("commit", {"note": "the threat draws closer", "clock": {key: f"+{int(by)}"}}, rng)

    def end_threat(self, threat_id=None):
        key = self._looming(threat_id)
        return self.append("threat", action="end", clock=key, label=self.state["clocks"][key]["label"])

    def _looming(self, threat_id):
        """A threat still looming, by id; with none given, the only one. Only threats: an
        adventure's clocks (hidden ones too) move by their own triggers or by a commit."""
        live = [cid for cid, c in self.state["clocks"].items() if c.get("threat") and not c["stopped"]]
        key = slug(threat_id or "")
        if key in live:
            return key
        elif not key and len(live) == 1:
            return live[0]
        elif not key:
            raise SoloError(f"which threat? {', '.join(live) or 'none is looming'}")
        else:
            raise SoloError(f"no threat {threat_id!r}; threats: {', '.join(live) or 'none'}")

    def _threat_comes(self, clock_id, cause):
        clock = self.state["clocks"][clock_id]
        self.append("threat", action="triggered", clock=clock_id, label=clock["label"], text=clock["threat"].get("text"), cause=cause,
                    note="it happens now, before anything else: run it in this reply (a fight, a hazard), then go on")
        if clock["threat"]["recurring"]:
            start = int(self.system.get("threats", {}).get("start", 1))
            self.append("clock", clock=clock_id, label=clock["label"], value=start, segments=clock["segments"], full=False, cause=cause)
        else:
            self.append("threat", action="end", clock=clock_id, label=clock["label"], cause=cause)

    def _stage(self, clock_id, stage, cause, rng=None):
        """A clock reached one of its stages: what the player notices (text), what the GM
        must do (note), and what changes for good (facts, other clocks)."""
        moves = {c: v for c, v in stage.get("clock", {}).items() if not self.state["clocks"][c]["stopped"]}
        payload = {"facts": packs.flat_facts(stage.get("facts")), "clock": moves}
        clock = self.state["clocks"][clock_id]
        return self._record("stage", payload, rng, clock=clock_id, label=clock["label"], at=stage["at"],
                            segments=clock["segments"], text=stage.get("text"), note=stage.get("note"), cause=cause)

    def _commit_triggers(self, changes, before):
        triggers = [f"fact:{key}" for key, value in changes.get("facts", {}).items() if value]
        triggers += [f"npc:{nid}:{c['fate']}" for nid, c in changes.get("npc", {}).items() if "fate" in c]
        triggers += [
            f"promise:{pid}:{p['status']}" for pid, p in changes.get("promise", {}).items()
            if p["status"] != p.get("status_was")
        ]
        return Counter(triggers) + self._time_triggers(before, before + changes.get("time", 0))

    def _time_triggers(self, before, after):
        """time:<unit> once for every boundary of that unit crossed between two moments, and `activity` once
        when what happened took a stretch or more (the unit [threats] activity names): a search, a rest, a
        shift of travel. A threat that advances on an activity moves one step for it, however long it took.
        Counted, not listed one by one: a year in rounds is three million of them."""
        triggers = Counter({f"time:{unit}": int(after // seconds - before // seconds) for unit, seconds in self.system["time"].items()})
        minimum = self.system["time"].get((self.system.get("threats") or {}).get("activity", "stretch"))
        triggers["activity"] = int(bool(minimum and after - before >= minimum))
        return +triggers


def _attack_name(text, fallback):
    """What a monster's attack is called, from its result: "Sharp Bite! The wolf sinks
    its teeth into you." is a Sharp Bite. Otherwise the table's name."""
    name, bang, _ = text.partition("!")
    return name.strip() if bang and 0 < len(name.strip()) <= 32 else fallback


def _count_of(item, name):
    """How many of `name` an item line holds: "torch" is 1, "3 torches" is 3, anything else None."""
    words = item.strip().split(" ", 1)
    number, rest = (int(words[0]), words[1]) if len(words) == 2 and words[0].isdigit() else (1, item)
    wanted = slug(name)
    return number if slug(rest) in (wanted, slug(_plural(name))) else None


def _triggers(outcome):
    """What a move's result sets off for the clocks that listen: check:strong_hit, check:weak_hit or check:miss, and check:match."""
    return [f"check:{outcome['hit']}"] + (["check:match"] if outcome["match"] else [])
