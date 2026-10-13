"""Malformed commits. The GM changes the story only through commits, so a commit is untrusted
input: whatever shape it takes, it goes through or is refused with a sentence (a SoloError),
quickly, and the campaign still reads afterwards. The payloads are drawn from a fixed seed,
so a failure here is the same failure on the next run."""

import contextlib
import json
import random
import signal
import unittest

from helpers import HRAFNA, IRONSWORN, OATH, CampaignTest

from solo import SoloError, campaign, cli

# The keys a commit holds, read from _normalize down to _pc_changes, and the keys each holds in turn.
# "clock", "npc" and "faction" hold records by id: the campaign's own, and one it has never heard of.
SCHEMA = {
    "note": None, "chronicle": None, "end": None, "override": None, "chaos": None, "clue": None, "learn": None,
    "time": ["round", "stretch", "shifts", "minutes", "hour", "days"],
    "facts": ["hall.alarm", "gate.guards", "scene", "Bad Key"], "scene": ["facts", "floor_searched"],
    "clock": "clock", "npc": "npc", "faction": "faction",
    "promise": sorted(campaign._PROMISE_KEYS), "consequence": sorted(campaign._CONSEQUENCE_KEYS),
    "pc": ["tracks", "conditions", "items", "spells", "prepared", "abilities", "gold"],
    "npcs": None, "fact": None, "clues": None,
}
FIELDS = {"npc": sorted(campaign._NPC_FIELDS), "faction": ["name", "standing", "memory"]}
WORDS = ["", "two", "+1", "-1", "friendly", "dead", "open", "kept", "2 shifts", "a stretch", "1", "-2", " 4 ", "1e400", "nan", "inf"]


class CommitFuzzTest(CampaignTest):
    cases = 100  # in each of the four campaigns below: about two seconds in all

    def setUp(self):
        super().setUp()
        self.addCleanup(signal.signal, signal.SIGALRM, signal.signal(signal.SIGALRM, self.too_long))

    def too_long(self, *_):
        raise AssertionError("the commit took more than two seconds")

    @contextlib.contextmanager
    def quickly(self):
        signal.alarm(2)
        try:
            yield
        finally:
            signal.alarm(0)

    def junk(self, rng, ids, depth=0):
        """A value of the wrong kind, or of the right kind with the wrong contents: nested a little."""
        kinds = [
            lambda: None, lambda: rng.choice([True, False]), lambda: rng.randint(-5, 5), lambda: 10 ** rng.randint(20, 400),
            lambda: rng.choice([float("nan"), float("inf"), float("-inf")]), lambda: rng.uniform(-1e6, 1e6),
            lambda: rng.choice(WORDS), lambda: rng.choice(ids), lambda: [rng.choice(ids)],
        ]
        if depth < 2:
            kinds += [
                lambda: [self.junk(rng, ids, depth + 1) for _ in range(rng.randint(0, 3))],
                lambda: {rng.choice([*ids, "add", "remove", "id", "text"]): self.junk(rng, ids, depth + 1) for _ in range(rng.randint(0, 3))},
                lambda: {"add": self.junk(rng, ids, depth + 1), "remove": self.junk(rng, ids, depth + 1)},
            ]
        return rng.choice(kinds)()

    def names(self, c):
        """The ids a campaign's commits name, and some it has never heard of."""
        state = c.state
        live = {"npc": [*state["npcs"], "tam"], "faction": [*state["factions"], "elves"], "clock": [*state["clocks"], "nowhere"],
                "pc": SCHEMA["pc"] + list(state["pc"]["tracks"])}
        return live, [*live["npc"], *live["faction"], *live["clock"], *state["pc"]["tracks"], *c.system["conditions"], state["scene"], "rope"]

    def payload(self, rng, live, ids):
        found = {}
        for key in rng.sample(sorted(SCHEMA), rng.randint(1, 3)):
            inner = SCHEMA[key]
            if inner is None or rng.random() < 0.2:
                found[key] = self.junk(rng, ids)
            elif key in FIELDS:
                found[key] = {rng.choice(live[key]): {rng.choice(FIELDS[key]): self.junk(rng, ids) for _ in range(rng.randint(1, 3))}
                              for _ in range(rng.randint(1, 2))}
            else:
                names = live[inner] if isinstance(inner, str) else live.get(key, inner)
                found[key] = {rng.choice(names): self.junk(rng, ids) for _ in range(rng.randint(1, 3))}
                if key in ("promise", "consequence") and rng.random() < 0.4:
                    found[key] = [found[key]]
        if rng.random() < 0.2:
            found["override"] = "the story says so"
        return found

    def test_a_malformed_commit_goes_through_or_is_refused_with_a_sentence(self):
        rng = random.Random(20)
        # A few campaigns, so a hero the junk has killed doesn't leave the rest of the commits refused for that alone.
        roots = [self.root, *(campaign.create(self.tmp / f"game{n}", self.system, self.adventure, self.character) for n in (2, 3)),
                 campaign.create(self.tmp / "ironsworn", IRONSWORN, OATH, HRAFNA)]
        for root in roots:
            with self.subTest(campaign=root.name):
                self.play(rng, root)

    def play(self, rng, root):
        with campaign.session(root) as c:
            live, ids = self.names(c)
        for number in range(self.cases):
            payload = self.payload(rng, live, ids)
            with self.subTest(payload=repr(payload)[:400]), self.quickly():
                try:
                    with campaign.session(root) as c:
                        c.commit(payload, rng=random.Random(number))
                except SoloError:
                    pass
                # As the panel reads it: JSON.parse takes no NaN or Infinity.
                json.loads((root / "state.json").read_text(), parse_constant=self.fail)
        with campaign.session(root) as c:
            cli.resume_digest(c)
            cli.resume_digest(c, book=True)
            cli.recall_text(c, "the")
            cli.scene_digest(c)
            for npc_id in c.state["npcs"]:
                cli.npc_card(c, npc_id)
            replayed = campaign.fold(c.system, c.adventure, c.events)
            self.assertEqual(json.dumps(replayed, sort_keys=True), json.dumps(c.state, sort_keys=True))
            last = c.events[-1]["seq"]
        self.assertEqual(json.loads((root / "state.json").read_text())["seq"], last)


if __name__ == "__main__":
    unittest.main()
