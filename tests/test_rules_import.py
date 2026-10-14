"""A rulebook through the whole import, the way an agent does it with the solo-rules-import
skill: extract the PDF, start the inventory, transcribe the tables, write a pack laid over
the bundled one, audit it against the book, and play on it. The book is made here, with
what real ones have: running heads, page numbers in the footers and no page labels, a
price list, travel rules, a table, a monster."""

import os
import random
import tempfile
import textwrap
import unittest
import unittest.mock
from pathlib import Path

from helpers import BUNDLED, DRAGONBANE, RAGNA, RED_TUSK, Dice

from solo import SoloError, audit, booktables, campaign, cli, extract, packs

try:
    import pymupdf
except ImportError:
    pymupdf = None

PAGES = [
    ("DRAGON TESTS\nThe rulebook", None),
    ("Contents\nEquipment 1\nTravel 2\nMonsters 4", None),
    ("Equipment\nWhat things cost in the markets of the realm. One gold is ten silver, one silver ten copper.\n"
     "Rope, 10 meters: 1 silver\nTorch: 2 copper\nRoom at an inn, one night: 1 silver\nBroadsword: 12 silver\n", 1),
    ("Journeys\nOn a road a hero on foot covers 15 kilometers in a shift, and 10 off the road. "
     "Every shift of travel in the wild, the pathfinder rolls BUSHCRAFT: a failure means the party is lost for a shift.\n", 2),
    ("Weather\nRoll D6 every morning of a journey.\n1-2 Clear skies\n3-4 Rain, a bane on BUSHCRAFT\n5 Storm, no travel\n6 Fog, a bane on AWARENESS\n", 3),
    ("Monsters\nWolf. Hit points 10, armor 1. Wolves hunt in packs.\nWolf attacks (D6)\n1-3 Bite: 2D6 damage\n4-5 Pounce: 1D8 damage\n6 Howl: the pack gathers\n", 4),
]


def make_rulebook(path):
    """Six pages. The rules pages carry a running head and a page number, printed 1 on the
    PDF's third page, and the PDF has no page labels (most don't)."""
    doc = pymupdf.open()
    for text, printed in PAGES:
        page = doc.new_page()
        if printed:
            page.insert_text((72, 40), "DRAGON TESTS - CORE RULES", fontsize=8)
            page.insert_text((300, 820), str(printed), fontsize=8)
        page.insert_textbox(pymupdf.Rect(72, 72, 540, 780), text, fontsize=10)
    doc.set_toc([[1, "Front", 1], [1, "Equipment", 3], [1, "Travel", 4], [2, "Journeys", 4], [2, "Weather", 5], [1, "Monsters", 6]])
    doc.save(path)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


@unittest.skipUnless(pymupdf, "PyMuPDF isn't installed")
class RulesImport(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        env = {"SOLO_HOME": str(self.tmp / "games"), "XDG_STATE_HOME": str(self.tmp / "state"), "SOLO_DEBUG": "1"}
        patch = unittest.mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        make_rulebook(self.tmp / "Dragon Tests.pdf")
        self.book, self.manifest = extract.extract(self.tmp / "Dragon Tests.pdf")
        self.pack = self.tmp / "games" / "systems" / "dragonbane"

    def page(self, number):
        return (self.book / "pages" / f"{number:04d}.txt").read_text(encoding="utf-8")

    def build_pack(self):
        """What an agent writes: only what the book adds. The test rules stand in for the
        rulebook's pack under it (the bundled pack holds only names)."""
        write(self.pack / "system.toml", f'extends = "{DRAGONBANE}"\n')
        write(self.pack / "gear.toml", """
            [money]
            coins = { gold = 100, silver = 10, copper = 1 }

            [gear.rope]
            name = "Rope, 10 meters"
            category = "Equipment"
            price = "1 silver"

            [gear.torch]
            name = "Torch"
            category = "Equipment"
            price = "2 copper"

            [gear.inn_room]
            name = "Room at an inn, one night"
            category = "Services"
            price = "1 silver"

            [gear.broadsword]
            name = "Broadsword"
            category = "Weapons"
            price = "12 silver"
            """)
        weather = "\n".join(line for line in self.page(5).splitlines() if booktables._ROLL.match(line) or "D6" in line)
        path, problems = booktables.write(weather, self.pack / "tables" / "weather.toml", name="Weather", source="p. 5")
        self.assertEqual(problems, [])
        attacks = "\n".join(line for line in self.page(6).splitlines() if booktables._ROLL.match(line) or line.startswith("Wolf attacks"))
        booktables.write(attacks, self.pack / "tables" / "wolf_attacks.toml", name="Wolf attacks")
        text = (self.pack / "tables" / "wolf_attacks.toml").read_text(encoding="utf-8")
        # The agent adds what the engine needs to the transcribed rows: each blow's damage.
        text = text.replace('text = "Bite: 2D6 damage" }', 'text = "Bite: 2D6 damage", damage = "2d6" }')
        text = text.replace('text = "Pounce: 1D8 damage" }', 'text = "Pounce: 1D8 damage", damage = "1d8" }')
        (self.pack / "tables" / "wolf_attacks.toml").write_text(text, encoding="utf-8")
        write(self.pack / "bestiary" / "wolf.toml", """
            name = "Wolf"
            role = "A hunter of the wild, one of a pack"
            attacks = "wolf_attacks"

            [stats]
            hp = 10
            armor = 1
            """)
        write(self.pack / "rules" / "journeys.md", """
            # Journeys
            Search: travel, travel time, journey, distance, kilometers, lost

            The book's rules for travel, in the importer's words: on a road, 15 km a shift on foot; 10 off the road.
            In the wild the pathfinder rolls BUSHCRAFT every shift; a failure loses a shift.
            """)
        items = self.pack / "inventory"
        write(self.pack / "inventory.toml", f'source = "Dragon Tests"\nextract = "{self.book}"\n')
        write(items / "01-front.toml", """
            [items.front]
            kind = "other"
            pages = ["1-2"]
            status = "skipped"
            note = "cover and contents"
            """)
        write(items / "02-equipment.toml", """
            [items.prices]
            name = "What things cost"
            kind = "gear"
            pages = [3]
            status = "mapped"
            to = ["gear.toml:money", "gear.toml:gear.rope", "gear.toml:gear.torch", "gear.toml:gear.inn_room", "gear.toml:gear.broadsword"]
            """)
        write(items / "03-travel.toml", """
            [items.journeys]
            kind = "mechanic"
            pages = [4]
            status = "mapped"
            to = ["rules/journeys.md"]

            [items.weather]
            kind = "table"
            pages = [5]
            status = "mapped"
            to = ["tables/weather"]
            """)
        write(items / "04-monsters.toml", """
            [items.wolf]
            kind = "creature"
            pages = [6]
            status = "mapped"
            to = ["bestiary/wolf", "tables/wolf_attacks"]
            """)

    def test_extract_takes_out_the_running_heads_and_reads_the_printed_pages(self):
        self.assertNotIn("DRAGON TESTS - CORE RULES", self.page(3))
        self.assertIn("dragon tests - core rules", self.manifest["running"])
        self.assertEqual(self.manifest["labels_from"], "footers")
        self.assertEqual(self.manifest["labels"]["3"], "1")
        self.assertEqual(self.manifest["labels"]["6"], "4")
        self.assertNotIn("2", self.manifest["labels"])
        self.assertIn("===== PAGE 5 (printed 3) =====", (self.book / "book.md").read_text(encoding="utf-8"))
        self.assertTrue(self.page(1).startswith("DRAGON TESTS"))  # the cover's title isn't a running head

    def test_the_scaffold_cites_every_page_with_an_item_per_section_and_table(self):
        written = audit.scaffold(self.pack, self.book)
        self.assertEqual(written, ["inventory.toml", "inventory/01-front.toml", "inventory/02-equipment.toml",
                                   "inventory/03-travel.toml", "inventory/04-monsters.toml"])
        write(self.pack / "system.toml", 'extends = "dragonbane"\n')
        report = audit.audit(self.pack, "system")
        self.assertEqual(report["pages"]["uncited"], [])
        items = {i["id"]: i for i in report["todo"]}
        self.assertEqual((items["journeys"]["kind"], items["journeys"]["pages"], items["journeys"]["file"]), ("mechanic", [4], "inventory/03-travel.toml"))
        self.assertEqual(items["weather"]["pages"], [5])
        self.assertEqual(items["equipment"]["kind"], "gear")
        self.assertIn("table_on_page_5", items)
        self.assertIn("inventory/03-travel.toml: 3 of 3 still todo", audit.render(report))
        with self.assertRaisesRegex(SoloError, "already has an inventory"):
            audit.scaffold(self.pack, self.book)

    def test_the_scaffold_wont_write_into_the_extract(self):
        with self.assertRaisesRegex(SoloError, "is the book's extract"):
            audit.scaffold(self.book, self.book)
        self.assertFalse((self.book / "inventory.toml").exists())

    def test_a_pack_true_to_the_book_passes_the_audit(self):
        self.build_pack()
        report = audit.audit(self.pack, "system")
        self.assertFalse(audit.failed(report), audit.render(report))
        system = packs.load_system(self.pack)
        self.assertEqual(system["name"], "Dragonbane")  # the bundled pack underneath
        self.assertIn("fortune", system["oracle"])
        self.assertEqual(system["tables"]["weather"]["formula"], "1d6")
        self.assertIn("treasure", system["tables"])
        self.assertEqual(packs.validate(system), [])

    def test_the_audit_reads_the_pack_back_against_its_pages(self):
        self.build_pack()
        write(self.pack / "gear.toml", (self.pack / "gear.toml").read_text(encoding="utf-8").replace('"12 silver"', '"15 silver"'))
        weather = (self.pack / "tables" / "weather.toml").read_text(encoding="utf-8").replace("Storm, no travel", "Hail the size of eggs")
        (self.pack / "tables" / "weather.toml").write_text(weather, encoding="utf-8")
        wolf = (self.pack / "tables" / "wolf_attacks.toml").read_text(encoding="utf-8").replace('damage = "1d8"', 'damage = "1d10"')
        (self.pack / "tables" / "wolf_attacks.toml").write_text(wolf, encoding="utf-8")
        write(self.pack / "bestiary" / "wolf.toml", (self.pack / "bestiary" / "wolf.toml").read_text(encoding="utf-8").replace("hp = 10", "hp = 12"))
        report = audit.audit(self.pack, "system")
        found = "\n".join(report["unverified"])
        self.assertIn("prices: gear.toml:gear.broadsword gives price 15, and p. 3 never says it", found)
        self.assertIn('weather: tables/weather result 5 "Hail the size of eggs" isn\'t on p. 5', found)
        self.assertIn("wolf: tables/wolf_attacks has d10, and p. 6 never says it", found)
        self.assertIn("wolf: bestiary/wolf gives stats.hp 12, and p. 6 never says it", found)
        self.assertTrue(audit.failed(report))

    def test_play_on_it(self):
        self.build_pack()
        root = campaign.create(self.tmp / "game", self.pack, RED_TUSK, RAGNA)
        with campaign.session(root) as c:
            self.assertEqual(c.system["dir"], self.pack.resolve())
            folders = [*(d / "rules" for d in c.system["dirs"]), c.adventure["dir"] / "rules"]
            pages = packs.rule_pages(folders, packs.engine_rules(c.system))

            def rule(topic):
                return cli.rule_text(topic, packs.rule_matches(folders, topic, packs.engine_rules(c.system)), pages, cli._tables_about(c, topic))

            self.assertIn("- Services (1): solo rule prices services", rule("prices"))
            self.assertIn("- Room at an inn, one night: 1 silver", rule("inn"))
            self.assertIn("- Broadsword: 12 silver (swords, 2d6 damage)", rule("broadsword"))
            self.assertIn("15 km a shift on foot", rule("travel time"))
            self.assertIn("Weather (solo table weather)", rule("weather"))
            self.assertIn("- wolf: Wolf, A hunter of the wild, one of a pack (HP 10, armor 1, attacks: solo table wolf_attacks)", rule("bestiary"))
            # A wolf the adventure never wrote, from the book's bestiary, fought by its own table.
            c.commit({"npc": {"wolf_1": {"name": "Grey wolf", "monster": "wolf"}}})
            fight = c.fight(["wolf_1"], rng=random.Random(3))
            self.assertEqual((fight["foes"]["wolf_1"]["hp"], fight["foes"]["wolf_1"]["armor"]), (10, 1))
            bite = c.enemy("wolf_1", rng=Dice(1))
            self.assertEqual(bite["incoming"]["damage"], "2d6")
            self.assertIn("Grey wolf", cli.npc_card(c, "wolf_1"))
            with self.assertRaisesRegex(SoloError, "monster must be one of the bestiary's \\(wolf\\)"):
                c.commit({"npc": {"bear": {"name": "Bear", "monster": "bear"}}})


class Transcribing(unittest.TestCase):
    def test_roll_lines_with_dashes_and_a_result_over_two_lines(self):
        formula, results = booktables.parse("Fear (D6)\n1 Frozen in place\n2–3 Shaken, and the hero\ndrops what they hold\n4-6 Panic")
        self.assertEqual(formula, "1d6")
        self.assertEqual(results, [{"range": [1, 1], "text": "Frozen in place"},
                                   {"range": [2, 3], "text": "Shaken, and the hero drops what they hold"},
                                   {"range": [4, 6], "text": "Panic"}])

    def test_a_row_number_alone_on_its_line_starts_a_row_and_a_number_in_the_words_does_not(self):
        text = "D8 EFFECT\n\n1\nEnfeebled. You lose 2D6 WP\nand become Disheartened.\n\n2\nShaken. Everyone within\n10\nmeters is Scared.\n\n3\nPanting.\n"
        formula, results = booktables.parse(text)
        self.assertEqual(formula, "1d8")
        self.assertEqual(results, [{"range": [1, 1], "text": "Enfeebled. You lose 2D6 WP and become Disheartened."},
                                   {"range": [2, 2], "text": "Shaken. Everyone within 10 meters is Scared."},
                                   {"range": [3, 3], "text": "Panting."}])

    def test_a_wrapped_line_that_starts_with_a_number_is_not_a_row(self):
        text = "D6 ATTACK\n\n1\nRoar! Everyone within\n20 meters suffers a fear attack.\n\n2\nSweep! Hits everyone within\n2 meters.\n\n3\nBite.\n"
        formula, results = booktables.parse(text)
        self.assertEqual([r["range"] for r in results], [[1, 1], [2, 2], [3, 3]])
        self.assertEqual(results[0]["text"], "Roar! Everyone within 20 meters suffers a fear attack.")
        self.assertEqual(results[1]["text"], "Sweep! Hits everyone within 2 meters.")

    def test_a_markdown_grid_keeps_its_extra_columns(self):
        formula, results = booktables.parse("|D20|Result|Effect|\n|---|---|---|\n|1-10|Nothing|<br>|\n|11-20|Ambush|A bane on SNEAKING|")
        self.assertEqual(formula, "1d20")
        self.assertEqual(results, [{"range": [1, 10], "text": "Nothing"}, {"range": [11, 20], "text": "Ambush; Effect: A bane on SNEAKING"}])

    def test_the_dice_come_from_the_ranges_when_the_header_is_silent(self):
        self.assertEqual(booktables.guess_formula([{"range": [11, 36]}, {"range": [41, 66]}]), "d66")
        self.assertEqual(booktables.guess_formula([{"range": [2, 6]}, {"range": [7, 12]}]), "2d6")
        self.assertEqual(booktables.guess_formula([{"range": [1, 50]}, {"range": [51, 100]}]), "1d100")

    def test_a_gap_is_written_and_said(self):
        with tempfile.TemporaryDirectory() as folder:
            path, problems = booktables.write("1-2 Clear\n4-6 Rain", Path(folder) / "weather.toml", formula="1d6")
            self.assertEqual(problems, ["table weather: no result for 3"])
            self.assertIn('{ range = [4, 6], text = "Rain" },', path.read_text(encoding="utf-8"))


class Layers(unittest.TestCase):
    def test_a_pack_can_extend_itself_only_once(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder) / "a", Path(folder) / "b"
            write(a / "system.toml", 'extends = "../b"\n')
            write(b / "system.toml", 'extends = "../a"\n')
            with self.assertRaisesRegex(SoloError, "extends it back"):
                packs.load_system(a)
            write(a / "system.toml", 'extends = "nowhere"\n')
            with self.assertRaisesRegex(SoloError, "no system pack by that name"):
                packs.load_system(a)

    def test_the_rulebook_sits_under_the_solo_rules(self):
        """make rules with both books: the rulebook's pack over the bundled names, the solo
        booklet's over it, under the name campaigns look for."""
        with tempfile.TemporaryDirectory() as folder, unittest.mock.patch.dict(os.environ, {"SOLO_HOME": folder}):
            systems = Path(folder) / "systems"
            write(systems / "dragonbane-rulebook" / "system.toml", 'extends = "bundled:dragonbane"\n[time]\nround = 10\n')
            write(systems / "dragonbane" / "system.toml", 'extends = "dragonbane-rulebook"\n[search]\nskill = "spot_hidden"\n')
            top = packs.load_system(systems / "dragonbane")
            self.assertEqual([d.name for d in top["dirs"]], ["dragonbane", "dragonbane-rulebook", "dragonbane"])
            self.assertEqual(top["dirs"][-1], BUNDLED.resolve())
            self.assertEqual((top["time"], top["search"]["skill"], top["attributes"]["str"]), ({"round": 10}, "spot_hidden", "Strength"))
            # Loaded by itself (to audit it), the rulebook's pack still finds the bundled names under it.
            self.assertEqual(packs.load_system(systems / "dragonbane-rulebook")["dirs"][-1], BUNDLED.resolve())
            write(systems / "dragonbane-rulebook" / "system.toml", 'extends = "bundled:nowhere"\n')
            with self.assertRaisesRegex(SoloError, "no system pack by that name"):
                packs.load_system(systems / "dragonbane")

    def test_a_pack_can_extend_a_list_of_packs_laid_down_in_order(self):
        """A supplement over the rulebook doesn't have to become the top pack: the top pack lists
        the ones it wants, the rulebook they share is laid down once, and a later one wins."""
        with tempfile.TemporaryDirectory() as folder, unittest.mock.patch.dict(os.environ, {"SOLO_HOME": folder}):
            systems = Path(folder) / "systems"
            write(systems / "rules" / "system.toml", 'extends = "bundled:dragonbane"\n[time]\nround = 10\n')
            write(systems / "cards" / "system.toml", 'extends = "rules"\n')
            write(systems / "cards" / "tables" / "loot.toml", 'name = "Loot"\nformula = "1d6"\nresults = [{ range = [1, 6], text = "Coin" }]\n')
            write(systems / "spells" / "system.toml", 'extends = "rules"\n[time]\nround = 5\n')
            write(systems / "top" / "system.toml", 'extends = ["cards", "spells"]\n')
            top = packs.load_system(systems / "top")
            self.assertEqual([d.name for d in reversed(top["dirs"])], ["dragonbane", "rules", "cards", "spells", "top"])
            self.assertEqual((top["time"], "loot" in top["tables"]), ({"round": 5}, True))
            # Each supplement still loads by itself over the rulebook, to be audited against its own book.
            self.assertEqual([d.name for d in reversed(packs.load_system(systems / "cards")["dirs"])], ["dragonbane", "rules", "cards"])
            write(systems / "rules" / "system.toml", 'extends = ["bundled:dragonbane", "top"]\n')
            with self.assertRaisesRegex(SoloError, "extends it back"):
                packs.load_system(systems / "top")

    def test_prices_read_as_the_book_writes_them(self):
        money = {"coins": {"gold": 100, "silver": 10, "copper": 1}, "aliases": {"sc": "silver"}}
        for text, value in [("1 gold 5 silver", 150), ("3 gold coins", 300), ("12 sc", 120), ("7", 7), ("2 coppers", 2),
                            ("1 gold, 2 silver and 3 copper", 123), ("varies", None), ("5 dragons", None)]:
            with self.subTest(text=text):
                self.assertEqual(packs.price(text, money), value)


class RuleSearch(unittest.TestCase):
    def pages(self, folder):
        write(folder / "journeys.md", "# Journeys\nSearch: travel, travel time\n\nA shift covers 15 km on a road.\n")
        write(folder / "beginnings.md", "# Beginnings\nAt the beginning of play, the heroes meet.\n")
        write(folder / "inns.md", "# Villages\nAn inn has rooms. The inn keeper knows rumours.\n")
        return [folder]

    def test_search_terms_whole_words_and_ranking(self):
        with tempfile.TemporaryDirectory() as folder:
            folders = self.pages(Path(folder))
            self.assertEqual([p["title"] for _, p in packs.rule_matches(folders, "travel time")], ["Journeys"])
            self.assertEqual(packs.rule_matches(folders, "travel time")[0][0], packs._EXACT)
            self.assertEqual([p["title"] for _, p in packs.rule_matches(folders, "inn")], ["Villages"])  # never "beginning"
            text = cli.rule_text("inn", packs.rule_matches(folders, "inn"), packs.rule_pages(folders), [])
            self.assertTrue(text.startswith("# Villages"))
            with self.assertRaisesRegex(SoloError, "it's yours to rule: a skill roll or the oracle, then write the answer down"):
                cli.rule_text("dragons", [], packs.rule_pages(folders), [])


if __name__ == "__main__":
    unittest.main()
