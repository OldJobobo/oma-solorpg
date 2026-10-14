"""Campaigns generated from a premise: the same premise and dice roll the same pack; the pack
validates, lints clean and plays through its first mission; the next mission, rolled from
what the hero did, loads into the campaign under way and brings back something the hero did;
and adventures in chapters, which that rests on."""

import contextlib
import io
import random
import re
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from helpers import DRAGONBANE, RAGNA, FIXTURES, CampaignTest, install_rules, leave_the_shell_out

from solo import SoloError, campaign, cli, generate, library, packs

PREMISE = "a smuggler's coast where the dead keep the lighthouses"
# A seed whose first mission Ragna fights through alive (the playthrough below).
SEED = 11


def roll(folder, seed=SEED, missions=3, system=DRAGONBANE):
    return generate.new(folder, system, PREMISE, tone="grim", missions=missions, seed=seed, system_name="dragonbane")


def write_up(pack):
    """What the agent does with the solo-campaign skill, as far as the checks can see: every
    file written up (the mark gone) and the drafts published."""
    for path in [*pack.glob("*.toml"), *pack.glob("*/*.toml"), *pack.glob("scenes/*.md")]:
        text = path.read_text(encoding="utf-8")
        text = "\n".join(line for line in text.splitlines() if generate.MARK not in line and line.strip() != "draft = true")
        path.write_text(text + "\n", encoding="utf-8")


def files(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


class Folder(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        leave_the_shell_out(self)


class Rolled(Folder):
    def test_the_same_premise_and_dice_roll_the_same_pack(self):
        roll(self.tmp / "a")
        roll(self.tmp / "b")
        roll(self.tmp / "c", seed=SEED + 1)
        self.assertEqual(files(self.tmp / "a"), files(self.tmp / "b"))
        self.assertNotEqual(files(self.tmp / "a"), files(self.tmp / "c"))

    def test_it_validates_lints_clean_and_is_a_draft(self):
        pack = self.tmp / "salt"
        made = roll(pack)
        adventure = packs.load_adventure(pack)
        system = packs.load_system(DRAGONBANE)
        self.assertEqual(packs.validate(system, adventure), [])
        self.assertEqual(packs.lint(adventure), [])
        self.assertTrue(adventure["draft"])
        self.assertEqual(adventure["chapters"], ["mission_1"])
        self.assertEqual(adventure["start"], "hub")
        self.assertTrue(adventure["scenes"]["hub"]["safe"])
        self.assertEqual(made["mission"]["scenes"], ["m1_w1", "m1_w2", "m1_w3", "m1_heart"])
        self.assertEqual(adventure["summary"], f"A grim campaign in 3 missions: {PREMISE}")
        # The clock counts the whole campaign, and its last stage is what the last heart reads.
        self.assertEqual(adventure["clocks"]["plan"]["segments"], 9)
        self.assertEqual(adventure["clocks"]["plan"]["stages"][-1]["facts"], {"plan.done": True})
        # A campaign under way plays on without a draft chapter.
        self.assertNotIn("m1_w1", packs.load_adventure(pack, drafts=False)["scenes"])

    def test_every_roll_is_recorded_and_cited(self):
        pack = self.tmp / "salt"
        roll(pack)
        rolls = generate.load_rolls(pack)
        self.assertEqual([r["n"] for r in rolls], list(range(1, len(rolls) + 1)))
        adventure = packs.load_adventure(pack)
        # The system's own tables have their say: the solo rules' threat, the treasure, the inspiration words.
        tables = {r["table"] for r in rolls}
        self.assertIn("Threats", tables)
        self.assertIn("meaning", tables)
        self.assertTrue(adventure["scenes"]["m1_heart"]["source"].startswith("rolled: #"))
        report = generate.check(pack)
        self.assertFalse([p for p in report["problems"] if "roll #" in p], report["problems"])
        # Written up by the agent, it's ready.
        self.assertTrue(any("still as rolled" in p for p in report["problems"]))
        write_up(pack)
        self.assertEqual(generate.check(pack)["problems"], [])

    def test_the_check_holds_the_author_to_the_dice(self):
        pack = self.tmp / "salt"
        roll(pack)
        write_up(pack)
        chapter = pack / "chapters" / "mission_1.toml"
        chapter.write_text(chapter.read_text(encoding="utf-8").replace('source = "rolled: #', 'source = "chose: #'), encoding="utf-8")
        problems = generate.check(pack)["problems"]
        self.assertTrue(any(re.match(r"roll #\d+ .* is used by nothing", p) for p in problems), problems)
        (pack / "scenes" / "m1_w1.md").write_text("A road.\n\n::: gm\nrolled: #999\n:::\n", encoding="utf-8")
        self.assertIn(f"a source cites roll #999, which isn't in {generate.ROLLS}", generate.check(pack)["problems"])

    def test_an_authors_roll_is_recorded_and_a_skipped_one_explained(self):
        pack = self.tmp / "salt"
        roll(pack)
        write_up(pack)
        with unittest.mock.patch.object(library, "find_system", return_value=DRAGONBANE):
            record = generate.roll(pack, "treasure", "what the lighthouse keeper hides", rng=random.Random(1))
            generate.roll(pack, "meaning", "the inn's landlord", rng=random.Random(2))
            generate.roll(pack, "2d6", "how many keepers", rng=random.Random(3))
            with self.assertRaisesRegex(SoloError, "neither a table"):
                generate.roll(pack, "no_such_table", "x")
        rolls = generate.load_rolls(pack)
        self.assertEqual(rolls[-3]["n"], record["n"])
        self.assertEqual(rolls[-1]["table"], "2d6")
        self.assertEqual(len([p for p in generate.check(pack)["problems"] if "is used by nothing" in p]), 3)
        with open(pack / generate.ROLLS, "a", encoding="utf-8") as log:
            log.write('note = "the landlord came out of the story"\n')  # onto the last roll
        (pack / "scenes" / "m1_w1.md").write_text(f"A road.\n\n::: gm\nThe keeper (rolled: #{record['n']}, #{record['n'] + 1}).\n:::\n",
                                                   encoding="utf-8")
        self.assertEqual(generate.check(pack)["problems"], [])

    def test_a_system_without_foes_or_threats_still_rolls_a_playable_pack(self):
        pack = self.tmp / "yze"
        generate.new(pack, FIXTURES / "yze" / "system", PREMISE, missions=2, seed=3)
        adventure = packs.load_adventure(pack)
        system = packs.load_system(FIXTURES / "yze" / "system")
        self.assertEqual(packs.validate(system, adventure), [])
        # No threats table: the mission counts its own time.
        self.assertIn("m1_time", adventure["clocks"])
        self.assertTrue(all(v["skill"] in system["skills"] or v["skill"] in system["attributes"]
                            for s in adventure["scenes"].values() for v in s.get("voices", [])))

    def test_refusals(self):
        with self.assertRaisesRegex(SoloError, "needs a premise"):
            generate.new(self.tmp / "x", DRAGONBANE, "  ")
        with self.assertRaisesRegex(SoloError, "missions must be"):
            generate.new(self.tmp / "x", DRAGONBANE, PREMISE, missions=0)
        roll(self.tmp / "x")
        with self.assertRaisesRegex(SoloError, "already holds an adventure"):
            roll(self.tmp / "x")
        with self.assertRaisesRegex(SoloError, "has only its names"):
            generate.new(self.tmp / "y", library.REPO / "packs" / "dragonbane", PREMISE)


class Played(CampaignTest):
    """The first mission played with fixed dice, then the next rolled into the pack under
    the running campaign."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.pack = Path(folder.name) / "salt"
        roll(self.pack)
        write_up(self.pack)
        self.adventure = self.pack
        super().setUp()

    def fight_through(self, c, foes, rng):
        c.fight(foes, rng=rng)
        for _ in range(40):
            fight = c.state["combat"]
            if fight is None or c.state["pc"]["dying"]:
                break
            standing = [fid for fid, foe in fight["foes"].items() if not foe["down"]]
            c.attack(standing[0], rng=rng)
            for fid in [fid for fid, foe in (c.state["combat"] or {"foes": {}})["foes"].items() if not foe["down"]]:
                if c.state["pc"]["dying"]:
                    break
                c.enemy(fid, rng=rng)
                if c.state["combat"]["incoming"]:
                    c.defend("parry", rng=rng)
            if c.state["combat"]:
                c.next_round(rng=rng)

    def play_mission_one(self, c, rng):
        adventure = c.adventure
        self.assertIn("Mission 1 of 3", cli.scene_digest(c))
        threat, fights = c.system["tables"]["threats"], 0
        c.move("m1_w1", rng=rng)
        c.threat(threat["results"][0]["text"], threat_id="m1_threat", recurring=True)
        for sid in ("m1_w1", "m1_w2", "m1_w3", "m1_heart"):
            if c.state["scene"] != sid:
                c.move(sid, rng=rng)
            here = adventure["scenes"][sid]
            foes = [n for n in here.get("npcs", []) if adventure["npcs"][n].get("template") or adventure["npcs"][n].get("monster")]
            if foes:
                fights += 1
                self.fight_through(c, foes, rng)
                self.assertFalse(c.state["pc"]["dying"], f"Ragna fell at {sid}: pick another SEED")
        self.assertEqual([e["type"] for e in c.events].count("fight_end"), fights)
        c.commit({"facts": {"mission_1.done": True}, "npc": {"m1_heart_lieutenant": {"fate": "dead"}},
                  "chronicle": "Ragna broke the lieutenant's hold on the heart of it."})
        c.move("hub", rng=rng)

    def test_the_first_mission_plays_through_and_the_hub_waits_for_the_next(self):
        rng = random.Random(4)
        with self.session() as c:
            self.play_mission_one(c, rng)
            digest = cli.scene_digest(c)
            self.assertEqual(c.state["scene"], "hub")
            self.assertTrue(c.state["facts"]["mission_1.done"])
            self.assertNotIn("Mission 1 of 3", digest)  # its briefing is done
            self.assertIn("hasn't been written yet", digest)
            self.assertEqual(campaign.fold(c.system, c.adventure, c.events), c.state)

    def test_the_next_mission_loads_into_the_campaign_and_brings_back_what_the_hero_did(self):
        rng = random.Random(4)
        with self.assertRaisesRegex(SoloError, "mission 1 isn't done"):
            generate.next_mission(self.root)
        with self.session() as c:
            c.commit({"npc": {"old_sula": {"name": "Old Sula", "role": "keeper of the north light", "voice": "croaks",
                                           "wants": "her drowned son's name cleared", "memory": "Ragna promised to find her son's grave"}},
                      "facts": {"hero.oath": "never to let a light go dark"},
                      "consequence": {"id": "sula_waits", "text": "Old Sula waits for news of her son's grave", "npc": "old_sula"}})
            self.play_mission_one(c, rng)
            before = c.state
        made = generate.next_mission(self.root, rng=random.Random(9))
        self.assertEqual(made["mission"], 2)
        self.assertEqual(len(made["threads"]), 2)
        chapter = packs.load_data(self.pack / "chapters" / "mission_2.toml")
        self.assertTrue(chapter["draft"])
        # Old Sula, made up in play, has a file of her own now, as the GM made her up; nothing the log sets.
        sula = packs.load_data(self.pack / "npcs" / "old_sula.toml")
        self.assertEqual((sula["name"], sula["wants"], sula["voice"]), ("Old Sula", "her drowned son's name cleared", "croaks"))
        self.assertFalse({"attitude", "fate", "faction", "location"} & set(sula))
        # The draft doesn't reach the campaign: the hub still says the next mission isn't written.
        with self.session() as c:
            self.assertNotIn("m2_w1", c.adventure["scenes"])
            # Its people are on file but met by no one, so nothing about them shows yet.
            new = set(c.state["npcs"]) - set(before["npcs"])
            self.assertTrue(new and not any(c.state["npcs"][n]["met"] for n in new))
            unchanged = lambda npcs: {k: {f: v for f, v in n.items() if f != "fought"} for k, n in npcs.items() if k not in new}  # noqa: E731
            self.assertEqual({**c.state, "npcs": unchanged(c.state["npcs"])}, {**before, "npcs": unchanged(before["npcs"])})
        write_up(self.pack)
        with self.session() as c:
            self.assertEqual(c.problems, [])
            self.assertEqual(campaign.fold(c.system, c.adventure, c.events), c.state)
            digest = cli.scene_digest(c)
            self.assertIn("Mission 2 of 3", digest)
            self.assertIn("m2_w1: Set out", digest.split("## Exits")[1].split("##")[0])
            # What the dice picked to come back is in the mission, with the people in it placed.
            text = "".join(packs.scene_text(c.adventure, s) for s in c.adventure["scenes"] if s.startswith("m2_"))
            self.assertIn("sula_waits", text)
            self.assertIn("never to let a light go dark", text)
            placed = {n for s, scene in c.adventure["scenes"].items() if s.startswith("m2_") for n in scene.get("npcs", [])}
            self.assertIn("old_sula", placed)
            # Everything before stands as it was: the people, the facts, the chronicle.
            for key in ("facts", "chronicle", "consequences", "promises", "time", "visited"):
                self.assertEqual(c.state[key], before[key])
            sula = {k: v for k, v in c.state["npcs"]["old_sula"].items() if k != "fought"}
            self.assertEqual(sula, before["npcs"]["old_sula"])  # where she was met, what she remembers
            c.move("m2_w1", rng=rng)
            self.assertEqual(c.state["scene"], "m2_w1")
        self.assertEqual(packs.lint(packs.load_adventure(self.pack)), [])
        self.assertEqual(generate.check(self.pack)["problems"], [])
        with self.assertRaisesRegex(SoloError, "mission 2 isn't done"):
            generate.next_mission(self.root)

    def test_the_last_mission_ends_the_campaign_and_no_more_are_rolled(self):
        shutil.rmtree(self.pack)
        roll(self.pack, missions=1)
        write_up(self.pack)
        heart = packs.scene_text(packs.load_adventure(self.pack), "m1_heart")
        self.assertIn('"end"', heart)
        self.assertIn("nemesis", packs.load_adventure(self.pack)["scenes"]["m1_heart"]["npcs"])
        with self.session() as c:
            c.commit({"facts": {"mission_1.done": True}})
        with self.assertRaisesRegex(SoloError, "all 1 missions"):
            generate.next_mission(self.root)


class Chapters(Folder):
    def pack(self, chapters):
        root = self.tmp / "pack"
        (root / "scenes").mkdir(parents=True)
        (root / "chapters").mkdir()
        (root / "adventure.toml").write_text(
            'title = "Chapters"\nstart = "hub"\n[clocks.dusk]\nsegments = 2\n'
            '[scenes.hub]\ntitle = "Hub"\nexits = { yard = "The yard" }\n'
            '[[scenes.hub.branches]]\nwhen = "not fact.never"\ntext = "Always."\n'
            '[scenes.yard]\ntitle = "Yard"\nexits = { hub = "Back" }\n', encoding="utf-8")
        for name, text in chapters.items():
            (root / "chapters" / name).write_text(text, encoding="utf-8")
        for sid in ("hub", "yard", "cave", "deep"):
            (root / "scenes" / f"{sid}.md").write_text(f"The {sid}.\n", encoding="utf-8")
        return root

    def test_chapters_add_scenes_and_to_scenes_in_order(self):
        root = self.pack({
            "part_10.toml": '[scenes.deep]\ntitle = "Deep"\nexits = { cave = "Up" }\n',
            "part_2.toml": ('[scenes.hub.exits.cave]\nlabel = "The cave"\nwhen = "fact.cave.found"\n'
                            '[[scenes.hub.branches]]\nwhen = "not fact.never"\ntext = "The cave is open."\n'
                            '[scenes.cave]\ntitle = "Cave"\nexits = { hub = "Out", deep = "Down" }\n[factions.bats]\nname = "Bats"\n'),
        })
        adventure = packs.load_adventure(root)
        self.assertEqual(adventure["chapters"], ["part_2", "part_10"])
        self.assertEqual(set(adventure["scenes"]["hub"]["exits"]), {"yard", "cave"})
        self.assertEqual([b["text"] for b in adventure["scenes"]["hub"]["branches"]], ["Always.", "The cave is open."])
        self.assertIn("bats", adventure["factions"])
        self.assertEqual(packs.validate(packs.load_system(DRAGONBANE), adventure), [])
        self.assertIn("Chapters: part_2, part_10.", packs.outline(adventure))

    def test_an_id_defined_twice_or_a_stray_key_is_a_problem(self):
        root = self.pack({"a.toml": '[clocks.dusk]\nsegments = 3\n', "b.toml": 'title = "Other"\n'})
        problems = packs.validate(packs.load_system(DRAGONBANE), packs.load_adventure(root))
        self.assertIn("chapters/a.toml: clock dusk is already defined in adventure.toml", problems)
        self.assertTrue(any(p.startswith("chapters/b.toml: a chapter holds only") for p in problems))

    def test_a_draft_chapter_is_the_authors_until_its_mark_comes_off(self):
        root = self.pack({"a.toml": 'draft = true\n[scenes.cave]\ntitle = "Cave"\nexits = { hub = "Out" }\n'})
        self.assertIn("cave", packs.load_adventure(root)["scenes"])
        self.assertNotIn("cave", packs.load_adventure(root, drafts=False)["scenes"])


class Commands(Folder):
    def setUp(self):
        super().setUp()
        patch = unittest.mock.patch.dict("os.environ", {"SOLO_HOME": str(self.tmp / "home"), "XDG_STATE_HOME": str(self.tmp / "state")})
        patch.start()
        self.addCleanup(patch.stop)
        install_rules(self.tmp / "home")

    def solo(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = cli.main(list(argv))
        return status, out.getvalue() + err.getvalue()

    def test_new_check_and_the_library(self):
        status, out = self.solo("campaign", "new", "salt", "--premise", PREMISE, "--tone", "grim", "--seed", str(SEED))
        self.assertEqual(status, 0, out)
        pack = self.tmp / "home" / "adventures" / "salt"
        self.assertIn(f"seed {SEED}", out)
        self.assertTrue((pack / generate.ROLLS).exists())
        # A draft isn't offered, and says why.
        listing = library.listing()
        self.assertNotIn("salt", [a["id"] for a in listing["adventures"]])
        self.assertIn("adventure salt: still being written (draft = true in adventure.toml)", listing["problems"])
        status, out = self.solo("new", "salt", "--character", str(RAGNA))
        self.assertEqual(status, 1)
        self.assertIn("still being written", out)
        status, out = self.solo("campaign", "check", "salt")
        self.assertEqual(status, 1)
        self.assertIn("still as rolled", out)
        self.assertEqual(self.solo("validate", "--adventure", "salt")[0], 0)
        write_up(pack)
        status, out = self.solo("campaign", "check", "salt")
        self.assertEqual(status, 0, out)
        self.assertIn("1 of 3 missions written", out)
        self.assertIn("salt", [a["id"] for a in library.listing()["adventures"]])
        status, out = self.solo("campaign", "roll", "salt", "1d6", "--for", "how many lights are lit")
        self.assertEqual(status, 0, out)
        self.assertRegex(out, r'source = "rolled: #\d+"')

    def test_next_needs_a_generated_campaign(self):
        status, out = self.solo("new", str(library.REPO / "examples" / "red-tusk"), "--character", str(RAGNA), "--dir", str(self.tmp / "game"))
        self.assertEqual(status, 0, out)
        status, out = self.solo("campaign", "next", str(self.tmp / "game"))
        self.assertEqual(status, 1)
        self.assertIn("wasn't generated", out)
