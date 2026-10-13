"""Chapter 7 of a made-up book, and its table of typical NPCs (invented creatures, the shapes and phrases of the real pages), read into
bestiary/<id>.toml and the tables a monster's attacks are."""

import tempfile
import tomllib
import unittest
from pathlib import Path

from fake_book import CELL, HEADER, LABEL, FakeBook

from solo import SoloError, audit
from solo.books import dragonbane_core
from solo.books.dragonbane_core import bestiary
from solo.books.pack import Pack
from solo.sections import Book

TITLE = ("Hideout-Bold", 10.0, 2301728)


def entries(made, page, y, x, *texts):
    """Entries of a stat block: each begins at the margin and its next line is set in."""
    for text in texts:
        for number, line in enumerate(text):
            made.line(page, y, line, x if number == 0 else x + 14, CELL)
            y += 12
    return y


class BestiaryRecipeTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        made = FakeBook(self.tmp / "extract")
        made.section(1, 80, 1, "6. Gear", "Gear is sold.")
        made.banner(1, 140, 2, "Table: Melee Weapons")
        made.banner(1, 170, 2, "Table: Ranged Weapons")
        made.banner(1, 200, 2, "Table: Armor & Helmets")
        made.section(2, 80, 1, "7. Bestiary", "Monsters live here.")
        made.section(2, 140, 2, "Introduction", "Monsters have ferocity.")
        # A monster that is hurt by little, mends and carries a weapon.
        made.section(3, 80, 2, "Bogey", "Bogeys lurk under beds.")
        made.line(3, 140, "Ferocity: 2   Size: Large", 85, LABEL)
        made.mark(3, "Statblock")
        made.line(3, 157, "Movement: 12   Armor: Same as armor   HP: 30", 85, LABEL)
        entries(made, 3, 180, 80, ["Regeneration: A bogey recovers D6 HP", "on each of its turns."], ["Resistance: Takes half damage from", "weapons, except fire."],
                ["Typical Gear: Sabre, scale armor"])
        made.line(3, 260, "MONSTER ATTACKS", 250, TITLE)
        made.mark(3, "Monster Attacks")
        made.line(3, 280, "D6 ATTACK", 68, HEADER)
        rows = ["Howl! The bogey howls. All within 10 meters suffer a fear attack.",
                "Claw! The bogey rakes a player character. The attack inflicts 2D6 slashing damage. It can be parried.",
                "Hurl! The bogey throws a victim 2D4 meters. That is an equal amount of bludgeoning damage, and it cannot be dodged.",
                "Smash! The bogey swings its weapon. The attack inflicts weapon damage plus an extra D6. Armor has no effect.",
                "Double! The bogey strikes twice the weapon’s normal number of dice. It can be parried.",
                "Curse! The bogey chants. Roll D4:"]
        for number, text in enumerate(rows):
            made.line(3, 297 + 17 * number, str(number + 1), 72, CELL)
            made.line(3, 297 + 17 * number, text, 85, CELL)
        for number, text in enumerate(["Your hair falls out.", "You grow a tail.", "Your shadow leaves.", "You forget your name."]):
            made.line(3, 399 + 17 * number, str(number + 1), 94, CELL)
            made.line(3, 399 + 17 * number, text, 109, CELL)
        # A swarm with a limit per creature, immune to all but magic, healing by what it takes.
        made.section(4, 80, 2, "Wisp", "Wisps drift over marshes.")
        made.line(4, 140, "Ferocity: 1/wisp   Size: Swarm", 85, LABEL)
        made.mark(3, "Statblock")
        made.line(4, 157, "Movement: 20   Armor: —   HP: 9/wisp", 85, LABEL)
        entries(made, 4, 180, 80, ["Immunity: Wisps are immune to all damage except spells."])
        made.line(4, 260, "MONSTER ATTACKS", 250, TITLE)
        made.mark(3, "Monster Attacks")
        made.line(4, 280, "D2 ATTACK", 68, HEADER)
        for number, text in enumerate(["Drain! The wisp touches a victim. The attack inflicts D6 slashing damage and the wisp heals the same amount of HP.",
                                       "Drain again! The wisp clings to a victim, who suffers D4 points of damage and the wisp heals the same amount of HP."]):
            made.line(4, 297 + 17 * number, str(number + 1), 72, CELL)
            made.line(4, 297 + 17 * number, text, 85, CELL)
        # Folk who are not monsters: a stat block each and what the book says of all of them.
        made.section(5, 80, 2, "Gobs", "Gobs live in burrows.")
        made.line(5, 150, "SCOUT", 414, TITLE)
        made.mark(3, "Statblock: Scout")
        for text, x in (("Movement: 10", 337), ("Damage Bonus: —", 411), ("HP: 9", 504)):
            made.line(5, 185, text, x, LABEL)
        made.line(5, 203, "Typical Armor: Leather (1)", 337, LABEL)
        made.line(5, 220, "Skills: Evade 10, Sneaking 12", 337, CELL)
        made.line(5, 238, "Typical Weapons: Sabre (skill level 12, damage D10), dirk (skill level 10, damage D8)", 337, CELL)
        made.line(5, 303, "WARRIOR", 405, TITLE)
        made.mark(3, "Statblock: Warrior")
        made.line(5, 322, "Mov.: 10 Damage Bonus STR: +D4 HP: 12", 337, LABEL)
        made.line(5, 339, "Typical Armor: —", 337, CELL)
        made.line(5, 357, "Skills: Evade 8", 337, CELL)
        made.line(5, 374, "Typical Weapon: Dirk (skill level 12, damage D8)", 337, CELL)
        made.line(5, 440, "Non-Monster: Gobs do not count as", 332, CELL)
        made.mark(3, "Abilities")
        entries(made, 5, 452, 346, ["monsters in combat."])
        entries(made, 5, 464, 332, ["Resistance: All piercing damage is", "halved (rounded up)."])
        # A table of animals, a row each.
        made.section(6, 80, 2, "Common Animals", "Animals are common.")
        made.table(6, 140, ["ANIMAL", "MOVEMENT", "HP", "ATTACK", "SKILLS"],
                   [["Hare", "16", "3", "Bite (skill level 8, damage D3)", "Evade 14, Sneaking 12"], ["Great Boar", "12", "14", "Tusks (skill level 12, damage 2D6)", "Awareness 10"]],
                   [68, 120, 178, 218, 388])
        # The typical NPCs of the adventures chapter.
        made.section(7, 80, 1, "8. Adventures", "Adventures are run.")
        made.section(7, 120, 2, "Non-Player Characters", "People are met.")
        made.banner(7, 160, 3, "Table: Typical NPCs")
        for text, x in (("TYPE", 68), ("SKILLS", 130), ("HEROIC ABILITIES", 227), ("BONUS", 312), ("HP", 361), ("WP", 386), ("GEAR", 411)):
            made.line(7, 300, text, x, HEADER)
        people = [(320, ["Guard"], ["Swords 12", "Evade 10"], ["—"], "STR +D4", "12", "—", "Sabre, scale armor"),
                  (360, ["Bandit Chief ", "(Boss)"], ["Swords 15", "Evade 12"], ["Berserker", "Robust × 6", "Veteran"], "STR +D6", "30", "16", "Sabre, scale armor"),
                  (420, ["Villager"], ["Brawling 8"], ["—"], "—", "8", "—", "Wooden club"),
                  (450, ["Scholar"], ["Languages 13", "Myths & Legends 13"], ["—"], "—", "7", "—", "A good book")]
        for y, kind, skills, abilities, bonus, hp, wp, gear in people:
            for column, texts in ((68, kind), (130, skills), (227, abilities)):
                for number, text in enumerate(texts):
                    made.line(7, y + 12 * number, text, column, CELL)
            for column, text in ((312, bonus), (363, hp), (389, wp), (411, gear)):
                made.line(7, y, text, column, CELL)
        made.save()
        self.book = Book(self.tmp / "extract")
        self.pack = Pack(self.book, self.tmp / "out", dragonbane_core.NAME, dragonbane_core.extends(None))
        self.pack.system["weapons"] = {"sabre": {"skill": "swords", "damage": "1d8"}, "dirk": {"skill": "knives", "damage": "1d8"},
                                       "small_wooden_club": {"skill": "hammers", "damage": "1d6"}}
        self.pack.system["armor"] = {"scale_armor": 4}
        bestiary.build(self.pack)

    def read(self, path):
        return tomllib.loads(self.pack.files[path])

    def blows(self, table_id):
        return {tuple(row["range"]): {key: value for key, value in row.items() if key not in ("range", "text")} for row in self.read(f"tables/{table_id}.toml")["results"]}

    def test_a_monsters_numbers_and_rules_are_read_from_its_stat_block(self):
        bogey = self.read("bestiary/bogey.toml")
        self.assertEqual(bogey["stats"], {"hp": 30, "armor": 4, "ferocity": 2, "movement": 12, "regenerate": "1d6", "resist": ["physical"]})
        self.assertEqual((bogey["name"], bogey["role"], bogey["attacks"], bogey["parries"], bogey["source"]), ("Bogey", "A large monster", "bogey_attacks", True, "p. 3"))
        self.assertEqual(bogey["description"], "Size: Large. Regeneration: A bogey recovers D6 HP on each of its turns. Resistance: Takes half damage from weapons, except fire. "
                                               "Typical Gear: Sabre, scale armor")

    def test_an_attack_is_read_for_its_damage_whether_it_can_be_parried_or_dodged_and_whether_armor_counts(self):
        self.assertEqual(self.blows("bogey_attacks"), {
            (1, 1): {},
            (2, 2): {"damage": "2d6", "kind": "slashing", "parry": True},
            (3, 3): {"damage": "2d4", "kind": "bludgeoning", "defend": False},
            (4, 4): {"damage": "1d8+1d6", "armor": False},
            (5, 5): {"damage": "1d8+1d8", "parry": True},
            (6, 6): {"then": "bogey_curses"}})

    def test_a_list_inside_an_attack_is_a_table_it_goes_on_to(self):
        curses = self.read("tables/bogey_curses.toml")
        self.assertEqual((curses["name"], curses["formula"], [row["text"] for row in curses["results"]]),
                         ("Bogey curses", "1d4", ["Your hair falls out.", "You grow a tail.", "Your shadow leaves.", "You forget your name."]))
        self.assertTrue(self.read("tables/bogey_attacks.toml")["results"][5]["text"].endswith("Roll D4:"))

    def test_a_swarm_that_is_immune_and_heals_by_what_it_takes_says_so_and_a_limit_per_creature_is_said_too(self):
        wisp = self.read("bestiary/wisp.toml")
        self.assertEqual(wisp["stats"], {"hp": 9, "armor": 0, "ferocity": 1, "movement": 20, "immune_to": ["physical"], "drain": True})
        self.assertIn("Ferocity and HP are for each wisp.", wisp["description"])
        self.assertNotIn("parries", wisp)
        self.assertEqual(self.blows("wisp_attacks"), {(1, 1): {"damage": "1d6", "kind": "slashing"}, (2, 2): {"damage": "1d4"}})

    def test_folk_who_are_not_monsters_have_a_stat_block_each_with_the_first_weapon_for_an_attack(self):
        scout, warrior = self.read("bestiary/gobs_scout.toml"), self.read("bestiary/gobs_warrior.toml")
        self.assertEqual((scout["name"], scout["role"], scout["attack"], scout["skills"]), ("Gobs scout", "A gobs scout", {"label": "Sabre", "value": 12, "damage": "1d10"}, {"evade": 10, "sneaking": 12}))
        self.assertEqual(scout["stats"], {"hp": 9, "armor": 1, "movement": 10, "resist": ["piercing"]})
        self.assertIn("Typical Weapons: Sabre (skill level 12, damage D10), dirk (skill level 10, damage D8).", scout["description"])
        self.assertIn("Non-Monster: Gobs do not count as monsters in combat.", scout["description"])
        self.assertEqual(warrior["attack"], {"label": "Dirk", "value": 12, "damage": "1d8", "bonus": "1d4"})
        self.assertEqual(warrior["stats"], {"hp": 12, "armor": 0, "movement": 10, "resist": ["piercing"]})

    def test_the_common_animals_are_a_row_each(self):
        boar = self.read("bestiary/great_boar.toml")
        self.assertEqual((boar["name"], boar["role"], boar["attack"], boar["stats"], boar["skills"]),
                         ("Great boar", "A common animal", {"label": "Tusks", "value": 12, "damage": "2d6"}, {"hp": 14, "armor": 0, "movement": 12}, {"awareness": 10}))
        self.assertEqual(self.read("bestiary/hare.toml")["skills"], {"evade": 14, "sneaking": 12})

    def test_a_typical_npc_attacks_with_its_first_weapon_and_wears_the_armor_in_its_gear(self):
        guard = self.read("bestiary/guard.toml")
        self.assertEqual((guard["role"], guard["attack"], guard["stats"], guard["skills"]),
                         ("A typical guard", {"label": "Sabre", "skill": "swords", "damage": "1d8", "bonus": "1d4"}, {"hp": 12, "armor": 4}, {"swords": 12, "evade": 10}))
        self.assertEqual(guard["description"], "Gear: Sabre, scale armor. Damage bonus: STR +D4.")
        chief = self.read("bestiary/bandit_chief.toml")
        self.assertEqual((chief["name"], chief["role"], chief["attack"]["bonus"], chief["stats"]), ("Bandit Chief", "A boss: bandit chief", "1d6", {"hp": 30, "armor": 4}))
        self.assertEqual(chief["description"], "Gear: Sabre, scale armor. Damage bonus: STR +D6. Heroic abilities: Berserker, Robust × 6, Veteran. WP 16.")

    def test_a_weapon_the_book_names_loosely_is_the_gear_tables_and_a_skill_it_lacks_is_the_npcs_own(self):
        villager = self.read("bestiary/villager.toml")
        self.assertEqual(villager["attack"], {"label": "Small wooden club", "skill": "brawling", "damage": "1d6"})
        self.assertEqual(self.pack.notes, ["Villager: the book says 'Wooden club', the gear tables have 'small wooden club': used"])
        self.assertNotIn("attack", self.read("bestiary/scholar.toml"))

    def test_the_pack_says_where_each_entry_went_and_the_audit_finds_what_it_wrote_claimed(self):
        self.assertEqual(self.pack.items["bestiary_bogey"]["to"], ["bestiary/bogey", "tables/bogey_attacks", "tables/bogey_curses"])
        self.assertEqual(self.pack.items["bestiary_gobs"]["to"], ["bestiary/gobs_scout", "bestiary/gobs_warrior"])
        self.assertIn("bestiary/guard", self.pack.items["bestiary_typical_npcs"]["to"])
        self.pack.write(self.tmp / "extract")
        report = audit.audit(self.tmp / "out", "system")
        self.assertEqual([unit for unit in report["unclaimed"] if not unit.startswith("system.toml")], [])
        self.assertEqual(report["problems"], [])


class ChangedAnimalsTableTest(unittest.TestCase):
    def build(self, names, row):
        with tempfile.TemporaryDirectory() as folder:
            made = FakeBook(Path(folder) / "extract")
            made.section(1, 80, 1, "7. Bestiary", "Monsters live here.")
            made.section(2, 80, 2, "Common Animals", "Animals are common.")
            made.table(2, 140, names, [row], [68, 120, 178, 218, 388][:len(names)])
            made.save()
            pack = Pack(Book(Path(folder) / "extract"), Path(folder) / "out", dragonbane_core.NAME, dragonbane_core.extends(None))
            pack.system.update({"weapons": {}, "armor": {}})
            bestiary.build(pack)

    def test_a_table_of_other_columns_or_an_attack_set_otherwise_is_named_with_its_page(self):
        with self.assertRaisesRegex(SoloError, r"'Common Animals' \(p. 2\): the table on p. 2 has 4 columns, and the importer reads 5; this may be another printing"):
            self.build(["ANIMAL", "MOVEMENT", "ATTACK", "SKILLS"], ["Hare", "16", "Bite (skill level 8, damage D3)", "Evade 14"])
        with self.assertRaisesRegex(SoloError, r"'Common Animals' \(p. 2\): can't read the attack of Hare on p. 2 \('Bite, D3, at 8'\)"):
            self.build(["ANIMAL", "MOVEMENT", "HP", "ATTACK", "SKILLS"], ["Hare", "16", "3", "Bite, D3, at 8", "Evade 14"])

    def test_a_number_cell_that_holds_more_than_a_number_is_named_with_its_column_and_page(self):
        with self.assertRaisesRegex(SoloError, r"'Common Animals' \(p. 2\): the table on p. 2 has '3 each' in its HP column, where the importer reads a number"):
            self.build(["ANIMAL", "MOVEMENT", "HP", "ATTACK", "SKILLS"], ["Hare", "16", "3 each", "Bite (skill level 8, damage D3)", "Evade 14"])


if __name__ == "__main__":
    unittest.main()
