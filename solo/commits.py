"""What a commit says, checked against the packs and the state before anything is logged.

The GM proposes what changed as a JSON object (`solo commit`), and so do the commands that end in one (a
rest, a harm, a spell's cost). _normalize reads it the way it was meant (npcs for npc, facts under the
scene, time in words), refuses what it can't mean and says what to write instead, and gives back absolute
changes (so the log reads without context), the clocks' moves and the warnings. Nothing here writes the
log or changes the state: Campaign._record does both with what comes back. Commits is the part of
Campaign that does the reading. The helpers after it read an amount ("+1", a name, a number), a time, a
list and records keyed by their ids, and the commands use them too.
"""

import json
import math
import re
from collections import Counter

from . import SoloError, combat, oracle, packs
from .eventlog import _line
from .packs import ATTITUDES, FATES, PROMISE_STATUSES, slug
from .reducer import LEARNABLE, _memory, profile_of

_COMMIT_KEYS = {"note", "facts", "npc", "faction", "promise", "pc", "clock", "time", "clue", "chronicle", "override", "chaos", "end", "learn", "consequence"}
# What a clock says, for a commit's time in the words the GM would use for it.
_CLOCK = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
# The most game time one step of the story passes: a year. More is a slip (a number written as text
# once multiplied the text, and the clocks counted the boundaries it crossed for ever).
_MOST_TIME = 365 * 86400
# A commit's time written out: "10 minutes", "a stretch", "2 hours and 30 minutes".
_TIME_WORDS = re.compile(r"\b(?:(\d+(?:\.\d+)?)\s*|(an?|one)\s+)([a-z]+)\b")
# The commit keys that hold a JSON object, with an example, for the GM that sends a string or a list instead.
_COMMIT_OBJECTS = {"facts": '{"hall.alarm": true}', "npc": '{"orc_leader": {"attitude": "unfriendly"}}', "faction": '{"orcs": {"standing": "-1"}}', "pc": '{"hp": "-2"}',
                   "clock": '{"ritual": "+1"}', "time": '{"stretch": 1}, or words like "10 minutes"'}
# What the GM writes down about someone it made up, so the next session meets the same person.
# An adventure's own NPCs have these already; what changes about them is a memory.
PROFILE_FIELDS = ("role", "description", "voice", "wants", "fears")
_NPC_FIELDS = {"name", "faction", "attitude", "fate", "location", "memory", "template", "attacker", "monster", *PROFILE_FIELDS}
# A consequence is something the hero did coming back later: open until the story pays it
# off (done), or until it can't happen any more (dropped).
CONSEQUENCE_STATUSES = ("open", "done", "dropped")
_CONSEQUENCE_KEYS = {"id", "text", "npc", "at", "when", "after", "status"}
_PROMISE_KEYS = {"id", "npc", "terms", "text", "status"}
# Commit keys GMs write in the plural or singular by mistake: read as meant.
_KEY_ALIASES = {"npcs": "npc", "fact": "facts", "factions": "faction", "promises": "promise",
                "consequences": "consequence", "clues": "clue"}
# Words a GM reaches for when it means an item: the refusal says how to write it.
_MONEY = {"gear", "silver", "gold", "copper", "money", "coins", "coin", "treasure", "inventory", "equipment"}


class Commits:
    """The part of Campaign that reads a commit: it looks at self.state, self.system and self.adventure,
    and changes nothing."""

    def _seconds(self, spent, what="time", most="the most one step of the story passes: let it pass a year at a time, or say what happened in between"):
        """{ stretch = 2 } in seconds, in the system's own time units (plural as well: rounds, stretches), or in the
        clock's (minutes: a GM writes what it means). Words read the same: "2 stretches". Each amount is a number
        from zero up (written as text, it reads as the number), and all of it together at most a year (`most` says
        why, and what to do instead)."""
        units = {**_CLOCK, **self.system["time"]}
        plurals = {_plural(unit): unit for unit in units}
        if isinstance(spent, str):
            spent = _time_words(spent) or spent
        if spent is not None and not isinstance(spent, dict):
            raise SoloError(f'{what} is game time, like {{"stretch": 1}} or "2 hours"; not {spent!r}')
        seconds = 0
        for unit, amount in (spent or {}).items():
            one = plurals.get(unit, unit)
            number = _amount(amount)
            if one not in units:
                raise SoloError(f"unknown time unit {unit}; the system has {', '.join(self.system['time']) or 'none'}, and seconds, minutes, hours and days will do")
            elif number is None:
                raise SoloError(f'{what}: {unit} is a number from zero up, like {{"{unit}": 2}}; not {amount!r}')
            elif number > _MOST_TIME or seconds + units[one] * number > _MOST_TIME:
                raise SoloError(f"{what} is more than a year of game time, {most}")
            seconds += units[one] * number
        return int(seconds)

    def _normalize(self, payload):
        """Check a commit against the packs and the current state. Returns absolute changes
        (so the log reads without context), clock moves, and warnings about clamping."""
        if not isinstance(payload, dict):
            raise SoloError("a commit is a JSON object")
        _line(payload)  # text the log can't hold is refused here, before the roll a commit lets stand (see commit)
        warnings = []
        payload = dict(payload)
        for alias, key in _KEY_ALIASES.items():
            # "npcs" for "npc": the meaning is plain, so it is read and said, not refused.
            if alias in payload and key not in payload:
                payload[key] = payload.pop(alias)
                warnings.append(f"read {alias} as {key}")
        if isinstance(payload.get("scene"), str) and payload["scene"] in self.adventure["scenes"]:
            raise SoloError(f"a commit doesn't take the hero anywhere: solo move {payload['scene']}")
        elif "scene" in payload:
            # "A fact under the scene", written the way it reads: {"scene": {"facts": {"floor_searched": true}}}.
            payload["facts"] = {**self._fact_shapes(payload.pop("scene"), under=self.state["scene"]), **self._fact_shapes(payload.get("facts"))}
            warnings.append(f"read scene as facts under {self.state['scene']}")
        elif payload.get("facts") is not None:
            shaped = self._fact_shapes(payload["facts"])
            if shaped != payload["facts"]:
                warnings.append(f"read facts as {json.dumps(shaped, ensure_ascii=False)}")
            payload["facts"] = shaped
        spent = _time_words(payload["time"]) if isinstance(payload.get("time"), str) else None
        if spent:
            warnings.append(f"read time {json.dumps(payload['time'], ensure_ascii=False)} as {json.dumps(spent)}")
            payload["time"] = spent
        unknown = sorted(set(payload) - _COMMIT_KEYS)
        if unknown:
            money = "; coins and gear are items: {\"pc\": {\"items\": {\"add\": [\"30 silver\"]}}}" if set(unknown) & _MONEY else ""
            memory = ('; a memory belongs to someone: {"npc": {"<id>": {"memory": "..."}}}, or to a faction: '
                      '{"faction": {"<id>": {"memory": "..."}}}') if set(unknown) & {"memory", "memories"} else ""
            raise SoloError(f"unknown commit keys: {', '.join(unknown)} (allowed: {', '.join(sorted(_COMMIT_KEYS))}){money}{memory}")
        payload = {key: value for key, value in payload.items() if value is not None}  # null says nothing
        for key, example in _COMMIT_OBJECTS.items():
            if key in payload and not isinstance(payload[key], dict):
                raise SoloError(f"{key} is a JSON object, like {example}")
        override = payload.get("override")
        changes = {}
        for key in ("note", "chronicle", "end"):
            if payload.get(key):
                changes[key] = str(payload[key])
        if payload.get("chaos") is not None:
            low, high = oracle.CHAOS_RANGE
            chaos = _clamp(_shift(payload["chaos"], self.state["chaos"]), low, high)
            if chaos != self.state["chaos"]:
                changes["chaos"] = {"value": chaos, "was": self.state["chaos"]}
        if override:
            changes["override"] = str(override)
        facts = self._facts(payload.get("facts", {}))
        npcs = self._npc_changes(payload.get("npc", {}), override)
        factions = self._faction_changes(payload.get("faction", {}), override)
        promises = self._promise_changes(payload.get("promise", []), npcs)
        pc, pc_warnings = self._pc_changes(payload.get("pc", {}), override)
        warnings += pc_warnings
        clues = [slug(c) for c in _names(payload.get("clue"), "clue")]
        learn = self._learn(payload.get("learn", []), npcs)
        consequences = self._consequence_changes(payload.get("consequence", []), npcs)
        seconds = self._seconds(payload.get("time", {}))
        clock_moves = []
        for clock_id, value in payload.get("clock", {}).items():
            if clock_id in self.state["clocks"] and self.state["clocks"][clock_id]["stopped"]:
                raise SoloError(f"clock {clock_id} has stopped for good; it doesn't move any more")
            elif clock_id in self.state["clocks"]:
                clock = self.state["clocks"][clock_id]
                target = _clamp(_shift(value, clock["value"]), 0, clock["segments"])
                clock_moves.append((clock_id, target - clock["value"]))
            else:
                raise SoloError(f"unknown clock {clock_id}; clocks: {', '.join(self.state['clocks']) or 'none'}")
        parts = {"facts": facts, "npc": npcs, "faction": factions, "promise": promises, "pc": pc, "clues": clues, "learn": learn,
                 "consequence": consequences, "time": seconds}
        changes.update({key: value for key, value in parts.items() if value})
        return changes, clock_moves, warnings

    def _fact_shapes(self, value, under=None):
        """Facts in the other shapes GMs write them, as the {key: value} a commit holds: a list or a line
        of keys (each one true) or of sentences, sentences listed under a key, and `under` a scene, keys
        without the scene's id or wrapped in "facts". A sentence with no key of its own is filed under the
        key it was listed under, else the scene, by its first words, the way a consequence gets its id."""
        if isinstance(value, dict) and under and value and set(value) <= {"facts", "fact"}:
            return {k: v for inner in value.values() for k, v in self._fact_shapes(inner, under).items()}
        elif isinstance(value, dict):
            found = {}
            for key, v in value.items():
                key = key if not under or "." in key else f"{under}.{key}"
                if isinstance(v, list):
                    # Sentences listed under a key are filed under it ("scene": the scene the hero is in).
                    found.update(self._fact_shapes(v, self.state["scene"] if key == "scene" else key))
                else:
                    found[key] = v
            return found
        found = {}
        for item in _listed(value) if value is None or isinstance(value, (list, str)) else [value]:
            if not isinstance(item, str):
                raise SoloError(f"facts is a JSON object, like {_COMMIT_OBJECTS['facts']}")
            text = item.strip()
            if packs.FACT_KEY.match(text):
                found[text if not under or "." in text else f"{under}.{text}"] = True
            elif text:
                base = f"{under or self.state['scene']}.{slug(' '.join(text.split()[:4])) or 'fact'}"
                key, number = base, 1
                # A new sentence never overwrites an older fact that began alike; the same sentence is the same fact.
                while key in found or self.state["facts"].get(key, text) != text:
                    number += 1
                    key = f"{base}_{number}"
                found[key] = text
        return found

    def _facts(self, facts):
        for key, value in facts.items():
            if not packs.FACT_KEY.match(key):
                raise SoloError(f"fact {key!r}: use lowercase words joined by dots, like hall.alarm")
            elif value is not None and not isinstance(value, (bool, int, float, str)):
                raise SoloError(f"fact {key!r}: a value must be true/false, a number or text")
            elif isinstance(value, float) and not math.isfinite(value):
                # state.json would hold NaN or Infinity, which the panel's JSON.parse can't read.
                raise SoloError(f"fact {key!r}: a number must be finite, like 2; not {value!r}")
        return dict(facts)

    def _learn(self, items, new_npcs=None):
        """What the player has found out about an NPC: `<npc>.wants`, `<npc>.fears` or
        `<npc>.<secret id>`. The codex shows these; everything else stays blanked out.
        An NPC the GM made up can be learned about too, from what the GM wrote down."""
        result = []
        if isinstance(items, dict):
            # {"gudrun": "wants"} or {"gudrun": ["wants", "fears"]}: the same as "gudrun.wants".
            items = [f"{npc_id}.{what}" for npc_id, whats in items.items() for what in _names(whats, f"learn {npc_id}")]
        elif not isinstance(items, (str, list)):
            raise SoloError(f'learn is what the player found out, like ["orc_leader.wants"]; not {items!r}')
        for item in [items] if isinstance(items, str) else items:
            npc_id, _, what = str(item).partition(".")
            profile = None
            if npc_id in self.state["npcs"] or npc_id in (new_npcs or {}):
                profile = {**profile_of(self.adventure, self.state, npc_id), **(new_npcs or {}).get(npc_id, {}).get("profile", {})}
            secrets = [s.get("id") for s in (profile or {}).get("secrets", [])]
            if profile is None:
                raise SoloError(f"learn {item!r}: unknown npc {npc_id!r}")
            elif not (what in LEARNABLE and profile.get(what)) and what not in secrets:
                known = [k for k in LEARNABLE if profile.get(k)] + secrets
                raise SoloError(f"learn {item!r}: {npc_id} has {', '.join(known) or 'nothing to learn'}")
            elif f"{npc_id}.{what}" not in self.state["learned"] + result:
                result.append(f"{npc_id}.{what}")
        return result

    def _npc_changes(self, updates, override):
        result = {}
        for npc_id, fields in updates.items():
            current = self.state["npcs"].get(npc_id)
            authored = self.adventure["npcs"].get(npc_id, {})
            if not isinstance(fields, dict):
                raise SoloError(f'npc {npc_id}: give the fields as an object, like {{"attitude": "+1", "memory": "..."}}')
            unknown = sorted(set(fields) - _NPC_FIELDS)
            if unknown:
                place = "; where someone is, is location (a scene id)" if set(unknown) & {"at", "place", "scene"} else ""
                raise SoloError(f"npc {npc_id}: unknown fields {', '.join(unknown)} (allowed: {', '.join(sorted(_NPC_FIELDS))}){place}")
            elif current is None and not fields.get("name"):
                raise SoloError(f"npc {npc_id!r} isn't in the adventure; give it a name to add it")
            strange = next((k for k in ("name", "fate", "location", "faction", "template", "attacker", "monster")
                            if fields.get(k) is not None and not isinstance(fields[k], str)), None)
            if strange:
                raise SoloError(f"npc {npc_id}: {strange} is a word or an id, as text; not {fields[strange]!r}")
            is_new = current is None
            change = {"name": fields["name"], "new": True} if is_new else {}
            named = str(fields.get("name") or "").strip()
            if not is_new and named and named.casefold() != current["name"].casefold():
                # A person keeps their name: two in the story is two people to the player. (This used to be dropped without a word.)
                if not override:
                    raise SoloError(f"npc {npc_id} is already called {current['name']}: a person keeps their name. If this is someone else, "
                                    'give them an id of their own; if the story really names them now, add "override": "<reason>"')
                change.update(name=named, name_was=current["name"])
            current = current or {"attitude": 0, "fate": "alive"}
            if "attitude" in fields:
                attitude = _clamp(_shift(fields["attitude"], current["attitude"], ATTITUDES), -2, 2)
                if not is_new and abs(attitude - current["attitude"]) > 1 and not override:
                    raise SoloError(
                        f"npc {npc_id}: attitude moves one step per commit ({current['attitude']} -> {attitude}); "
                        'add "override": "<reason>" if the adventure says otherwise'
                    )
                change.update(attitude=attitude, attitude_was=current["attitude"])
            if "fate" in fields:
                if fields["fate"] not in FATES:
                    raise SoloError(f"npc {npc_id}: fate must be one of {', '.join(FATES)}")
                elif authored.get("many"):
                    raise SoloError(
                        f"npc {npc_id} is a kind of foe the hero meets again and again ({authored.get('name', npc_id)}), "
                        f"so no one fate covers them all: say what became of these ones with a fact "
                        f'({{"facts": {{"{self.state["scene"]}.{npc_id}": "two fled"}}}}), or give one a name of their own to follow them')
                elif current["fate"] == "dead" and fields["fate"] != "dead" and not override:
                    raise SoloError(f'npc {npc_id} is dead; add "override": "<reason>" to change that')
                change.update(fate=fields["fate"], fate_was=current["fate"])
            if "location" in fields and fields["location"] not in (None, *self.adventure["scenes"]):
                raise SoloError(f"npc {npc_id}: unknown location {fields['location']}")
            if "faction" in fields and fields["faction"] not in self.state["factions"]:
                raise SoloError(f"npc {npc_id}: unknown faction {fields['faction']}")
            npcs = self.system.get("npcs", {})
            if "template" in fields and fields["template"] not in npcs.get("templates", {}):
                raise SoloError(f"npc {npc_id}: template must be one of {', '.join(npcs.get('templates', {})) or 'none'}")
            if "attacker" in fields and fields["attacker"] not in npcs.get("attackers", []):
                raise SoloError(f"npc {npc_id}: attacker must be one of {', '.join(npcs.get('attackers', [])) or 'none'}")
            if fields.get("memory") is not None and not isinstance(fields["memory"], str):
                raise SoloError(f'npc {npc_id}: a memory is one line of text, like {{"memory": "saw the hero spare the guard"}}; '
                                "two things remembered are two commits")
            if "monster" in fields and fields["monster"] not in self.system.get("bestiary", {}):
                known = ", ".join(self.system.get("bestiary", {})) or "none: the system pack has no bestiary"
                raise SoloError(f"npc {npc_id}: monster must be one of the bestiary's ({known})")
            change.update({k: fields[k] for k in ("location", "faction", "memory", "template", "attacker", "monster") if k in fields})
            if isinstance(change.get("memory"), str):
                change["memory"] = _memory(change["memory"])
            profile = {k: str(fields[k]).strip() for k in PROFILE_FIELDS if str(fields.get(k) or "").strip()}
            written = [k for k in profile if authored.get(k)]
            if written:
                raise SoloError(f"npc {npc_id}: the adventure already gives their {', '.join(written)}; "
                                "what changed about them goes in a memory")
            elif profile:
                change["profile"] = profile
            result[npc_id] = change
        return result

    def _faction_changes(self, updates, override):
        result = {}
        for faction_id, value in updates.items():
            current = self.state["factions"].get(faction_id)
            spec = value if isinstance(value, dict) else {"standing": value}
            unknown = sorted(set(spec) - {"name", "standing", "memory"})
            if unknown:
                raise SoloError(f"faction {faction_id}: unknown fields {', '.join(unknown)} (allowed: memory, name, standing)")
            elif current is None and not spec.get("name"):
                raise SoloError(f'faction {faction_id!r} isn\'t in the adventure; add it with {{"name": ..., "standing": 0}}')
            elif spec.get("memory") is not None and not isinstance(spec["memory"], str):
                raise SoloError(f'faction {faction_id}: what they heard is one line of text, like {{"memory": "the hero spared the guard"}}')
            elif spec.get("name") is not None and not isinstance(spec["name"], str):
                raise SoloError(f"faction {faction_id}: a name is text; not {spec['name']!r}")
            old = current["standing"] if current else 0
            standing = _clamp(_shift(spec.get("standing", old), old, ATTITUDES), -2, 2)
            if current is not None and abs(standing - old) > 1 and not override:
                raise SoloError(
                    f"faction {faction_id}: standing moves one step per commit ({old} -> {standing}); "
                    'add "override": "<reason>" if the adventure says otherwise'
                )
            result[faction_id] = {"standing": standing, "standing_was": old}
            if current is None:
                result[faction_id]["name"] = spec["name"]
            if str(spec.get("memory") or "").strip():
                # Word spreads: what the faction has heard of the hero, for the next of them they meet.
                result[faction_id]["memory"] = _memory(spec["memory"])
        return result

    def _consequence_changes(self, items, new_npcs):
        """Something the hero did that will come back: when the hero is somewhere (`at`),
        meets someone (`npc`, when nothing else says when), a condition holds (`when`), or
        game time has passed (`after`). Given several, all must hold. Updates by id: a
        status (done, dropped), new words or new triggers."""
        result = {}
        for item in _by_id(items, _CONSEQUENCE_KEYS):
            if not isinstance(item, dict):
                raise SoloError('a consequence is an object: {"id": ..., "text": "what will happen", "npc": ..., "at": ..., "when": ..., "after": {"shift": 1}}')
            unknown = sorted(set(item) - _CONSEQUENCE_KEYS)
            text = str(item.get("text") or "").strip()
            consequence_id = slug(str(item.get("id") or " ".join(text.split()[:4])))
            if not item.get("id") and consequence_id:
                # An id made from the words is a new consequence, never an old one that began alike.
                base, number = consequence_id, 1
                while consequence_id in self.state["consequences"] or consequence_id in result:
                    number += 1
                    consequence_id = f"{base}_{number}"
            current = self.state["consequences"].get(consequence_id)
            status = item.get("status", current["status"] if current else "open")
            if unknown:
                raise SoloError(f"consequence: unknown fields {', '.join(unknown)} (allowed: {', '.join(sorted(_CONSEQUENCE_KEYS))})")
            elif not consequence_id:
                raise SoloError("a consequence needs an id, or its text to make one from")
            elif current is None and not text:
                known = ", ".join(self.state["consequences"]) or "none yet"
                raise SoloError(f"consequence {consequence_id}: a new one needs its text (what will happen, and to whom); consequences: {known}")
            elif status not in CONSEQUENCE_STATUSES:
                raise SoloError(f"consequence {consequence_id}: status must be one of {', '.join(CONSEQUENCE_STATUSES)}")
            change = {"status": status, "status_was": current["status"] if current else None}
            if text:
                change["text"] = text
            if item.get("npc") is not None:
                if not isinstance(item["npc"], str):
                    raise SoloError(f"consequence {consequence_id}: npc is the id of the one it waits for, as text; not {item['npc']!r}")
                elif item["npc"] not in self.state["npcs"] and item["npc"] not in new_npcs:
                    raise SoloError(f"consequence {consequence_id}: unknown npc {item['npc']}; someone new goes in the same commit's "
                                    f'npc with a name: {{"npc": {{"{item["npc"]}": {{"name": "..."}}}}}}')
                change["npc"] = item["npc"]
            if item.get("at") is not None:
                places = [slug(p) for p in _names(item["at"], f"consequence {consequence_id}: at")]
                strange = [p for p in places if p not in self.adventure["scenes"]]
                if strange:
                    raise SoloError(f"consequence {consequence_id}: unknown scene {strange[0]}; at names scene ids, like {self.state['scene']}")
                change["at"] = places
            if item.get("when"):
                try:
                    packs.compile_condition(str(item["when"]))
                except SoloError as error:
                    raise SoloError(
                        f"consequence {consequence_id}: {error}. `when` is a condition the engine can check, like "
                        "fact.hall.alarm or clock.dark_ritual >= 4. To wait for something that happens in the story, "
                        "leave when out and give at, npc or after, or no trigger at all (a loose end you bring in)") from None
                change["when"] = str(item["when"])
            if item.get("after"):
                seconds = self._seconds(item["after"], what=f"consequence {consequence_id}: after",
                                        most="the furthest ahead a consequence waits: leave after out, and bring it in yourself when its time comes")
                if seconds <= 0:
                    raise SoloError(f'consequence {consequence_id}: after is game time from now, like {{"shift": 1}}')
                change["due_at"] = self.state["time"] + seconds
            if current is None or {"npc", "at", "when", "due_at"} & set(change):
                # Waiting starts now: `at` and `npc` wait for the hero's next arrival, so one
                # made in front of the smith comes due when the hero comes back to him.
                change.update(arrivals=self.state["arrivals"], due=False)
            result[consequence_id] = change
        return result

    def _promise_changes(self, items, new_npcs):
        """Promises by id: a new one needs npc and terms (`text` reads as terms), and an id,
        made from the terms when none is given; an update needs only its status."""
        result = {}
        for item in _by_id(items, _PROMISE_KEYS):
            if not isinstance(item, dict):
                raise SoloError('a promise is an object: {"id": ..., "npc": ..., "terms": "what was promised", "status": "open"}')
            item = {**item, "terms": item.get("terms") or item.get("text")} if item.get("text") else item
            promise_id = slug(str(item.get("id") or ""))
            if not promise_id and item.get("terms"):
                base = promise_id = slug(" ".join(str(item["terms"]).split()[:4]))
                number = 1
                while promise_id in self.state["promises"] or promise_id in result:
                    number += 1
                    promise_id = f"{base}_{number}"
            current = self.state["promises"].get(promise_id)
            status = item.get("status", current["status"] if current else "open")
            npc = item.get("npc", current["npc"] if current else None)
            terms = item.get("terms", current["terms"] if current else None)
            if not promise_id:
                raise SoloError("a promise needs an id, or its terms to make one from")
            elif status not in PROMISE_STATUSES:
                raise SoloError(f"promise {promise_id}: status must be one of {', '.join(PROMISE_STATUSES)}")
            elif not (npc and terms):
                raise SoloError(f"promise {promise_id}: a new promise needs npc and terms")
            elif not (isinstance(npc, str) and isinstance(terms, str)):
                raise SoloError(f'promise {promise_id}: npc is an id and terms are what was promised, both as text, like {{"npc": "orc_leader", "terms": "..."}}')
            elif npc not in self.state["npcs"] and npc not in new_npcs:
                raise SoloError(f"promise {promise_id}: unknown npc {npc}")
            else:
                result[promise_id] = {
                    "npc": npc, "terms": terms, "status": status,
                    "status_was": current["status"] if current else None,
                }
        return result

    def _pc_changes(self, updates, override=None):
        pc = self.state["pc"]
        dying = self.system.get("dying") or {}
        result, warnings = {}, []
        if updates and pc["dead"] and not override:
            raise SoloError(f'{pc["name"]} is dead; add "override": "<reason>" to change that')
        if isinstance(updates.get("tracks"), dict):
            # {"pc": {"tracks": {"hp": 3}}} can only mean the tracks themselves.
            updates = {**{k: v for k, v in updates.items() if k != "tracks"}, **updates["tracks"]}
        # An impact cleared in this same commit no longer holds its track down.
        cleared = [slug(c) for c in _names(updates["conditions"].get("remove"), "pc conditions remove")] if isinstance(updates.get("conditions"), dict) else []
        for key, value in updates.items():
            if key in pc["tracks"]:
                track = pc["tracks"][key]
                low = track.get("min", 0)
                if (isinstance(value, int) and not isinstance(value, bool) or isinstance(value, float) and math.isfinite(value)) and value < 0:
                    # A track is never set below zero, so -3 can only mean "lose 3". Setting HP to 0
                    # instead would leave the hero dying over a scratch (a GM wrote exactly this).
                    warnings.append(f"read {key} {value} as a loss of {-int(value)}; write \"{int(value)}\" as text to move a value")
                    value = str(int(value))
                wanted = _shift(value, track["value"])
                held = [c for c in pc["conditions"] if c not in cleared and self.system["conditions"].get(c) == key]
                if held and wanted > track["value"]:
                    # Wounded, shaken and unprepared (Ironsworn) keep health, spirit and supply from rising.
                    warnings.append(f"{key} can't rise while {held[0]} is marked: clear it first")
                    wanted = track["value"]
                result.setdefault("tracks", {})[key] = _clamp(wanted, low, track["max"])
                result.setdefault("tracks_was", {})[key] = track["value"]
                if key == dying.get("track") and pc["dying"] and wanted < 0:
                    # Harm while dying: one failed death roll.
                    result["death_failures"] = 1
                elif result["tracks"][key] != wanted:
                    warnings.append(f"{key} stops at {result['tracks'][key]} (range {low}-{track['max']})")
            elif key in ("conditions", "items", "spells", "prepared", "abilities") and not isinstance(value, dict):
                # A list could mean the ones to add or all the hero has now: which, the GM says.
                example = next(iter(self.system["conditions"]), "...") if key == "conditions" else "rope" if key == "items" else "..."
                raise SoloError(f'pc {key} is what to add and what to remove, like {{"{key}": {{"add": ["{example}"], "remove": []}}}}; not {value!r}')
            elif key == "conditions":
                # One name is a list of one: {"add": "dazed"} is dazed, not d, a, z, e, d.
                add = [slug(c) for c in _names(value.get("add"), "pc conditions add")]
                remove = [slug(c) for c in _names(value.get("remove"), "pc conditions remove")]
                unknown = [c for c in add + remove if c not in self.system["conditions"]]
                if unknown:
                    raise SoloError(f"unknown conditions {', '.join(unknown)}; the system has {', '.join(self.system['conditions'])}")
                result["conditions_add"] = [c for c in add if c not in pc["conditions"]]
                result["conditions_remove"] = [c for c in remove if c in pc["conditions"]]
            elif key == "items":
                result["items_add"] = _names(value.get("add"), "pc items add")
                result["items_remove"] = [i for i in _names(value.get("remove"), "pc items remove") if i in pc["items"]]
                warnings += [f"{i} isn't carried" for i in _names(value.get("remove"), "pc items remove") if i not in pc["items"]]
            elif key in ("spells", "prepared"):
                have = pc.get(key, [])
                result[f"{key}_add"] = [a for a in _names(value.get("add"), f"pc {key} add") if a not in have]
                result[f"{key}_remove"] = [a for a in _names(value.get("remove"), f"pc {key} remove") if a in have]
            elif key == "abilities":
                # What the hero has learned or lost: a heroic ability, an asset, or its upgrade ("Slayer, second ability").
                # One that can be taken again and again (Robust) can be added again.
                stacks = {slug(spec.get("name", aid)) for aid, spec in self.system.get("abilities", {}).items() if spec.get("stack")}
                result["abilities_add"] = [a for a in _names(value.get("add"), "pc abilities add") if a not in pc["abilities"] or slug(a) in stacks]
                result["abilities_remove"] = [a for a in _names(value.get("remove"), "pc abilities remove") if a in pc["abilities"]]
                warnings += [f"{a} {why}" for a in result["abilities_add"] for why in [self._unmet(a)] if why]
                raised = Counter()
                for a in result["abilities_add"]:
                    spec = next((spec for aid, spec in self.system.get("abilities", {}).items() if slug(a) in (aid, slug(spec.get("name", aid)))), {})
                    raised.update({track: int(n) for track, n in (spec.get("max") or {}).items()})
                if raised:
                    result["max_up"] = dict(raised)
                warnings += [f"{a} isn't among {pc['name']}'s abilities" for a in _names(value.get("remove"), "pc abilities remove") if a not in pc["abilities"]]
            else:
                money = " (coins and gear are items: {\"pc\": {\"items\": {\"add\": [\"30 silver\"]}}})" if key in _MONEY else ""
                raise SoloError(f"pc has no {key!r}; use a track ({', '.join(pc['tracks'])}), conditions, items or abilities{money}")
        return {k: v for k, v in result.items() if v}, warnings

    def _unmet(self, name):
        """Why the hero can't have this ability yet (its skill requirement), or None."""
        spec = next((spec for aid, spec in self.system.get("abilities", {}).items() if slug(name) in (aid, slug(spec.get("name", aid)))), None)
        need, pc = (spec or {}).get("requires"), self.state["pc"]
        if not need:
            return None
        weapons = combat.weapons(self.system)
        kinds = {"weapon": {w["skill"] for w in weapons.values() if w["id"] != "unarmed"},
                 "melee": {w["skill"] for w in weapons.values() if w["id"] != "unarmed" and not w["ranged"]},
                 "str_melee": {w["skill"] for w in weapons.values() if w["id"] != "unarmed" and not w["ranged"] and self.system["skills"].get(w["skill"], {}).get("attribute") == "str"},
                 "magic": {k for k, sk in self.system["skills"].items() if not sk["untrained"]}}
        skills = need.get("skills") or sorted(kinds.get(need.get("kind"), ()))
        best = max((pc["skills"].get(k, {}).get("value", 0) for k in skills), default=0)
        if best < int(need.get("level", 0)):
            label = " or ".join(self.system["skills"][k]["name"] if k in self.system["skills"] else k for k in skills) if need.get("skills") else f"any {need['kind'].replace('_', '-')} skill"
            return f"needs {label} at {need['level']} (the best is {best})"
        return None


def _shift(value, old, names=None):
    """ "+1" / "-2" move from the old value; a number or a name sets it outright."""
    text = value.strip() if isinstance(value, str) else None
    if isinstance(value, bool) or value is None:
        raise SoloError(f"can't use {value!r} as an amount")
    elif isinstance(value, int) or (isinstance(value, float) and math.isfinite(value)):
        return int(value)
    elif text and re.fullmatch(r"[+-]\d+", text):
        try:
            return old + int(text)
        except ValueError:  # more digits than Python reads as a number (4300): no step is that long
            raise SoloError(f"can't use a step of {len(text) - 1} digits: write \"+1\", \"-1\" or a number") from None
    elif text and names and text in names:
        return names[text]
    else:
        raise SoloError(f"can't use {value!r}: write \"+1\", \"-1\" or a number" + (f", or one of {', '.join(names)}" if names else ""))


def _by_id(items, fields):
    """Records given as a list, as one object, or keyed by their ids, the way npc and faction
    are ({"hrok_talks": {"status": "done"}}): always a list of objects with their id inside."""
    if isinstance(items, dict):
        if items and not set(items) & fields and all(isinstance(v, dict) for v in items.values()):
            return [{"id": key, **value} for key, value in items.items()]
        return [items]
    return list(items) if isinstance(items, list) else [items]


def _listed(value):
    return [] if value is None else [value] if isinstance(value, str) else list(value)


def _names(value, what):
    """A name or a list of names from a commit, as a list. Anything else is refused, saying what the key holds."""
    if value is None:
        return []
    elif isinstance(value, str):
        return [value]
    elif isinstance(value, list) and all(isinstance(name, str) for name in value):
        return list(value)
    raise SoloError(f"{what} is a name or a list of names; not {value!r}")


def _amount(value):
    """A number from zero up, from a number or the text of one ("2"), or None: never true or false, NaN or infinity."""
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return value if value >= 0 else None


def _time_words(text):
    """{"minutes": 10} for "10 minutes", or None for words that say something else ("until dawn")."""
    text = text.lower()
    found = _TIME_WORDS.findall(text)
    if not found or re.sub(r"\band\b|[\s,&+]", "", _TIME_WORDS.sub("", text)):
        return None
    spent = {}
    for number, _, unit in found:
        spent[unit] = spent.get(unit, 0) + (float(number) if number else 1)
    # A number too long for a float is infinity, left as it is for _seconds to refuse.
    return {unit: int(amount) if math.isfinite(amount) and amount == int(amount) else amount for unit, amount in spent.items()}


def _clamp(value, low, high):
    return max(low, min(high, value))


def _plural(word):
    return word + ("es" if word.endswith(("ch", "sh", "s", "x")) else "s")
