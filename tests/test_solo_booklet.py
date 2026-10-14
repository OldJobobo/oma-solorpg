"""The solo booklet read into a system pack: the wiring the booklet's own words give its tables, and, on a made-up booklet with its bookmarks, its tools."""

import os
import tempfile
import tomllib
import unittest
import unittest.mock
from pathlib import Path

from fake_book import FakeBook

from solo import audit
from solo.books import dragonbane_solo
from solo.books.dragonbane_solo import tables
from solo.books.pack import Pack
from solo.sections import Book


class WiringTest(unittest.TestCase):
    def test_cards_a_repeat_a_roll_twice_and_a_roll_for_the_details_of_a_place_are_the_engines_then_and_again(self):
        self.assertEqual(tables._result("Hidden vault – two treasure cards, and roll again.", "search"),
                         {"text": "Hidden vault – two treasure cards, and roll again.", "then": ["treasure", "treasure"], "again": True})
        self.assertEqual(tables._result("One treasure card.", "scavenge"), {"text": "One treasure card.", "then": "treasure"})
        self.assertEqual(tables._result("Roll twice, ignoring this result", "traps"), {"text": "Roll twice, ignoring this result", "then": ["traps", "traps"]})
        self.assertEqual(tables._result("Hidden antechamber – roll for location details.", "search")["then"], "location_detail_rolls")

    def test_a_list_of_things_to_roll_among_is_a_choice_and_a_die_in_the_words_is_a_value_to_roll(self):
        self.assertEqual(tables._result("Supplies. Roll D6. 1: lamp, 2: rope, 3: bell.", "scavenge"), {"text": "Supplies", "choices": ["lamp", "rope", "bell"]})
        self.assertEqual(tables._result("Secret path – diverts to D4 new waypoints.", "search"), {"text": "Secret path – diverts to {value} new waypoints.", "roll": "1d4"})
        self.assertEqual(tables._result("Nothing of note.", "scavenge"), {"text": "Nothing of note."})

    def test_an_attacker_that_attacks_says_with_what_and_one_that_does_something_else_is_an_effect(self):
        self.assertEqual(tables._attacker("Rush! The NPC attacks with a boon, and a hit does an extra D6 damage."),
                         {"text": "Rush! The NPC attacks with a boon, and a hit does an extra D6 damage.", "attack": True, "boons": 1, "extra": "1d6"})
        self.assertEqual({key: value for key, value in tables._attacker("Burst! The NPC attacks twice. All of them are with a bane.").items() if key != "text"},
                         {"attack": True, "banes": 1, "times": 2})
        self.assertEqual({key: value for key, value in tables._attacker("Zap! The NPC casts an attack spell that inflicts 2D6 damage at one foe.").items() if key != "text"},
                         {"attack": True, "damage": "2d6"})
        self.assertEqual({key: value for key, value in tables._attacker("Wait! The NPC uses its action to find a better spot. It attacks next turn with a boon.").items() if key != "text"},
                         {"effect": True})


class BookletTest(unittest.TestCase):
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
        made = FakeBook(self.tmp / "extract")
        page = [0]

        def section(level, title, *text):
            page[0] += 1
            made.section(page[0], 80, level, title, *text)

        def table(level, title, headers, rows, xs):
            page[0] += 1
            made.banner(page[0], 80, level, title)
            made.roll_table(page[0], 100, headers, rows, xs)

        section(1, "Alone in Deepfall Breach", "A solo adventure.")
        section(2, "Introduction", "As a lone hero, you gain one additional heroic ability, any you like, at the start.")
        section(2, "Your Solo Player Character", "Alone you go.")
        section(3, "Heroic Ability: Army of One", "✦Requirement: —", "✦Willpower Points: —", "Alone in a fight, draw two initiative cards and keep both: two turns a round.")
        section(3, "Heroic Ability: Sole Survivor", "✦Requirement: —", "✦Willpower Points: 3", "Going it alone, you can push a roll without suffering a condition, for the price.")
        section(2, "Core Solo Tools", "The tools.")
        section(3, "Fortune Chart", "Ask your question, roll a D6.")
        table(4, "Table: Fortune Chart", ["D6", "YES / NO", "NUMBER", "SCALE", "POWER", "QUALITY", "REACTION"],
              [["1", "Extreme no", "None", "Small", "Weak", "Flawed", "Hostile"], ["2–3", "No", "Few", "Moderate", "Minor", "Mundane", "Wary"],
               ["4–5", "Yes", "Many", "Large", "Strong", "Fine", "Open"], ["6", "Extreme yes", "Lots", "Huge", "Mighty", "Rare", "Warm"]], [72, 110, 170, 230, 290, 350, 410])
        section(3, "Inspiration Table", "Roll on a column.")
        table(4, "Table: Inspiration Table", ["D4", "ACTION", "ATTRIBUTE", "THING"], [["1", "Avenge", "Ancient", "Barrier"], ["2", "Craft", "Blocked", "Cage"], ["3", "Hide", "Cold", "Door"],
                                                                                 ["4", "Seek", "Dark", "Eye"]], [72, 110, 190, 270])
        section(3, "Dragon and Demon Effects", "Dragons and demons add a twist.")
        table(4, "Table: Dragon and Demon Effects", ["D2", "DRAGON EFFECT", "DEMON EFFECT"], [["1", "You find a helpful item", "An item is lost"], ["2", "You are fast", "You are delayed"]], [72, 110, 220])
        section(3, "Managing NPCs and Monsters", "Roll for NPCs.")
        page[0] += 1
        made.section(page[0], 80, 4, "Sidebar: Simple NPC Templates")
        for y, text in ((120, "MINION"), (140, "Attributes: 10 Movement: 10"), (152, "HP: 12 Armor: — Damage: 2D6"), (164, "Skills: relevant skills 12, other 6"),
                        (200, "BOSS"), (220, "Attributes: 14 Movement: 12"), (232, "HP: 20 Armor: 4 Damage: 2D8"), (244, "Skills: relevant skills 15, other 8")):
            made.line(page[0], y, text, 62)
        table(4, "Table: NPC Attack Table", ["D6", "MELEE ATTACKER", "RANGED ATTACKER"], [["1–3", "Blow! The NPC makes a melee attack.", "Shot! The NPC makes a ranged attack."],
                                                                                           ["4–6", "Rage! The NPC roars.", "Volley! The NPC attacks twice. Both attacks are with a bane."]], [72, 110, 300])
        section(2, "Surviving Solo Play", "Alone you survive.")
        section(3, "Suffering Damage", "If you suffer harm, roll on the table.")
        table(4, "Table: Damage Table", ["D6", "CATEGORY", "DAMAGE"], [["1–2", "Slight", "D6"], ["3–5", "Moderate", "2D6"], ["6", "Severe", "2D10"]], [72, 110, 220])
        section(3, "Healing", "As a solo adventurer, you may:", "✦One HEALING roll to tend your own wounds each stretch rest. On a success, heal 2D6 HP.",
                "✦Try to rally yourself, at zero HP and without a bane to the PERSUASION roll.", "✦Rescue your own life with a HEALING roll, at zero HP.")
        section(2, "Your Missions", "Missions.")
        section(3, "Mission Threats", "Track a threat using D6 as a counter, starting at one. At six it comes to pass.")
        table(4, "Table: Threats", ["D2 THREAT"], [["1", "A creature has your scent."], ["2", "The cave shakes."]], [72, 110])
        section(2, "Exploration Tables", "Tables.")
        section(3, "Locations", "Area first. Roll a D4, then roll a D4 as many times on the details table.")
        table(4, "Table: Area Table", ["D2 AREA"], [["1", "Old outpost"], ["2", "Dark tunnel"]], [72, 110])
        table(4, "Table: Location Details", ["D4", "DETAIL"], [["1", "Contents"], ["2", "Environment"], ["3", "Oddity"], ["4", "Danger"]], [72, 110])
        table(4, "Table: Subtables", ["D2", "CONTENTS", "ENVIRONMENT", "ODDITY", "DANGER"], [["1", "Old supplies", "Cold pool", "Strange glyphs", "Acid"], ["2", "Bloody trail", "Webs", "Puzzle", "Ambush"]],
              [72, 110, 190, 270, 350])
        section(3, "Inhabitants", "Who lives here.")
        table(4, "Table: Inhabitants", ["D2", "CREATURE OR PEOPLE"], [["1", "Dragons"], ["2", "Orcs"]], [72, 110])
        section(3, "Scavenging", "Loot. Scavenge twice in an area, it requires a Stretch.")
        table(4, "Table: Scavenge", ["D4", "SCAVENGE"], [["1", "Danger. Roll D4. 1: beast, 2: trap, 3: gas, 4: fall."], ["2–3", "Nothing."], ["4", "One treasure card, and roll again."]], [72, 110])
        section(3, "Searching", "To search, roll SPOT HIDDEN. Searching costs time – it requires a stretch.")
        table(4, "Table: Search Table", ["D4", "SEARCH"], [["1", "Trap – roll again, ignoring this result."], ["2", "Secret path – diverts to D4 new waypoints."], ["3–4", "Hidden treasure – one treasure card."]], [72, 110])
        section(3, "Traps", "Traps abound.")
        table(4, "Table: Traps", ["D4 TRAP"], [["1", "Acid spray"], ["2", "Rolling boulder"], ["3+", "Roll twice, ignoring this result"]], [72, 110])
        made.save(pages=True)
        self.book = Book(self.tmp / "extract")
        self.pack = Pack(self.book, self.tmp / "out", dragonbane_solo.NAME, ["dragonbane-rulebook"])
        dragonbane_solo.build(self.pack)

    def table(self, table_id):
        return tomllib.loads(self.pack.files[f"tables/{table_id}.toml"])

    def test_the_fortune_chart_has_its_bands_and_a_column_of_answers_for_each_kind_of_question(self):
        oracle = self.pack.system["oracle"]
        self.assertEqual((oracle["chart"], oracle["scene_checks"], oracle["inspiration"]), ("fortune", False, ["inspiration_action", "inspiration_attribute", "inspiration_thing"]))
        self.assertEqual(oracle["fortune"]["bands"], [[1, 1], [2, 3], [4, 5], [6, 6]])
        self.assertEqual((oracle["fortune"]["yes_no"], oracle["fortune"]["reaction"]), (["Extreme no", "No", "Yes", "Extreme yes"], ["Hostile", "Wary", "Open", "Warm"]))

    def test_a_threat_is_a_counter_that_moves_with_each_activity_and_a_search_and_a_scavenge_take_a_stretch(self):
        system = self.pack.system
        self.assertEqual(system["threats"], {"segments": 6, "start": 1, "advance": ["activity"], "table": "threats"})
        self.assertEqual(system["search"], {"skill": "spot_hidden", "table": "search", "time": {"stretch": 1}})
        self.assertEqual(system["scavenge"], {"table": "scavenge", "again_time": {"stretch": 1}})
        self.assertEqual(system["effects"], {"dragon": "dragon_effects", "demon": "demon_effects"})

    def test_the_simple_npcs_are_templates_and_the_attack_table_has_a_column_for_each_kind_of_attacker(self):
        npcs = self.pack.system["npcs"]
        self.assertEqual(npcs["attackers"], ["melee", "ranged"])
        self.assertEqual(npcs["templates"]["minion"], {"attributes": 10, "movement": 10, "hp": 12, "armor": 0, "damage": "2d6", "skill": 12, "other": 6})
        self.assertEqual(npcs["templates"]["boss"]["armor"], 4)
        rows = self.table("npc_attacks")["results"]
        self.assertEqual((rows[0]["range"], rows[0]["melee"]["attack"], rows[1]["melee"], rows[1]["ranged"]["times"]), ([1, 3], True, {"text": "Rage! The NPC roars.", "effect": True}, 2))

    def test_a_lone_heros_abilities_and_healing_and_the_extra_ability_they_start_with(self):
        system = self.pack.system
        self.assertEqual(system["abilities"], {"army_of_one": {"name": "Army of One", "initiative": 2}, "sole_survivor": {"name": "Sole Survivor", "push": {"wp": 3}}})
        self.assertEqual(self.pack.creation["extra_abilities"], {"count": 1, "from": ["Army of One", "Sole Survivor"]})
        self.assertEqual(system["rest"], {"stretch": {"tend": {"skill": "healing", "recover": {"hp": "2d6"}}}})
        self.assertEqual(system["dying"], {"self_rally": {"skill": "persuasion"}, "self_save": {"skill": "healing"}})

    def test_the_tables_the_booklet_prints_are_each_a_table_and_a_column_is_a_table_of_its_own(self):
        self.assertEqual([row["text"] for row in self.table("inspiration_attribute")["results"]], ["Ancient", "Blocked", "Cold", "Dark"])
        self.assertEqual(self.table("dragon_effects")["name"], "Dragon effect")
        self.assertEqual([row["text"] for row in self.table("demon_effects")["results"]], ["An item is lost", "You are delayed"])
        self.assertEqual(self.table("harm")["results"], [{"range": [1, 2], "text": "Slight: {value} damage", "roll": "1d6"}, {"range": [3, 5], "text": "Moderate: {value} damage", "roll": "2d6"},
                                                          {"range": [6, 6], "text": "Severe: {value} damage", "roll": "2d10"}])
        self.assertEqual(self.table("location_danger")["results"][1]["text"], "Ambush")

    def test_what_the_booklet_says_in_words_about_a_locations_details_is_a_table_of_its_own(self):
        rolls = self.table("location_detail_rolls")
        self.assertEqual((rolls["formula"], rolls["results"][1]), ("1d4", {"range": [2, 2], "text": "Roll on the location details table 2 times", "then": ["location_details", "location_details"]}))
        self.assertEqual(self.table("location_details")["results"][2], {"range": [3, 3], "text": "Oddity", "then": "location_oddity"})

    def test_the_engines_wiring_follows_the_words_of_the_results(self):
        self.assertEqual(self.table("scavenge")["results"], [{"range": [1, 1], "text": "Danger", "choices": ["beast", "trap", "gas", "fall"]}, {"range": [2, 3], "text": "Nothing."},
                                                              {"range": [4, 4], "text": "One treasure card, and roll again.", "then": "treasure", "again": True}])
        self.assertEqual(self.table("search")["results"][1], {"range": [2, 2], "text": "Secret path – diverts to {value} new waypoints.", "roll": "1d4"})
        self.assertEqual(self.table("traps")["results"][2], {"range": [3, 4], "text": "Roll twice, ignoring this result", "then": ["traps", "traps"]})

    def test_the_audit_finds_the_pack_it_wrote_claimed_and_its_pages_said(self):
        self.pack.write(self.tmp / "extract")
        report = audit.audit(self.tmp / "out", "system")
        self.assertEqual(report["unclaimed"], [])
        self.assertEqual(report["problems"], [])
        # Read back against the made-up book's own pages, every table, number and word is on them.
        self.assertEqual(report["unverified"], [])


class NoTemplatesTest(unittest.TestCase):
    def test_a_sidebar_of_npc_templates_it_cant_read_is_said(self):
        with tempfile.TemporaryDirectory() as folder:
            made = FakeBook(Path(folder) / "extract")
            made.section(1, 80, 1, "Managing NPCs and Monsters", "Roll for NPCs.")
            made.section(1, 160, 2, "Sidebar: Simple NPC Templates", "Make the NPC up as you go.")
            made.save()
            book = Book(Path(folder) / "extract")
            pack = Pack(book, Path(folder) / "out", dragonbane_solo.NAME)
            pack.facts["attackers"] = ["melee"]
            self.assertEqual(dragonbane_solo.system._npcs(pack, book.find("Managing NPCs and Monsters"))["templates"], {})
            self.assertEqual(pack.notes, ["'Sidebar: Simple NPC Templates' (p. 1): no template the importer can read, so the pack has no simple NPCs"])


if __name__ == "__main__":
    unittest.main()
