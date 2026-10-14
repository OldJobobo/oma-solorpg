"""Chapter 2 of a made-up book (its bookmarks, the shapes its tables are set in and the phrases the recipe reads, invented things
throughout) read into creation.toml."""

import tempfile
import unittest
from pathlib import Path

from fake_book import BANNER, CELL, HEADER, HEADING, LABEL, FakeBook

from solo import audit
from solo.books import dragonbane_core
from solo.books.dragonbane_core import creation
from solo.books.pack import Pack
from solo.sections import Book

# The weapons and armor a pack knows, as the gear recipe leaves them: what a kit's words are matched to.
KNOWN = {"lightmace": "light_mace", "sabre": "sabre", "pike": "pike", "dirk": "dirk", "scalearmor": "scale_armor"}


class KitsTest(unittest.TestCase):
    def test_a_choice_is_a_kit_each_and_a_set_with_none_repeats_so_every_set_comes_up_as_often(self):
        kits, gear = creation._kits([
            "Mace (light), scale armor, forge tools, torch, rope (hemp), D6 food rations, D4 silver",
            "Sabre/pike, scale armor, joiner tools, torch, D6 food rations, D4 silver",
            "Two dirks, scale armor, dyer tools, lantern, D6 food rations, D4 silver"], KNOWN)
        one, two, three = ["Light mace", "Forge tools", "Torch", "Rope (hemp)"], ["Joiner tools", "Torch"], ["Dirk", "Dirk", "Dyer tools", "Lantern"]
        self.assertEqual(kits, [one, one, ["Sabre", *two], ["Pike", *two], three, three])
        self.assertEqual(gear, ["Scale armor", "{1d6} food rations", "{1d4} silver"])

    def test_sets_with_the_same_number_of_choices_are_not_repeated(self):
        kits, gear = creation._kits(["Sabre, torch", "Pike, torch", "Dirk, torch"], KNOWN)
        self.assertEqual((kits, gear), ([["Sabre"], ["Pike"], ["Dirk"]], ["Torch"]))

    def test_words_are_the_pack_entrys_when_there_is_one_and_the_books_when_there_is_not(self):
        self.assertEqual([creation._item(text, KNOWN) for text in ("mace (light)", "Light mace", "rope (hemp)", "D8 food rations", "2D6 silver")],
                         [["Light mace"], ["Light mace"], ["Rope (hemp)"], ["{1d8} food rations"], ["{2d6} silver"]])


def names(made, page, y, six):
    """Six names in two halves side by side, D6 FIRST NAME over each."""
    made.line(page, y, "D6 FIRST NAME", 68, HEADER)
    banner_at = made.outline[-1]
    made.outline.append({**banner_at, "title": "Table: First Name", "level": 4, "y": y - 1})
    made.line(page, y, "D6 FIRST NAME", 194, HEADER)
    for row in range(3):
        made.line(page, y + 17 + 17 * row, str(row + 1), 72, CELL)
        made.line(page, y + 17 + 17 * row, six[row], 85, CELL)
        made.line(page, y + 17 + 17 * row, str(row + 4), 197, CELL)
        made.line(page, y + 17 + 17 * row, six[row + 3], 211, CELL)


def profession(made, page, title, bullets, sets):
    y = made.section(page, 80, 3, title, "A sentence about what a " + title.lower() + " does.")
    made.line(page, y, bullets[0], 64, LABEL)
    made.lines(page, y + 12, *bullets[1:], x=64)
    made.banner(page, 300, 4, "Table: Gear")
    made.line(page, 320, "D6", 318, HEADER)
    made.line(page, 320, "GEAR", 343, HEADER)
    for number, (roll, text) in enumerate(sets):
        made.line(page, 340 + 30 * number, f"{roll} {text[0]}", 320, CELL)
        made.line(page, 352 + 30 * number, text[1], 343, CELL)


class CreationRecipeTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        made = FakeBook(self.tmp / "extract")
        y = made.section(1, 80, 1, "2. Your Player Character", "A hero is made in steps.")
        y = made.section(1, y, 2, "Attributes", "Six attributes measure a hero, on a scale from 3 to 18.")
        y = made.section(1, y, 3, "Starting Scores", "Roll 4D6 and remove the worst die for each one. Once done you may swap two scores.")
        y = made.section(1, y, 2, "Skills", "Skills are trained or not.")
        made.section(1, y, 3, "Starting Skill Levels", "A trained skill starts out equal to twice the base chance. 6 of your trained skills must be selected, "
                                                          "the profession names which. The rest are free.")
        y = made.section(2, 80, 2, "Derived Ratings", "Ratings follow from the attributes.")
        y = made.section(2, y, 3, "Hit Points (HP)", "Total HP is equal to your CON, always.")
        made.section(2, y, 3, "Willpower Points (WP)", "Total WP is equal to your WIL, always.")
        made.line(3, 80, "MOVEMENT", 62, HEADING)
        made.mark(3, "Movement")
        made.lines(3, 100, "The kin sets the pace and AGL changes it.")
        made.banner(3, 130, 4, "Table: Movement")
        made.table(3, 150, ["KIN", "MOVEMENT"], [["Fox", "9"], ["Owl", "7"], ["AGL 1–6", "–3"], ["AGL 7–9", "–1"], ["AGL 13–15", "+1"]], [128, 200])
        made.line(3, 300, "DAMAGE BONUS", 62, HEADING)
        made.mark(3, "Damage Bonus")
        made.lines(3, 320, "STR and AGL each give one.")
        made.banner(3, 350, 4, "Table: Damage Bonus")
        made.table(3, 370, ["STR/AGL", "DAMAGE BONUS"], [["≤12", "—"], ["13–16", "+D4"], ["17+", "+D6"]], [128, 200])
        y = made.section(4, 80, 2, "Kin", "Two kin are playable.")
        y = made.section(4, y, 3, "Introduction", "Roll for a kin or choose one.")
        made.banner(4, y, 4, "Table: Kin")
        made.roll_table(4, y + 20, ["D4", "KIN"], [["1–2", "Fox"], ["3–4", "Owl"]], [145, 172])
        made.section(5, 80, 3, "Fox", "Foxes are quick.")
        names(made, 5, 130, ["Ash", "Bram", "Cole", "Dell", "Emry", "Flint"])
        made.section(5, 250, 4, "Ability: Bolt", "You may run at once.")
        made.section(6, 80, 3, "Owl", "Owls are wise.")
        names(made, 6, 130, ["Gale", "Hob", "Ivo", "Jet", "Kip", "Lark"])
        y = made.section(6, 250, 4, "Ability: Hoot", "You may call for help.")
        made.section(6, y, 4, "Ability: Glide", "You may fall slowly.")
        y = made.section(7, 80, 2, "Profession", "Choose what the hero did before.")
        y = made.section(7, y, 3, "Introduction", "Roll for one or choose.")
        made.banner(7, y, 4, "Table: Profession")
        made.roll_table(7, y + 20, ["D3", "PROFESSION"], [["1", "Smith"], ["2", "Seer"], ["3", "Scout"]], [344, 360])
        profession(made, 8, "Smith", ["✦Key Attribute: STR", "✦Skills: Axes, Crafting, Hammers, Knives, Swords, Brawling, Evade, Bows",
                                      "✦Heroic Ability: Master Forger, Master Joiner or Master Dyer"],
                   [("1–2", ("Mace (light), scale armor, forge tools, torch,", "rope (hemp), D6 food rations, D4 silver")),
                    ("3–4", ("Sabre/pike, scale armor, joiner tools, torch,", "D6 food rations, D4 silver")),
                    ("5–6", ("Two dirks, scale armor, dyer tools, lantern,", "D6 food rations, D4 silver"))])
        profession(made, 9, "Seer", ["✦Key Attribute: WIL", "✦Fire Skills: Pyro, Evade, Healing", "✦Wind Skills: Aero, Evade, Healing",
                                     "✦Heroic Ability: Seers don’t get a starting heroic ability here."],
                   [("1–2", ("Staff, grimoire, torch,", "D6 food rations")), ("3–4", ("Wand, grimoire, torch,", "D6 food rations")),
                    ("5–6", ("Orb, grimoire, torch,", "D6 food rations"))])
        made.section(9, 500, 4, "Sidebar: Magic", "A newly created mage may choose 3 rank 1 spells and 3 magic tricks.")
        profession(made, 10, "Scout", ["✦Key Attribute: AGL", "✦Skills: Bows, Evade, Knives, Sneaking, Bushcraft, Awareness, Healing, Swimming",
                                       "✦Heroic Ability: Tracker"],
                   [("1–2", ("Sabre, torch,", "D6 food rations")), ("3–4", ("Dirk, torch,", "D6 food rations")), ("5–6", ("Pike, torch,", "D6 food rations"))])
        y = made.section(11, 80, 2, "Age", "A hero is young, adult or old.")
        made.banner(11, y, 3, "Table: Effects of Age")
        made.roll_table(11, y + 20, ["D6", "AGE", "TRAINED SKILLS*", "ATTRIBUTES†"],
                   [["1–3", "Young", "6+2", "AGL and CON +1"], ["4–5", "Adult", "6+4", "—"], ["6", "Old", "6+6", "STR, AGL, and CON –2, INT and WIL +1"]], [122, 188, 271, 339])
        made.save(pages=True)
        self.book = Book(self.tmp / "extract")
        self.pack = Pack(self.book, self.tmp / "out", dragonbane_core.NAME, dragonbane_core.extends(None))
        self.pack.system["weapons"] = {"light_mace": {}, "sabre": {}, "pike": {}, "dirk": {}}
        self.pack.system["armor"] = {"scale_armor": 4}
        creation.build(self.pack)
        self.creation = self.pack.creation

    def test_the_attributes_are_rolled_as_the_book_says_and_a_score_may_be_swapped(self):
        self.assertEqual({key: self.creation[key] for key in ("attributes", "attribute_range", "key_swap", "trained_multiplier", "tracks")},
                         {"attributes": "4d6kh3", "attribute_range": [3, 18], "key_swap": True, "trained_multiplier": 2, "tracks": {"hp": "con", "wp": "wil"}})

    def test_movement_steps_fill_the_range_the_book_leaves_out_with_no_change(self):
        ratings = self.creation["ratings"]
        self.assertEqual(ratings["movement"], {"label": "Movement", "attribute": "agl", "table": [[6, -3], [9, -1], [12, 0], [15, 1]]})
        self.assertEqual(ratings["damage_bonus_str"], {"label": "Damage bonus (STR)", "attribute": "str", "table": [[12, "none"], [16, "+D4"], [18, "+D6"]]})
        self.assertEqual(ratings["damage_bonus_agl"]["attribute"], "agl")

    def test_a_kin_has_its_range_its_abilities_its_movement_and_its_six_names(self):
        kin = self.creation["choose"]["kin"]
        self.assertEqual((kin["roll"], kin["options"]["fox"]), ("1d4", {"range": [1, 2], "abilities": ["Bolt"], "ratings": {"movement": 9},
                                                                       "names": ["Ash", "Bram", "Cole", "Dell", "Emry", "Flint"]}))
        self.assertEqual(kin["options"]["owl"]["abilities"], ["Hoot", "Glide"])
        self.assertEqual((kin["options"]["owl"]["range"], kin["options"]["owl"]["ratings"], kin["options"]["owl"]["names"][3:]), ([3, 4], {"movement": 7}, ["Jet", "Kip", "Lark"]))

    def test_a_profession_has_its_key_attribute_skills_ability_and_kits(self):
        choose = self.creation["choose"]
        smith = choose["profession"]["options"]["smith"]
        self.assertEqual(choose["profession"]["roll"], "1d3")
        self.assertEqual({key: smith[key] for key in ("range", "key", "skills", "train", "then", "gear")},
                         {"range": [1, 1], "key": "str", "skills": ["Axes", "Crafting", "Hammers", "Knives", "Swords", "Brawling", "Evade", "Bows"], "train": 6,
                          "then": "craft", "gear": ["Scale armor", "{1d6} food rations", "{1d4} silver"]})
        self.assertEqual(len(smith["kits"]), 6)
        self.assertNotIn("abilities", smith)
        scout = choose["profession"]["options"]["scout"]
        self.assertEqual((scout["abilities"], scout["key"], "then" in scout, scout["kits"]), (["Tracker"], "agl", False, [["Sabre"], ["Dirk"], ["Pike"]]))

    def test_a_choice_of_heroic_abilities_is_a_follow_up_choice_to_make(self):
        self.assertEqual(self.creation["choose"]["craft"], {"label": "Craft", "options": {
            "forger": {"label": "Forger", "abilities": ["Master Forger"]}, "joiner": {"label": "Joiner", "abilities": ["Master Joiner"]},
            "dyer": {"label": "Dyer", "abilities": ["Master Dyer"]}}})

    def test_a_profession_with_magic_has_no_heroic_ability_and_a_school_for_each_list_of_skills(self):
        seer = self.creation["choose"]["profession"]["options"]["seer"]
        self.assertEqual((seer["then"], "abilities" in seer, "skills" in seer, seer["key"]), ("school", False, False, "wil"))
        self.assertEqual(seer["spells"], {"count": 3, "rank": 1, "tricks": 3})
        self.assertEqual(self.creation["choose"]["school"]["options"]["fire"], {"label": "Pyro", "always": ["Pyro"], "skills": ["Pyro", "Evade", "Healing"], "train": 6})
        self.assertEqual(list(self.creation["choose"]["school"]["options"]), ["fire", "wind"])

    def test_an_age_changes_the_attributes_and_says_how_many_skills_are_free(self):
        age = self.creation["choose"]["age"]
        self.assertEqual((age["roll"], age["options"]["young"], age["options"]["adult"]),
                         ("1d6", {"range": [1, 3], "attributes": {"agl": 1, "con": 1}, "extra": 2}, {"range": [4, 5], "extra": 4}))
        self.assertEqual(age["options"]["old"], {"range": [6, 6], "attributes": {"str": -2, "agl": -2, "con": -2, "int": 1, "wil": 1}, "extra": 6})

    def test_the_pack_claims_what_it_wrote_and_the_audit_finds_it_so(self):
        self.pack.write(self.tmp / "extract")
        report = audit.audit(self.tmp / "out", "system")
        # The weapons and armor stand in for what the gear recipe writes: they are not this recipe's to claim.
        self.assertEqual([unit for unit in report["unclaimed"] if unit.startswith("creation.toml")], [])
        self.assertEqual(report["problems"], [])
        # Each number is on the pages its item cites: a kin's movement is the movement table's, a profession's six skills the skills' section's.
        self.assertEqual(report["unverified"], [])


if __name__ == "__main__":
    unittest.main()
