"""The Book of Magic's importer on a made-up book with its bookmarks: new schools as skills, how a mage starts in each, spells by rank, tricks, recipes and
ingredients (invented things, the shapes and phrases of the real pages)."""

import os
import tempfile
import tomllib
import unittest
import unittest.mock
from pathlib import Path

from fake_book import FakeBook, Flow

from solo import audit
from solo.books import dragonbane_magic
from solo.books.pack import Pack
from solo.sections import Book


class BookOfMagicTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        # The audit loads the pack with what it extends: a player's rulebook pack, here a
        # stand-in over the bundled names, so the test doesn't lean on ~/Games/solo.
        rulebook = self.tmp / "home" / "systems" / "dragonbane-rulebook"
        rulebook.mkdir(parents=True)
        (rulebook / "system.toml").write_text('extends = "bundled:dragonbane"\n')
        home = unittest.mock.patch.dict(os.environ, {"SOLO_HOME": str(self.tmp / "home")})
        home.start()
        self.addCleanup(home.stop)
        flow = Flow(FakeBook(self.tmp / "extract"))
        flow.section(1, "Contents", "Everything in order.")
        flow.section(1, "Preface", "About this book.")
        flow.section(2, "New Schools of Magic", "Every new school is a secondary skill, secondary skills based on INT as the first three are; harmonism isn’t a skill in itself, "
                     "it uses the skill level in PERFORMANCE.")
        flow.section(1, "1. General Magic", "Anyone may learn these.")
        flow.section(2, "Spells", "The spells.")
        flow.section(3, "Rank 1", "Rank one.")
        flow.section(4, "Hush", "✦Rank: 1", "✦Prerequisite: Any school of magic", "✦Requirement: Word, gesture", "✦Casting Time: Action/stretch", "✦Range: 10 meters", "✦Duration: Instant", "You make no sound.")
        flow.section(1, "2. Animism", "The school of the wild.")
        flow.section(2, "Preamble", "How animists live.")
        flow.section(3, "Sidebar: Starting Skills", "Good picks for newly created animists, who may be chosen as the 6 trained skills (see the rulebook): "
                     "Animism, Beast Lore, Evade, Healing, Hunting & Fishing, Staves.")
        flow.section(3, "Magic Tricks", "Hum: You hum a tune.", "", "Glow: Your hands glow.")
        flow.section(2, "Spells", "The spells.")
        flow.section(3, "Rank 1", "Rank one.")
        flow.section(4, "Zap", "✦Rank: 1", "✦Prerequisite: Animism", "✦Requirement: Gesture", "✦Casting Time: Action", "✦Range: 30 meters", "✦Duration: Instant",
                     "A bolt strikes the target, who takes 2D6 damage. Each level raises the dice rolled for damage by one.")
        flow.section(1, "5. Harmonism", "Music as magic.")
        flow.section(2, "Spells", "The spells.")
        flow.section(3, "Rank 1", "Rank one.")
        flow.section(4, "Soothing Song", "✦Rank: 1", "✦Prerequisite: Harmonism", "✦Requirement: Melody", "✦Casting Time: Action", "✦Range: 20 meters", "✦Duration: Stretch", "It calms.")
        flow.section(1, "10. Witchcraft", "Hexes.")
        flow.section(2, "Preamble", "Witches.")
        flow.section(3, "Sidebar: Starting Skills", "Good picks for newly created witches, who may be chosen as the 6 trained skills (see the rulebook): "
                     "Witchcraft, Awareness, Healing, Sneaking.")
        flow.section(1, "11. Alchemy", "Brews.")
        flow.section(2, "Preamble", "Alchemists.")
        flow.section(3, "Sidebar: Magic Tricks", "Unlike most other schools of magic, alchemy has no magic tricks.")
        flow.table(["INGREDIENT", "COST PER DOSE", "SUPPLY"], [["Iron Filings", "1 silver", "Common"], ["Nymph Tears", "3 gold", "Rare"]], [68, 150, 250])
        flow.section(2, "Recipes", "The recipes.")
        flow.section(3, "Rank 1", "Rank one.")
        flow.section(4, "Focus Tonic", "✦Rank: 1", "✦Prerequisite: Alchemy", "✦Ingredients: General herbs, wolf blood", "✦Cost: 5 gold (rare)", "Cures the Dazed condition.")
        flow.section(1, "13. Dracomancy", "The dragons’ art.")
        flow.section(2, "Spells", "The spells.")
        flow.section(3, "Astral Form", "✦Rank: 6", "✦Prerequisite: Any rank 5 spell", "✦Requirement: Word", "✦Casting Time: Action", "✦Range: Personal", "✦Duration: Shift", "You leave your body.")
        flow.section(1, "Index of Spells, Recipies, and Magic Tricks", "Zap 22.")
        flow.made.save()
        self.book = Book(self.tmp / "extract")
        self.pack = Pack(self.book, self.tmp / "out", dragonbane_magic.NAME, ["dragonbane-rulebook"])
        dragonbane_magic.build(self.pack)

    def spell(self, spell_id):
        return tomllib.loads(self.pack.files[f"spells/{spell_id}.toml"])

    def test_each_school_but_general_magic_is_a_skill_nobody_can_try_untrained_and_harmonism_is_rolled_as_performance(self):
        skills = self.pack.system["skills"]
        self.assertEqual(skills["animism"], {"attribute": "int", "untrained": False})
        self.assertEqual(skills["harmonism"], {"attribute": "cha", "untrained": False, "uses": "performance"})
        self.assertEqual(list(skills), ["animism", "harmonism", "witchcraft", "alchemy", "dracomancy"])

    def test_a_mage_may_start_in_a_school_that_lists_skills_suited_to_it_and_in_no_other(self):
        options = self.pack.creation["choose"]["school"]["options"]
        self.assertEqual(options["animist"], {"label": "Animism", "always": ["Animism"], "skills": ["Animism", "Beast Lore", "Evade", "Healing", "Hunting & Fishing", "Staves"], "train": 6})
        self.assertEqual((list(options), options["witch"]["label"]), (["animist", "witch"], "Witchcraft"))

    def test_spells_are_read_as_the_core_ones_are_and_a_page_names_only_what_it_has(self):
        self.assertEqual(self.spell("zap")["damage"], "2d6")
        self.assertEqual(self.spell("zap")["school"], "animism")
        hush = self.spell("hush")
        self.assertEqual((hush["school"], hush["casting_time"], "prerequisite" in hush), ("general", "action/stretch", False))
        astral = self.spell("astral_form")
        self.assertEqual((astral["rank"], "prerequisite" in astral, astral["range"]), (6, False, "personal"))
        self.assertEqual(self.spell("soothing_song")["requirement"], ["melody"])
        self.assertEqual(self.spell("soothing_song")["prerequisite"], ["harmonism"])

    def test_the_tricks_of_a_school_are_its_list_of_name_and_what_it_does_and_a_recipe_has_ingredients_and_a_price(self):
        self.assertEqual(self.spell("hum"), {"name": "Hum", "school": "animism", "trick": True, "rank": 0, "source": "p. 1"})
        self.assertEqual(self.spell("glow")["trick"], True)
        self.assertEqual(self.spell("focus_tonic"), {"name": "Focus Tonic", "school": "alchemy", "rank": 1, "prerequisite": ["alchemy"], "ingredients": "General herbs, wolf blood",
                                                      "cost": "5 gold (rare)", "source": self.spell("focus_tonic")["source"]})
        self.assertEqual(self.pack.items["spells_animism"]["to"], ["spells/hum", "spells/glow", "spells/zap"])

    def test_the_alchemists_ingredients_are_gear_with_a_price_a_dose(self):
        gear = self.pack.gear["gear"]
        self.assertEqual(gear["nymph_tears"]["price"], "3 gold")
        self.assertEqual((gear["iron_filings"]["supply"], gear["iron_filings"]["note"], gear["iron_filings"]["category"]), ("common", "Price per dose.", "Alchemical ingredients"))

    def test_the_audit_finds_what_the_pack_wrote_claimed(self):
        self.pack.write(self.tmp / "extract")
        report = audit.audit(self.tmp / "out", "system")
        self.assertEqual(report["unclaimed"], [])
        self.assertEqual(report["problems"], [])


class LeftOutTest(unittest.TestCase):
    """What the importer can't read of a school it leaves out, and its notes say what and where."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        flow = Flow(FakeBook(Path(folder.name) / "extract"))
        flow.section(1, "2. Animism", "The school of the wild.")
        flow.section(2, "Preamble", "How animists live.")
        flow.section(3, "Sidebar: Starting Skills", "Animists learn by doing, and pick their skills as they go.")
        flow.section(3, "Magic Tricks", "Hum: You hum a tune.", "", "The chart of the school's spells is on the next page.")
        flow.section(1, "11. Alchemy", "Brews.")
        flow.section(2, "Preamble", "Alchemists.")
        flow.made.save()
        self.book = Book(Path(folder.name) / "extract")
        self.pack = Pack(self.book, Path(folder.name) / "out", dragonbane_magic.NAME)

    def test_tricks_read_up_to_a_paragraph_that_isnt_one_say_where_they_stop(self):
        self.assertEqual(dragonbane_magic.spells._tricks(self.pack, self.book.find("2. Animism")), [("Hum", 1)])
        self.assertEqual(self.pack.notes, ["Animism, magic tricks (p. 1): read up to a paragraph that isn't a trick's \"Name: what it does\" "
                                           "(The chart of the school's spells ...); the rest of the section isn't read as tricks"])

    def test_a_starting_sidebar_it_cant_read_and_ingredients_it_cant_find_are_said(self):
        self.assertIsNone(dragonbane_magic.system._start(self.pack, self.book.find("2. Animism"), "animism"))
        self.assertIsNone(dragonbane_magic.system._ingredients(self.pack, self.book.find("11. Alchemy")))
        self.assertEqual(self.pack.notes, [
            "Animism, 'Sidebar: Starting Skills' (p. 1): can't read which skills a new mage of the school starts with, so a hero can't start in it",
            "Alchemy: no table of ingredients where the importer looks for it (a sidebar on magic tricks), so they aren't gear"])


if __name__ == "__main__":
    unittest.main()
