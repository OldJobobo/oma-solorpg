"""The importers for a book (solo/books/): tables read from where their words sit, and the gear recipe
on a made-up book that has the bookmarks of the real one and none of its words or numbers."""

import os
import tempfile
import tomllib
import types
import unittest
import unittest.mock
from pathlib import Path

from fake_book import BANNER, BODY, BOX, CELL, HEADER, HEADING, FakeBook
from test_cli import CliCase

from solo import SoloError, audit, booktables, books, foundry, library
from solo.books import dice, grid, read
from solo.books.pack import Pack
from solo.books import dragonbane_core
from solo.books.dragonbane_core import tables
from solo.sections import Book


def cell_line(page, y, text, x, style=CELL, words=None):
    font, size, color = style
    return {"x0": x, "y0": y, "x1": x + 5 * len(text), "y1": y + 12, "text": text, "size": size, "font": font, "color": color,
            "col": 0, "page": page, "words": words or [[x + 6 * i, x + 6 * i + 5] for i, _ in enumerate(text.split())]}


class GridTest(unittest.TestCase):
    def header(self, page=1, y=100):
        return [cell_line(page, y, "ITEM", 68, HEADER), cell_line(page, y, "COST", 150, HEADER), cell_line(page, y, "SUPPLY", 200, HEADER),
                cell_line(page, y - 9, "WEIGHT", 250, HEADER), cell_line(page, y, "EFFECT", 290, HEADER)]

    def test_the_header_names_the_columns_and_a_row_ends_where_the_next_is_a_row_below(self):
        lines = self.header() + [
            cell_line(1, 120, "Rope", 68), cell_line(1, 120, "1 gold", 151), cell_line(1, 120, "Common", 200), cell_line(1, 120, "1", 255), cell_line(1, 120, "Boon on climbing.", 290),
            cell_line(1, 137, "Lamp", 68), cell_line(1, 137, "5 silver", 151), cell_line(1, 137, "Rare", 200), cell_line(1, 137, "—", 255), cell_line(1, 137, "Burns for a shift", 290),
            cell_line(1, 149, "and then goes out.", 290),
        ]
        header, rows = grid.read(lines)
        self.assertEqual(header, ["ITEM", "COST", "SUPPLY", "WEIGHT", "EFFECT"])
        self.assertEqual([row["cells"] for row in rows], [
            ["Rope", "1 gold", "Common", "1", "Boon on climbing."],
            ["Lamp", "5 silver", "Rare", "—", "Burns for a shift and then goes out."],
        ])

    def test_a_cell_keeps_its_lines_apart_as_well_as_joined(self):
        lines = self.header() + [
            cell_line(1, 120, "Rope", 68), cell_line(1, 120, "1 gold", 151), cell_line(1, 120, "Common", 200), cell_line(1, 120, "1", 255), cell_line(1, 120, "Boon on climbing.", 290),
            cell_line(1, 132, "Sturdy.", 290)]
        _, rows = grid.read(lines)
        self.assertEqual((rows[0]["cells"][4], rows[0]["parts"][4], rows[0]["parts"][0]), ("Boon on climbing. Sturdy.", ["Boon on climbing.", "Sturdy."], ["Rope"]))

    def test_two_cells_the_pdf_set_in_one_line_are_cut_at_the_gap(self):
        fused = cell_line(1, 120, "5 silver Common", 154, words=[[154.5, 160.2], [162.1, 185.6], [192.8, 229.8]])
        _, rows = grid.read(self.header() + [cell_line(1, 120, "Whistle", 68), fused, cell_line(1, 120, "Heard far.", 290)])
        self.assertEqual(rows[0]["cells"][:3], ["Whistle", "5 silver", "Common"])

    def test_a_name_that_wraps_and_a_price_that_wraps_join_their_cells(self):
        lines = self.header() + [
            cell_line(1, 120, "Lodging,", 68), cell_line(1, 120, "2 gold/", 151), cell_line(1, 120, "Common", 200),
            cell_line(1, 132, "Suite", 68), cell_line(1, 132, "day", 160),
        ]
        _, rows = grid.read(lines)
        self.assertEqual(rows[0]["cells"][:3], ["Lodging, Suite", "2 gold/day", "Common"])

    def test_a_table_that_goes_on_to_the_next_page_repeats_its_header_and_is_read_once(self):
        lines = self.header() + [cell_line(1, 120, "Rope", 68), cell_line(1, 120, "1 gold", 151)]
        lines += self.header(page=2) + [cell_line(2, 120, "Tent", 68), cell_line(2, 120, "4 gold", 151)]
        header, rows = grid.read(lines)
        self.assertEqual(header, ["ITEM", "COST", "SUPPLY", "WEIGHT", "EFFECT"])
        self.assertEqual([(row["cells"][0], row["page"]) for row in rows], [("Rope", 1), ("Tent", 2)])


class DiceTest(unittest.TestCase):
    def read(self, lines):
        return dice.read(lines, lambda text, part: text[:-1] + part)

    def test_a_number_in_a_cell_of_its_own_or_at_the_start_of_the_text_line_is_a_row(self):
        found = self.read([
            cell_line(1, 100, "D6 FEAR", 67, HEADER),
            cell_line(1, 120, "1", 72), cell_line(1, 120, "Frozen in place", 88),
            cell_line(1, 137, "2-3", 70), cell_line(1, 137, "You flee", 88), cell_line(1, 149, "into the dark", 88),
            cell_line(1, 166, "4", 72), cell_line(1, 166, "Shaken", 88),
            cell_line(1, 183, "5 Steady", 72),
            cell_line(1, 200, "6", 72), cell_line(1, 200, "Unmoved by", 88), cell_line(1, 212, "the for-", 88), cell_line(1, 224, "est", 88),
        ])
        self.assertEqual((found["faces"], dice.formula(found["faces"])), (6, "1d6"))
        self.assertEqual([(row["low"], row["high"], row["text"]) for row in found["rows"]], [
            (1, 1, "Frozen in place"), (2, 3, "You flee into the dark"), (4, 4, "Shaken"), (5, 5, "Steady"), (6, 6, "Unmoved by the forest")])

    def test_a_table_in_two_halves_side_by_side_is_read_in_the_order_of_its_numbers(self):
        found = self.read([
            cell_line(1, 100, "D4 FLAW", 67, HEADER), cell_line(1, 100, "D4 FLAW", 319, HEADER),
            cell_line(1, 120, "1", 72), cell_line(1, 120, "Vain", 88), cell_line(1, 120, "3", 325), cell_line(1, 120, "Greedy", 340),
            cell_line(1, 137, "2", 72), cell_line(1, 137, "Proud", 88), cell_line(1, 137, "4", 325), cell_line(1, 137, "Lazy", 340),
        ])
        self.assertEqual([(row["low"], row["text"]) for row in found["rows"]], [(1, "Vain"), (2, "Proud"), (3, "Greedy"), (4, "Lazy")])

    def test_the_columns_of_a_row_are_its_cells_and_the_header_names_them(self):
        found = self.read([
            cell_line(1, 100, "D2", 67, HEADER), cell_line(1, 100, "ANIMAL", 88, HEADER), cell_line(1, 100, "REQUIREMENT", 150, HEADER), cell_line(1, 100, "RATIONS", 230, HEADER),
            cell_line(1, 120, "1", 72), cell_line(1, 120, "Hare", 88), cell_line(1, 120, "Weapon or trap", 150), cell_line(1, 120, "1", 230),
            cell_line(1, 137, "2", 72), cell_line(1, 137, "Stag", 88), cell_line(1, 137, "Weapon", 150), cell_line(1, 137, "D6", 230),
        ])
        self.assertEqual(found["headers"], ["D2", "ANIMAL", "REQUIREMENT", "RATIONS"])
        self.assertEqual([row["cells"] for row in found["rows"]], [["Hare", "Weapon or trap", "1"], ["Stag", "Weapon", "D6"]])

    def test_a_table_whose_rows_stop_short_of_its_die_has_lost_a_row(self):
        lines = [cell_line(4, 100, "D6 FEAR", 67, HEADER)] + [line for y, number, text in [(120, "1", "Shakes"), (137, "2", "Runs"), (154, "4", "Faints"), (171, "5-6", "Screams")]
                                                             for line in (cell_line(4, y, number, 72), cell_line(4, y, text, 88))]
        with self.assertRaisesRegex(Exception, r"the table under 'D6 FEAR' on p. 4 has rows for 1-2 and none for 3, short of its die; this may be another printing"):
            self.read(lines)
        # A table that goes on from another page has no die of its own here: it is read as far as it goes.
        self.assertEqual([row["low"] for row in dice.read(lines[1:5], lambda text, part: text + part, 6)["rows"]], [1, 2])

    def test_a_hundred_is_written_00(self):
        lines = [cell_line(1, 100, "D% OMEN", 67, HEADER), cell_line(1, 120, "01-50", 70), cell_line(1, 120, "Rain", 100), cell_line(1, 137, "51-00", 70), cell_line(1, 137, "Sun", 100)]
        self.assertEqual([(row["low"], row["high"], row["text"]) for row in self.read(lines)["rows"]], [(1, 50, "Rain"), (51, 100, "Sun")])

    def test_a_table_without_its_die_is_no_table(self):
        with self.assertRaisesRegex(Exception, "no roll table"):
            self.read([cell_line(1, 120, "1", 72), cell_line(1, 120, "Hare", 88)])

    def test_the_die_of_a_label(self):
        self.assertEqual([dice.faces(label) for label in ("D6", "d20 FEAR", "D66", "D%")], [6, 20, 66, 100])
        self.assertEqual([dice.formula(sides) for sides in (6, 66, 100)], ["1d6", "d66", "1d100"])


class CountTest(unittest.TestCase):
    def test_a_count_in_words_the_importer_doesnt_know_is_said_not_a_key_error(self):
        self.assertEqual((read.count("Three"), read.count("12")), (3, 12))
        with self.assertRaisesRegex(SoloError, r"the importer reads 'eleven' where it expects a number, and doesn't know it as one"):
            read.count("eleven")


class TablesRecipeTest(unittest.TestCase):
    """The roll tables of a made-up book: its bookmarks, set the ways the real one sets them."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        made = FakeBook(self.tmp / "extract")
        made.line(1, 80, "GEAR", style=HEADING)
        made.mark(1, "6. Gear")
        made.line(2, 80, "ADVENTURES", style=HEADING)
        made.mark(1, "9. Adventures")
        # A table with its number in a cell of its own, a range, and a cell that wraps.
        made.line(2, 100, "FEAR", x=250, style=BANNER)
        made.mark(2, "Table: Fear Table")
        made.line(2, 120, "D4 FEAR", 67, HEADER)
        for y, number, text in [(140, "1", "You stand frozen"), (157, "2-3", "You run from the"), (185, "4", "You stay calm")]:
            made.line(2, y, number, 72, CELL)
            made.line(2, y, text, 88, CELL)
        made.line(2, 169, "place at once", 88, CELL)
        # Named columns, and a footnote under the table.
        made.line(2, 240, "HUNTING", x=250, style=BANNER)
        made.mark(2, "Table: Hunting")
        for name, x in [("D2", 67), ("ANIMAL", 88), ("REQUIREMENT", 150), ("RATIONS", 230)]:
            made.line(2, 260, name, x, HEADER)
        for y, cells in [(280, ["1", "Hare", "Weapon or trap", "1"]), (297, ["2", "Stag*", "Weapon", "D6"])]:
            for cell, x in zip(cells, [72, 88, 150, 230]):
                made.line(2, y, cell, x, CELL)
        made.line(2, 320, "* A stag fights back if the roll fails.", 67, CELL)
        # Two halves, the bookmark at the second.
        made.line(3, 80, "Every hero has a flaw, which makes the story.", style=BODY)
        made.mark(2, "Optional Rule: Weakness")
        made.line(3, 300, "D4 FLAW", 67, HEADER)
        for y, number, text in [(320, "1", "Vain"), (337, "2", "Proud")]:
            made.line(3, y, number, 72, CELL)
            made.line(3, y, text, 88, CELL)
        made.line(3, 300, "D4 FLAW", 319, HEADER)
        made.mark(3, "Table: Weakness")
        for y, number, text in [(320, "3", "Greedy"), (337, "4", "Lazy")]:
            made.line(3, y, number, 325, CELL)
            made.line(3, y, text, 340, CELL)
        # A box with no table in its bookmark.
        made.line(4, 80, "Wounds that last are rolled for here.", style=BODY)
        made.mark(2, "Optional Rule: Severe Injuries")
        for name, x in [("D4", 67), ("INJURY", 88), ("EFFECT", 150)]:
            made.line(4, 120, name, x, HEADER)
        for y, cells in [(140, ["1-2", "Bruise", "Bane on AWARENESS."]), (157, ["3-4", "Limp", "Movement is halved."])]:
            for cell, x in zip(cells, [70, 88, 150]):
                made.line(4, y, cell, x, CELL)
        # Dice across the top, each column a table the first one rolls the rest after.
        made.line(5, 80, "THE QUEST", x=250, style=BANNER)
        made.mark(2, "Table: The Quest")
        for mark, x in zip(["D4", "D3", "D4", "D4", "D4", "D4"], [104, 184, 264, 344, 424, 504]):
            made.line(5, 100, mark, x, HEADER)
        quest = [["at dusk", "a stranger", "a baker", "find", "lamp", "Lost Lamp"], ["by the well", "a note", "a beggar", "hide", "bell", "Loud Bell"],
                 ["in the rain", "a rumor", "a bard", "steal", "key", "Low Key"], ["at the fair", "—", "a butcher", "free", "map", "Late Map"]]
        for row, cells in enumerate(quest):
            made.line(5, 120 + 17 * row, str(row + 1), 70, CELL)
            for cell, x in zip(cells, [100, 180, 260, 340, 420, 500]):
                made.line(5, 120 + 17 * row, cell, x, CELL)
        made.save(pages=True)
        self.book = Book(self.tmp / "extract")
        self.pack = Pack(self.book, self.tmp / "out", dragonbane_core.NAME, dragonbane_core.extends(None))
        tables.build(self.pack)

    def table(self, table_id):
        return tomllib.loads(self.pack.files[f"tables/{table_id}.toml"])

    def results(self, table_id):
        return [(tuple(row["range"]), row["text"]) for row in self.table(table_id)["results"]]

    def test_a_table_is_named_for_its_bookmark_and_its_rows_are_read_with_their_ranges_and_wraps(self):
        self.assertEqual({key: self.table("fear")[key] for key in ("name", "formula", "source")}, {"name": "Fear", "formula": "1d4", "source": "p. 2"})
        self.assertEqual(self.results("fear"), [((1, 1), "You stand frozen"), ((2, 3), "You run from the place at once"), ((4, 4), "You stay calm")])

    def test_a_table_of_named_columns_says_what_each_cell_is_and_a_footnote_goes_with_its_row(self):
        self.assertEqual(self.results("hunting"), [
            ((1, 1), "Hare; Requirement: Weapon or trap; Rations: 1"),
            ((2, 2), "Stag*; Requirement: Weapon; Rations: D6 (* A stag fights back if the roll fails.)")])

    def test_the_half_of_a_table_before_the_bookmark_is_found_by_its_header(self):
        self.assertEqual(self.results("weakness"), [((1, 1), "Vain"), ((2, 2), "Proud"), ((3, 3), "Greedy"), ((4, 4), "Lazy")])

    def test_a_box_of_the_book_with_a_table_in_it_is_read_under_its_own_bookmark(self):
        self.assertEqual(self.results("severe_injuries"), [((1, 2), "Bruise; Effect: Bane on AWARENESS."), ((3, 4), "Limp; Effect: Movement is halved.")])

    def test_dice_across_the_top_are_a_table_to_each_and_the_first_rolls_the_others_after_it(self):
        self.assertEqual(self.results("quest_when")[:2], [((1, 1), "at dusk"), ((2, 2), "by the well")])
        self.assertEqual([row["then"] for row in self.table("quest_when")["results"]], [["quest_hook", "quest_patron", "quest_goal", "quest_object", "quest_name"]] * 4)
        self.assertEqual((self.table("quest_hook")["formula"], self.results("quest_hook")), ("1d3", [((1, 1), "a stranger"), ((2, 2), "a note"), ((3, 3), "a rumor")]))
        self.assertEqual(self.results("quest_name")[3], ((4, 4), "Late Map"))
        self.assertNotIn("then", self.table("quest_name")["results"][0])

    def test_the_pack_says_where_each_table_went_and_the_audit_reads_them_back_against_the_book(self):
        self.assertEqual(self.pack.items["table_hunting"]["to"], ["tables/hunting"])
        self.assertEqual(self.pack.items["table_the_quest"]["to"], [f"tables/quest_{part}" for part in ("when", "hook", "patron", "goal", "object", "name")])
        self.pack.write(self.tmp / "extract")
        report = audit.audit(self.tmp / "out", "system")
        self.assertEqual(report["unclaimed"], [])
        self.assertEqual(report["problems"], [])
        # Read back against the made-up book's own pages, every table, number and word is on them.
        self.assertEqual(report["unverified"], [])


class SentenceColumnsTest(unittest.TestCase):
    def test_a_table_of_dice_with_fewer_columns_than_the_importer_names_says_so(self):
        with tempfile.TemporaryDirectory() as folder:
            made = FakeBook(Path(folder) / "extract")
            made.line(1, 80, "THE JOURNEY", x=250, style=BANNER)
            made.mark(1, "Table: The Journey")
            for mark, x in zip(["D4", "D4"], [104, 184]):
                made.line(1, 100, mark, x, HEADER)
            for row, cells in enumerate([["long", "at a ford"], ["short", "at a bridge"], ["wet", "at a gate"], ["dry", "at a cave"]]):
                made.line(1, 120 + 17 * row, str(row + 1), 70, CELL)
                for cell, x in zip(cells, [100, 180]):
                    made.line(1, 120 + 17 * row, cell, x, CELL)
            made.save()
            book = Book(Path(folder) / "extract")
            pack = Pack(book, Path(folder) / "out", dragonbane_core.NAME)
            tables._sentence(pack, book.find("Table: The Journey"), "The Journey")
            self.assertEqual(sorted(path for path in pack.files), ["tables/journey_end.toml", "tables/journey_kind.toml"])
            self.assertEqual(pack.notes, ["The Journey (p. 1): the book's table has 2 columns of dice and the importer names 6: no table is written for the last 4"])


class GearRecipeTest(unittest.TestCase):
    """Chapter 6 of a made-up book: the bookmarks and columns of the real one, invented things."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        made = FakeBook(self.tmp / "extract")
        made.line(1, 80, "YOUR HERO", style=HEADING)
        made.mark(1, "2. Your Player Character")
        made.line(1, 100, "GEAR", style=HEADING)
        made.mark(2, "Gear")
        made.line(1, 120, "COINS", x=150, style=BANNER)
        made.mark(3, "Sidebar: Coins")
        made.lines(1, 140, "Ten copper coins equal one silver, and ten silver coins equal one gold.", style=CELL)
        made.line(2, 80, "SKILLS", style=HEADING)
        made.mark(1, "3. Skills")
        made.line(2, 100, "THE CORE SKILLS", style=HEADING)
        made.mark(2, "The Core Skills")
        made.line(2, 120, "WEAPON SKILLS (STR/AGL)", style=HEADING)
        made.mark(3, "Weapon Skills")
        made.line(2, 140, "Swords (STR): Used for swords.")
        made.mark(4, "Swords")
        made.line(2, 152, "Bows (AGL): Used for bows.")
        made.mark(4, "Bows")
        made.line(3, 80, "GEAR", style=HEADING)
        made.mark(1, "6. Gear")
        made.line(3, 100, "MELEE WEAPONS", x=250, style=BANNER)
        made.mark(2, "Table: Melee Weapons")
        xs = [68, 150, 185, 215, 260, 310, 375, 430, 490]
        names = ["WEAPON", "GRIP", "STR", "RANGE", "DAMAGE", "DURABILITY", "COST", "SUPPLY", "FEATURES"]
        made.table(3, 120, names, [
            ["Sword, Long", "1H", "9", "2", "2D6", "14", "11 gold", "Common", "Piercing, slashing"],
            ["Stick", "2H", "—", "STR", "D4", "—", "—", "—", "Bludgeoning, can be thrown"],
        ], xs)
        made.line(3, 200, "RANGED WEAPONS", x=250, style=BANNER)
        made.mark(2, "Table: Ranged Weapons")
        made.table(3, 220, names, [
            ["Bow, Long", "2H", "12", "90", "D12", "5", "40 gold", "Uncommon", "Piercing, requires quiver"],
        ], xs)
        made.line(3, 300, "ARMOR & HELMETS", x=250, style=BANNER)
        made.mark(2, "Table: Armor & Helmets")
        made.table(3, 320, ["ARMOR", "ARMOR RATING", "COST", "SUPPLY", "EFFECT"], [
            ["Leather", "1", "2 gold", "Common", "—"],
            ["Plate Armor", "5", "400 gold", "Rare", "Bane on EVADE, and SNEAKING rolls."],
            ["Great Helm", "+2", "35 gold", "Common", "Bane on AWARENESS and ranged attacks."],
        ], [68, 150, 240, 290, 350])
        made.line(3, 400, "SERVICES", x=250, style=BANNER)
        made.mark(2, "Table: Services")
        made.table(3, 420, ["SERVICE", "COST", "SUPPLY", "EFFECT"], [["Guide", "3 gold/day", "Common", "Leads the way."], ["Curse", "2 gold × potency", "Rare", "See the chapter."]], [68, 150, 250, 300])
        made.save(pages=True)
        self.book = Book(self.tmp / "extract")
        self.pack = Pack(self.book, self.tmp / "out", dragonbane_core.NAME, dragonbane_core.extends(None))
        dragonbane_core.gear.build(self.pack)

    def test_a_weapon_row_becomes_a_weapon_with_its_skill_and_what_the_table_says(self):
        sword = self.pack.system["weapons"]["long_sword"]
        self.assertEqual(sword, {"skill": "swords", "damage": "2d6", "bonus": "str", "grip": 1, "str": 9, "range": 2, "durability": 14,
                                 "features": ["piercing", "slashing"]})

    def test_a_thrown_weapons_range_is_the_heros_strength_and_a_bow_needs_a_quiver(self):
        stick = self.pack.system["weapons"]["stick"]
        self.assertEqual((stick["range"], stick["features"], "durability" in stick, "str" in stick), ("str", ["bludgeoning", "thrown"], False, False))
        bow = self.pack.system["weapons"]["long_bow"]
        self.assertEqual((bow["skill"], bow["bonus"], bow["range"], bow["ranged"], bow["parry"]), ("bows", "agl", 90, True, False))

    def test_armor_has_a_rating_and_the_skills_it_puts_a_bane_on(self):
        self.assertEqual(self.pack.system["armor"], {"leather_armor": 1, "plate_armor": 5, "great_helm": 2})
        gear = self.pack.gear["gear"]
        self.assertEqual(gear["plate_armor"]["banes"], ["evade", "sneaking"])
        self.assertEqual(gear["great_helm"]["banes"], ["awareness", "ranged_attack"])
        self.assertNotIn("banes", gear["leather_armor"])

    def test_prices_are_as_the_book_writes_them_and_one_it_doesnt_say_is_varies_with_a_note(self):
        gear = self.pack.gear["gear"]
        self.assertEqual((gear["long_sword"]["price"], gear["long_sword"]["supply"]), ("11 gold", "common"))
        self.assertEqual((gear["stick"]["price"], gear["stick"]["note"]), ("varies", "The book prints no price. Bludgeoning, can be thrown"))
        self.assertEqual((gear["guide"]["price"], gear["guide"]["note"]), ("3 gold", "Per day. Leads the way."))
        self.assertEqual((gear["curse"]["price"], gear["curse"]["note"]), ("varies", "Price: 2 gold × potency. See the chapter."))

    def test_the_coins_come_from_the_sidebar_and_the_pack_says_where_each_thing_went(self):
        self.assertEqual(self.pack.gear["money"]["coins"], {"gold": 100, "silver": 10, "copper": 1})
        item = self.pack.items["gear_melee_weapons"]
        self.assertEqual((item["kind"], item["pages"], "gear.toml:gear.long_sword" in item["to"], "system.toml:weapons.long_sword" in item["to"]), ("gear", [3], True, True))
        self.assertIn("system.toml:armor", self.pack.items["gear_armor_and_helmets"]["to"])

    def test_the_pack_is_written_and_the_audit_reads_its_gear_back_against_the_book(self):
        self.pack.write(self.tmp / "extract")
        report = audit.audit(self.tmp / "out", "system")
        self.assertEqual(report["unclaimed"], [])
        self.assertEqual(report["problems"], [])
        # Every weapon's numbers are on its table's page: a grip of 2 is the page's "2H".
        self.assertEqual(report["unverified"], [])


class ChangedGearTableTest(unittest.TestCase):
    """A weapons table set otherwise than the printing the recipe knows: the import says where, and how."""

    def build(self, names, row):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            made = FakeBook(tmp / "extract")
            made.line(1, 80, "YOUR HERO", style=HEADING)
            made.mark(1, "2. Your Player Character")
            made.line(1, 100, "GEAR", style=HEADING)
            made.mark(2, "Gear")
            made.line(1, 120, "COINS", x=150, style=BANNER)
            made.mark(3, "Sidebar: Coins")
            made.lines(1, 140, "Ten copper coins equal one silver, and ten silver coins equal one gold.", style=CELL)
            made.line(2, 80, "SKILLS", style=HEADING)
            made.mark(1, "3. Skills")
            made.line(2, 100, "THE CORE SKILLS", style=HEADING)
            made.mark(2, "The Core Skills")
            made.line(2, 120, "WEAPON SKILLS", style=HEADING)
            made.mark(3, "Weapon Skills")
            made.line(2, 140, "Swords (STR): Used for swords.")
            made.mark(4, "Swords")
            made.line(3, 80, "GEAR", style=HEADING)
            made.mark(1, "6. Gear")
            made.line(3, 100, "MELEE WEAPONS", x=250, style=BANNER)
            made.mark(2, "Table: Melee Weapons")
            made.table(3, 120, names, [row], [68, 150, 185, 215, 260, 310, 375, 430, 490][:len(names)])
            made.save()
            pack = Pack(Book(tmp / "extract"), tmp / "out", dragonbane_core.NAME, dragonbane_core.extends(None))
            dragonbane_core.gear.build(pack)
            return pack

    def test_a_column_the_table_lost_is_named_with_the_table_and_its_page(self):
        with self.assertRaisesRegex(SoloError, r"Test Book.pdf, 'Table: Melee Weapons' \(p. 3\): the table on p. 3 has no DURABILITY column; "
                                               r"this may be another printing than the importer was written for"):
            self.build(["WEAPON", "GRIP", "STR", "RANGE", "DAMAGE", "COST", "SUPPLY", "FEATURES"], ["Sword, Long", "1H", "9", "2", "2D6", "11 gold", "Common", "Slashing"])

    def test_a_grip_written_out_is_a_grip_and_the_weapon_a_weapon(self):
        names = ["WEAPON", "GRIP", "STR", "RANGE", "DAMAGE", "DURABILITY", "COST", "SUPPLY", "FEATURES"]
        for grip, hands in (("1-handed", 1), ("Two-handed", 2), ("2 H", 2)):
            pack = self.build(names, ["Sword, Long", grip, "9", "2", "2D6", "14", "11 gold", "Common", "Slashing"])
            self.assertEqual(pack.system["weapons"]["long_sword"]["grip"], hands, grip)


class BuildTest(unittest.TestCase):
    """books.build with a made-up recipe in place of the real ones: what it writes, and what it keeps when a build goes wrong."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        made = FakeBook(self.tmp / "extract")
        made.line(1, 80, "LANTERNS", style=HEADING)
        made.mark(1, "1. Lanterns")
        made.save()
        self.builds, self.stop, self.playable, self.readable = 0, None, True, True

        def build(pack):
            self.builds += 1
            if self.stop:
                raise SoloError(self.stop)
            pack.system.update({"name": "Lanterns", "build": self.builds, **({"family": "d20-under"} if self.playable else {})})
            pack.item("lanterns", "Lanterns", "mechanic", [1], ["system.toml:build"])
            if not self.readable:
                pack.file("tables/wick.toml", "name = \n")

        recipe = types.SimpleNamespace(NAME="Lanterns", PACK="lanterns", recognizes=lambda book: True, extends=lambda folder: None, build=build)
        patch = unittest.mock.patch.object(books, "recipes", lambda: (recipe,))
        patch.start()
        self.addCleanup(patch.stop)
        self.systems = self.tmp / "systems"
        books.build(self.tmp / "extract", systems=self.systems)

    def built(self):
        return tomllib.loads((self.systems / "lanterns" / "system.toml").read_text(encoding="utf-8"))["build"]

    def test_replace_builds_again_and_leaves_nothing_beside_the_pack(self):
        books.build(self.tmp / "extract", systems=self.systems, replace=True)
        self.assertEqual((self.built(), sorted(path.name for path in self.systems.iterdir())), (2, ["lanterns"]))

    def test_the_inventory_keeps_an_extract_under_solo_home_relative_to_it(self):
        with unittest.mock.patch.dict(os.environ, {"SOLO_HOME": str(self.tmp)}):
            books.build(self.tmp / "extract", systems=self.systems, replace=True)
        self.assertIn('extract = "extract"\n', (self.systems / "lanterns" / "inventory.toml").read_text(encoding="utf-8"))

    def test_a_build_that_fails_keeps_the_pack_that_was_there(self):
        self.stop = "a section the recipe expects isn't there"
        with self.assertRaisesRegex(SoloError, "a section the recipe expects"):
            books.build(self.tmp / "extract", systems=self.systems, replace=True)
        self.assertEqual((self.built(), sorted(path.name for path in self.systems.iterdir())), (1, ["lanterns"]))

    def test_a_system_pack_the_engine_cant_play_is_refused_and_the_old_one_kept(self):
        self.playable = False
        with self.assertRaisesRegex(SoloError, r"lanterns was built, and the engine says it can't be played \(the pack that was there is kept\):\n  system: family"):
            books.build(self.tmp / "extract", systems=self.systems, replace=True)
        self.assertEqual((self.built(), sorted(path.name for path in self.systems.iterdir())), (1, ["lanterns"]))

    def test_a_pack_the_engine_cant_even_load_leaves_nothing_half_built_beside_the_old_one(self):
        # The library lists every folder of systems/ that has a system.toml: one left half built would show up as a pack of its own.
        self.readable = False
        with self.assertRaisesRegex(SoloError, r"can't parse .*wick\.toml"):
            books.build(self.tmp / "extract", systems=self.systems, replace=True)
        self.assertEqual((self.built(), sorted(path.name for path in self.systems.iterdir())), (1, ["lanterns"]))


class RepositoryTest(unittest.TestCase):
    def test_no_importer_writes_into_the_repository(self):
        said = r"is inside the repository: a book's text stays out of it"
        with tempfile.TemporaryDirectory() as folder:
            # A stand-in for the repository, so that an importer that would write into it writes here.
            repository = Path(folder) / "repository"
            inside = repository / "packs" / "from-a-book"
            made = FakeBook(Path(folder) / "extract")
            made.line(1, 80, "LANTERNS", style=HEADING)
            made.mark(1, "1. Lanterns")
            made.save()
            recipe = types.SimpleNamespace(NAME="Lanterns", PACK="lanterns", recognizes=lambda book: True, extends=lambda folder: None, build=lambda pack: None)
            with unittest.mock.patch.object(library, "REPO", repository.resolve()), unittest.mock.patch.object(books, "recipes", lambda: (recipe,)):
                for kind, out in (("out", inside), ("systems", repository / "packs")):
                    with self.assertRaisesRegex(SoloError, said):
                        books.build(Path(folder) / "extract", **{kind: out})
                with self.assertRaisesRegex(SoloError, said):
                    audit.scaffold(inside, Path(folder) / "extract")
                with self.assertRaisesRegex(SoloError, said):
                    booktables.write("1-3 Rain\n4-6 Sun\n", inside / "tables" / "weather.toml")
                for write in (lambda: foundry.import_adventure([], inside), lambda: foundry.import_rules([], inside),
                              lambda: foundry.import_character([], inside / "hero.json", system={})):
                    with self.assertRaisesRegex(SoloError, said):
                        write()
            self.assertFalse(repository.exists())


class ImportBookCliTest(CliCase):
    """`solo import book` on a folder of PDFs, `solo extract` stood in for: a book it can't read or doesn't know is said, the rest go on, and the
    import fails at the end."""

    def extract(self, pdf, out=None, tables=True):
        pdf = Path(pdf)
        if pdf.stem == "torn":
            raise SoloError(f"can't open {pdf}: it isn't a PDF")
        made = FakeBook(self.tmp / "sources" / pdf.stem, source=pdf.name)
        if pdf.stem == "scan":
            made.pages = {page: [] for page in (1, 2, 3)}
        else:
            made.line(1, 80, "LANTERNS", style=HEADING)
            made.mark(1, "1. Lanterns")
            made.line(2, 80, "Words on the second page of a book no importer knows.")
        made.save()
        return made.folder, {"pages": 3}

    def test_a_book_that_cant_be_read_or_that_no_importer_knows_fails_the_import_after_the_others(self):
        books_folder = self.tmp / "books"
        books_folder.mkdir()
        for name in ("lanterns.pdf", "scan.pdf", "torn.pdf"):
            (books_folder / name).write_bytes(b"%PDF")
        with unittest.mock.patch("solo.extract.extract", self.extract):
            code, out, err = self.solo("import", "book", str(books_folder))
        self.assertEqual(code, 1, out + err)
        # The torn PDF comes between the other two, and they are read all the same.
        self.assertIn("torn.pdf: can't open", out)
        self.assertIn(f"lanterns.pdf: no importer knows this book, or this printing of it (it has 1 bookmark, fingerprint {Book(self.tmp / 'sources' / 'lanterns').fingerprint()[:16]})", out)
        self.assertIn("scan.pdf: no importer knows this book, or this printing of it (it has 0 bookmarks, fingerprint e3b0c44298fc1c14). "
                      "3 of its 3 pages have no text, so it looks scanned: run ocrmypdf on the PDF and import it again.", out)
        self.assertIn("not every book became a pack: torn.pdf (it can't be read); lanterns (no importer knows it); scan (no importer knows it)", err)


if __name__ == "__main__":
    unittest.main()
