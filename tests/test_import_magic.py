"""Heroic abilities and spells read from a made-up book: the lines under each title and the words that say what the engine can run of them
(invented things, the shapes and phrases of the real pages)."""

import tempfile
import tomllib
import unittest
from pathlib import Path

from fake_book import FakeBook, Flow

from solo import audit
from solo.books import dragonbane_core
from solo.books.dragonbane_core import abilities, spells
from solo.books.pack import Pack
from solo.sections import Book


class MagicRecipeTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        flow = Flow(FakeBook(self.tmp / "extract"))
        flow.section(1, "3. Skills", "Skills are trained.")
        flow.section(2, "The Core Skills", "Thirty of them.")
        for skill in ("Knives", "Swimming", "Evade"):
            flow.section(3, skill, f"{skill} is a skill.")
        flow.section(2, "Heroic Abilities", "Abilities are heroic.")
        flow.section(3, "Sharpshot", "✦Requirement: Knives 12", "✦Willpower Points: 3", "Your sneak attack (page 43) deals an extra D8 damage. Say so after the roll.")
        flow.section(3, "Hardy", "✦Requirement: —", "✦Willpower Points: —", "Your max HP increases by 2. Take it again and again: multiple times, without limit.")
        flow.section(3, "Deep Mind", "✦Requirement: —", "✦Willpower Points: —", "The maximum number of Willpower Points is for good increased by 2. Take it "
                     "multiple times, without limit.")
        flow.section(3, "Quick Draw", "✦Requirement: Evade 12", "✦Willpower Points: 2", "At the start of a round draw two cards instead of one, then pick.")
        flow.section(3, "Brawny", "✦Requirement: Any STR-based melee weapon skill 12", "✦Willpower Points: 3",
                     "Swing a heavy weapon in both hands: it inflicts D8 additional points of damage, standing still.")
        flow.section(3, "Swimmer", "✦Requirement: Swim 12", "✦Willpower Points: Varies", "You are safe in water for one round.")
        flow.section(3, "Steady Hand", "✦Requirement: Any melee weapon skill 12", "✦Willpower Points: 3",
                     "Any round you may attempt to parry an attack that comes, without consuming your action.")
        flow.section(3, "Healer", "✦Requirement: Axes, Hammers, or Swords 12", "✦Willpower Points: 2", "Rest well and heal an extra D6 HP when you take a stretch rest.")
        flow.section(1, "5. Magic", "Magic is cast.")
        flow.section(2, "Spell List", "The spells.")
        flow.section(3, "General Magic", "Anyone may learn these.")
        flow.section(4, "Hush", "✦Rank: 1", "✦Prerequisite: Any School of Magic", "✦Requirement: Word, gesture", "✦Casting Time: Reaction", "✦Range: Touch", "✦Duration: Instant",
                     "You make no sound.")
        flow.section(3, "Animism", "Animists hear the world.")
        flow.section(4, "Magic Tricks", "The tricks.")
        flow.section(5, "Hum", "Hum: You hum a tune.")
        flow.section(5, "Glow", "Glow: Your hands glow.")
        flow.section(4, "Zap", "✦Rank: 1", "✦Prerequisite: Animism", "✦Requirement: Gesture", "✦Casting Time: Action", "✦Range: 30 meters", "✦Duration: Instant",
                     "A bolt strikes the target, who takes 2D6 damage. The bolt continues to another random target within 2 meters, inflicting 2D4 damage. Each power level "
                     "beyond the first raises the dice rolled for damage by one. The bolt can be dodged or parried.")
        flow.section(4, "Soothe", "✦Rank: 2", "✦Prerequisite: ZAP or HEAL", "✦Requirement: Word, gesture, ingredient (a petal)", "✦Casting Time: Stretch", "✦Range: 10 meters (sphere)",
                     "✦Duration: Shift", "It heals a living creature for 2D6 HP. Each level beyond the first heals an additional D6 HP.")
        flow.section(4, "Flare", "✦Rank: 3", "✦Prerequisite: ZAP and SOOTHE", "✦Requirement: Word", "✦Casting Time: Action", "✦Range: 1 kilometer", "✦Duration: Concentration",
                     "A flare inflicts 2D8 damage on a demon. Each extra level increases the damage by D8, nothing more. Armor and natural armor have no effect here; nothing dodges it.")
        flow.made.save(pages=True)
        self.book = Book(self.tmp / "extract")
        self.pack = Pack(self.book, self.tmp / "out", dragonbane_core.NAME, dragonbane_core.extends(None))
        abilities.build(self.pack)
        spells.build(self.pack)

    def spell(self, spell_id):
        return tomllib.loads(self.pack.files[f"spells/{spell_id}.toml"])

    def test_an_ability_has_what_it_costs_and_the_skill_level_it_asks_for(self):
        found = self.pack.system["abilities"]
        self.assertEqual(found["sharpshot"], {"name": "Sharpshot", "pay": {"wp": 3}, "requires": {"skills": ["knives"], "level": 12}, "extra_damage": "1d8"})
        self.assertEqual(found["hardy"], {"name": "Hardy", "max": {"hp": 2}, "stack": True})
        self.assertEqual(found["swimmer"], {"name": "Swimmer", "pay": "varies", "requires": {"skills": ["swimming"], "level": 12}})
        self.assertEqual(found["healer"]["requires"], {"skills": ["axes", "hammers", "swords"], "level": 12})

    def test_the_words_of_a_group_of_skills_are_the_engines_kinds_of_them(self):
        found = self.pack.system["abilities"]
        self.assertEqual((found["brawny"]["requires"], found["steady_hand"]["requires"]), ({"kind": "str_melee", "level": 12}, {"kind": "melee", "level": 12}))

    def test_what_the_engine_runs_of_an_ability_is_read_from_the_words_the_book_uses(self):
        found = self.pack.system["abilities"]
        self.assertEqual({key: found["deep_mind"][key] for key in ("max", "stack")}, {"max": {"wp": 2}, "stack": True})
        self.assertEqual(found["quick_draw"]["initiative_pick"], 2)
        self.assertEqual({key: found["brawny"][key] for key in ("extra_damage", "grip", "melee")}, {"extra_damage": "1d8", "grip": 2, "melee": True})
        self.assertEqual(found["steady_hand"]["reaction"], "parry")
        self.assertEqual({key: found["healer"].get(key) for key in ("heal", "rest")}, {"heal": "1d6", "rest": "stretch"})

    def test_a_spell_has_its_lines_and_an_or_in_its_prerequisite_is_a_list_of_either(self):
        zap, soothe, flare = self.spell("zap"), self.spell("soothe"), self.spell("flare")
        self.assertEqual({key: zap[key] for key in ("school", "rank", "prerequisite", "requirement", "casting_time", "range", "duration", "source")},
                         {"school": "animism", "rank": 1, "prerequisite": ["animism"], "requirement": ["gesture"], "casting_time": "action", "range": 30, "duration": "instant", "source": "p. 2"})
        self.assertEqual((soothe["prerequisite"], soothe["requirement"], soothe["range"], soothe["area"]), ([["zap", "heal"]], ["word", "gesture", "ingredient"], 10, "sphere"))
        self.assertEqual((flare["prerequisite"], flare["range"], flare["duration"]), (["zap", "soothe"], 1000, "concentration"))
        self.assertNotIn("prerequisite", self.spell("hush"))
        self.assertEqual(self.spell("hush")["school"], "general")

    def test_what_a_spell_does_is_read_from_the_words_the_book_uses_for_it(self):
        zap, soothe, flare = self.spell("zap"), self.spell("soothe"), self.spell("flare")
        self.assertEqual({key: zap[key] for key in ("damage", "chain", "per_level", "avoid", "kind")},
                         {"damage": "2d6", "chain": ["2d4"], "per_level": {"dice": 1}, "avoid": ["dodge", "parry"], "kind": "magic"})
        self.assertEqual({key: soothe.get(key) for key in ("heal", "per_level", "damage")}, {"heal": "2d6", "per_level": {"add": "1d6"}, "damage": None})
        self.assertEqual({key: flare[key] for key in ("damage", "per_level", "avoid", "armor")}, {"damage": "2d8", "per_level": {"add": "1d8"}, "avoid": [], "armor": False})
        self.assertNotIn("damage", self.spell("hush"))

    def test_a_magic_trick_is_a_spell_of_rank_zero(self):
        self.assertEqual(self.spell("hum"), {"name": "Hum", "school": "animism", "trick": True, "rank": 0, "source": "p. 2"})
        self.assertEqual(self.pack.items["spells_animism"]["to"], ["spells/hum", "spells/glow", "spells/zap", "spells/soothe", "spells/flare"])

    def test_the_pack_says_where_they_went_and_the_audit_finds_them_claimed(self):
        self.pack.write(self.tmp / "extract")
        report = audit.audit(self.tmp / "out", "system")
        self.assertEqual(report["unclaimed"], [])
        self.assertEqual(report["problems"], [])
        # Read back against the made-up book's own pages, every table, number and word is on them.
        self.assertEqual(report["unverified"], [])


if __name__ == "__main__":
    unittest.main()
