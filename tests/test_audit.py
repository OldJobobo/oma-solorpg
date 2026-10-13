import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from test_cli import CliCase

from solo import SoloError, audit


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


def make_adventure(root):
    write(root / "adventure.toml", """
        title = "The Test Crypt"
        system = "dragonbane"
        start = "gate"

        [clocks.flood]
        label = "The flood"
        segments = 4

        [scenes.gate]
        title = "The Gate"
        exits = { crypt = "Down" }

        [scenes.crypt]
        title = "The Crypt"
        """)
    write(root / "scenes" / "gate.md", "A gate.\n")
    write(root / "npcs" / "ghoul.toml", 'name = "Ghoul"\n')
    write(root / "tables" / "omens.toml", 'name = "Omens"\nformula = "1d6"\nresults = [{ range = [1, 6], text = "Dripping" }]\n')
    write(root / "rules" / "drowning.md", "# Drowning\n")


def make_extract(root, pages):
    """What solo extract writes, for the parts the audit reads: pages with text, a manifest, chapters."""
    for number, text in pages.items():
        write(root / "pages" / f"{number:04d}.txt", text)
    write(root / "manifest.json", json.dumps({"source": "crypt.pdf", "pages": len(pages)}))
    write(root / "toc.json", json.dumps([
        {"level": 1, "title": "Credits", "start": 1, "end": 1},
        {"level": 1, "title": "The Crypt", "start": 2, "end": 4},
    ]))


LONG = "Enough text on this page that it is clearly a page of the book, not a stray number.\n"


class AuditTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        self.pack = self.tmp / "crypt"
        make_adventure(self.pack)
        self.book = self.tmp / "source"
        make_extract(self.book, {1: LONG, 2: LONG, 3: LONG + "Omens (D6)\n1–6 Dripping, somewhere below.\n", 4: "12\n"})

    def inventory(self, items):
        write(self.pack / "inventory.toml", f'source = "The Test Crypt"\nextract = "{self.book}"\n\n' + textwrap.dedent(items))
        return audit.audit(self.pack, "adventure")

    COMPLETE = """
        [items.credits]
        kind = "other"
        pages = [1]
        status = "skipped"
        note = "credits"

        [items.the_crypt]
        kind = "place"
        pages = ["2-3"]
        status = "mapped"
        to = ["scenes/gate", "scenes/crypt.md", "adventure.toml:clocks.flood", "tables/omens.toml"]

        [items.ghoul]
        kind = "creature"
        pages = [3]
        status = "mapped"
        to = ["npcs/ghoul"]

        [items.drowning]
        kind = "mechanic"
        status = "house"
        to = ["rules/drowning.md"]
        note = "the book gives no rule for it: a CON roll a round"
        """

    def test_a_complete_inventory_passes(self):
        report = self.inventory(self.COMPLETE)
        self.assertFalse(audit.failed(report), audit.render(report))
        self.assertEqual(report["counts"], {"mapped": 2, "house": 1, "engine": 0, "skipped": 1, "todo": 0})
        text = audit.render(report)
        self.assertIn("Everything is accounted for.", text)
        # Page 4 holds a page number and nothing else: there is nothing on it to cite.
        self.assertIn("3 of 3 pages with text are cited", text)

    def test_a_tables_own_dice_need_not_be_printed_but_its_results_must_be(self):
        make_extract(self.book, {1: LONG, 2: LONG, 3: LONG + "Omens\n1-6 Dripping, somewhere below.\n", 4: "12\n"})
        self.assertFalse(audit.failed(self.inventory(self.COMPLETE)))
        make_extract(self.book, {1: LONG, 2: LONG, 3: LONG + "Omens\n1-6 Silence.\n", 4: "12\n"})
        report = self.inventory(self.COMPLETE)
        self.assertEqual(report["unverified"], ['the_crypt: tables/omens.toml result 1-6 "Dripping" isn\'t on p. 2-3 (no dripping)'])

    def test_a_page_read_from_its_picture_stands_in_for_text_the_pdf_lacks(self):
        write(self.book / "pages" / "0003.txt", LONG)  # the PDF says nothing of the table: it is art
        self.assertTrue(self.inventory(self.COMPLETE)["unverified"])
        write(self.book / "picture" / "0003.txt", "1-6 Dripping\n")
        report = self.inventory(self.COMPLETE)
        self.assertEqual((report["unverified"], report["pages"]["pictures"]), ([], [3]))
        self.assertIn("Read from the pictures", audit.render(report))

    def test_a_dice_multiplier_is_read_back_too(self):
        write(self.pack / "tables" / "loot.toml", 'name = "Loot"\nformula = "1d2"\nresults = [{ range = [1, 1], text = "{value} silver coins", roll = "2d6x10" }, { range = [2, 2], text = "Nothing" }]\n')
        items = self.COMPLETE + '\n[items.loot]\nkind = "table"\npages = [4]\nstatus = "mapped"\nto = ["tables/loot.toml"]\n'
        write(self.book / "pages" / "0004.txt", LONG + "2D6 \u00d7 5 silver coins. Nothing at all.\n")
        self.assertTrue(any("2d6x10" in line for line in self.inventory(items)["unverified"]))
        write(self.book / "pages" / "0004.txt", LONG + "2D6 \u00d7 10 silver coins. Nothing at all.\n")
        self.assertEqual(self.inventory(items)["unverified"], [])

    def test_a_deck_is_read_a_card_to_a_page_choices_and_numbers_included(self):
        write(self.book / "pages" / "0003.txt", LONG + "Omens (D6)\n1\u20136 Dripping, somewhere below.\nLantern. Roll D6: 1: brass, 2: iron. Worth 2D6 copper.\n")
        write(self.book / "pages" / "0004.txt", LONG + "Poison. Potency 12. Suffer D6 x 10 damage.\n")
        items = self.COMPLETE + '\n[items.loot]\nkind = "table"\npages = [3, 4]\nstatus = "mapped"\nto = ["tables/loot.toml"]\n'

        def deck(second="iron", potency=12, roll="1d6x10"):
            write(self.pack / "tables" / "loot.toml", "name = 'Loot'\nformula = '1d2'\nresults = [\n"
                  f"  {{ range = [1, 1], page = 3, text = 'Lantern', choices = ['brass', '{second}'] }},\n"
                  f"  {{ range = [2, 2], page = 4, text = 'Poison, Potency {potency}', roll = '{roll}' }},\n]\n")
            return self.inventory(items)["unverified"]

        self.assertEqual(deck(), [])
        self.assertIn("\"silver\" isn't on p. 3", deck(second="silver")[0])
        self.assertIn("(no 13)", deck(potency=13)[0])
        # 2D6 is on the other card, and a result answers for its own page only.
        self.assertEqual(deck(roll="2d6"), ["loot: tables/loot.toml has 2d6, and p. 4 never says it"])
        self.assertEqual(deck(roll="1d6x5"), ["loot: tables/loot.toml has d6x5, and p. 4 never says it"])

    def test_the_columns_of_an_attack_table_are_read_too(self):
        items = self.COMPLETE + '\n[items.raids]\nkind = "table"\npages = [3]\nstatus = "mapped"\nto = ["tables/raids.toml"]\n'

        def raids(said):
            write(self.pack / "tables" / "raids.toml", f"name = 'Raids'\nformula = '1d6'\nresults = [{{ range = [1, 6], melee = {{ text = '{said}', attack = true }} }}]\n")
            return self.inventory(items)["unverified"]

        self.assertEqual(raids("Dripping somewhere"), [])
        self.assertEqual(len(raids("Screeching somewhere")), 1)

    def test_a_word_split_by_a_soft_hyphen_is_still_on_the_page(self):
        make_extract(self.book, {1: LONG, 2: LONG, 3: LONG + "Omens\n1-6 Drip\u00ad\nping, somewhere below.\n", 4: "12\n"})
        self.assertEqual(self.inventory(self.COMPLETE)["unverified"], [])

    def test_a_mechanic_only_in_rules_pages_is_pointed_out(self):
        report = self.inventory(self.COMPLETE.replace('status = "house"', 'status = "mapped"\npages = [3]'))
        self.assertEqual([i["id"] for i in report["prose_only"]], ["drowning"])
        self.assertFalse(audit.failed(report))
        self.assertIn("## Mechanics only in rules pages (1)\n", audit.render(report))

    def test_pack_content_no_item_claims_is_reported(self):
        report = self.inventory(self.COMPLETE.replace('"npcs/ghoul"', '"skill:solo-gm"'))
        self.assertEqual(report["unclaimed"], ["npcs/ghoul"])
        self.assertTrue(audit.failed(report))
        self.assertIn("- npcs/ghoul", audit.render(report))

    def test_references_must_name_something_in_the_pack(self):
        report = self.inventory(self.COMPLETE.replace('"npcs/ghoul"', '"npcs/ghoul", "npcs/wight", "adventure.toml:clocks.tide", "scenes/vault", "skill:nope"'))
        self.assertEqual(sorted(report["problems"]), [
            "item ghoul: to 'adventure.toml:clocks.tide': no key 'clocks.tide' in adventure.toml",
            "item ghoul: to 'npcs/wight': no such file",
            "item ghoul: to 'scenes/vault': no such scene",
            "item ghoul: to 'skill:nope': no skill called 'nope'",
        ])

    def test_each_status_asks_for_what_it_needs(self):
        report = self.inventory("""
            [items.a]
            kind = "mechanic"
            pages = [2]
            status = "mapped"

            [items.b]
            kind = "spell"
            pages = [2]
            status = "engine"

            [items.c]
            kind = "other"
            status = "skipped"

            [items.d]
            kind = "gadget"
            pages = ["5-3"]
            status = "done"
            """)
        self.assertEqual(sorted(report["problems"]), sorted([
            "item a: mapped but `to` names nothing in the pack",
            "item b: engine needs a note saying what the engine needs to run it",
            "item c: skipped needs a note saying why it's left out",
            "item c: no pages (every item from the book cites where it is)",
            "item d: status 'done', expected one of mapped, house, engine, skipped, todo",
            "item d: kind 'gadget', expected one of " + ", ".join(audit.KINDS),
            "item d: page range '5-3' runs backwards",
            "item d: no pages (every item from the book cites where it is)",
        ]))

    def test_todo_items_and_uncited_pages_fail_by_chapter(self):
        report = self.inventory("""
            [items.ghoul]
            kind = "creature"
            pages = [3]
            status = "todo"
            """)
        self.assertEqual([i["id"] for i in report["todo"]], ["ghoul"])
        self.assertEqual(report["pages"]["uncited"], [1, 2])
        text = audit.render(report)
        self.assertIn("## Not decided yet (1)\n- ghoul: Ghoul (p. 3)", text)
        self.assertIn("- Credits (p. 1): 1", text)
        self.assertIn("- The Crypt (p. 2-4): 2", text)

    def test_pages_past_the_end_are_wrong(self):
        report = self.inventory(self.COMPLETE.replace("pages = [3]", "pages = [3, 9]"))
        self.assertEqual(report["pages"]["beyond"], [9])
        self.assertTrue(audit.failed(report))

    def test_without_an_extract_the_pages_go_unchecked(self):
        write(self.pack / "inventory.toml", textwrap.dedent(self.COMPLETE))
        report = audit.audit(self.pack, "adventure")
        self.assertIsNone(report["pages"])
        self.assertFalse(audit.failed(report))
        self.assertIn("Not checked", audit.render(report))

    def test_a_pack_without_an_inventory(self):
        with self.assertRaisesRegex(SoloError, "no inventory.toml"):
            audit.audit(self.pack, "adventure")

    def test_page_lists_and_spans(self):
        self.assertEqual(audit.parse_pages([7, "2-4", "3"]), [2, 3, 4, 7])
        self.assertEqual(audit.spans([1, 2, 3, 7, 9, 10]), "1-3, 7, 9-10")
        with self.assertRaises(ValueError):
            audit.parse_pages(["p. 4"])


class SystemAuditTest(unittest.TestCase):
    def test_sections_of_tables_are_claimed_entry_by_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            pack = Path(folder) / "game"
            write(pack / "system.toml", """
                format = 1
                name = "Game"
                family = "d20-under"
                untrained = 5

                [attributes]
                str = "Strength"

                [weapons]
                dagger = { skill = "knives", damage = "1d8" }
                sword = { skill = "swords", damage = "1d10" }

                [foundry]
                attributes = "x"
                """)
            write(pack / "inventory.toml", """
                [items.weapons]
                kind = "gear"
                pages = [40]
                status = "mapped"
                to = ["system.toml:weapons.dagger", "system.toml:attributes"]
                """)
            report = audit.audit(pack, "system")
        # name, family, format and foundry describe the pack, not the game
        self.assertEqual(report["unclaimed"], ["system.toml:untrained", "system.toml:weapons.sword"])


class BookCheckTest(unittest.TestCase):
    """A small rules pack true to its three pages, and the ways a copy can go wrong that the audit has to see:
    each test changes one thing in the pack (or the book) and the audit must fail on it, naming it."""

    PAGES = {
        1: "FEAR TABLE\nD6 EFFECT\n1 Shakes and drops what they hold.\n2 Runs away screaming into the night.\n3-6 Freezes on the spot for a round.\n"
           "A long sword has durability 12, STR 10, range 2, damage 2D8. Resting heals D6 HP. A dagger does D4.\n",
        2: "FIREBOLT. Rank 1. The spell inflicts 2D6 damage to one target. It can be dodged.\n",
        3: "GHOUL. Ferocity: 2 Movement: 10 Armor: 4 HP: 18. Its claws do 2D6 damage. It has 4 friends and 12 teeth.\n",
    }

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        self.book, self.pack = self.tmp / "extract", self.tmp / "pack"
        for number, text in self.PAGES.items():
            write(self.book / "pages" / f"{number:04d}.txt", text)
        write(self.book / "manifest.json", json.dumps({"source": "made.pdf", "pages": 3}))
        write(self.book / "toc.json", json.dumps([{"level": 1, "title": "Rules", "start": 1, "end": 3}]))
        write(self.pack / "system.toml", """
            format = 1
            extends = "bundled:dragonbane"

            [weapons.long_sword]
            skill = "swords"
            damage = "2d8"
            str = 10
            range = 2
            durability = 12

            [rest.stretch]
            label = "Stretch rest"
            recover = { hp = "1d6" }
            time = { stretch = 1 }
            """)
        write(self.pack / "tables" / "fear.toml", """
            name = "Fear"
            formula = "1d6"
            results = [
              { range = [1, 1], text = "Shakes and drops what they hold." },
              { range = [2, 2], text = "Runs away screaming into the night." },
              { range = [3, 6], text = "Freezes on the spot for a round." },
            ]
            """)
        write(self.pack / "bestiary" / "ghoul.toml", """
            name = "Ghoul"
            role = "A monster"
            description = "Claws."
            attack = { label = "Claws", value = 12, damage = "2d6" }
            stats = { hp = 18, armor = 4, ferocity = 2, movement = 10 }
            """)
        write(self.pack / "spells" / "firebolt.toml", """
            name = "Firebolt"
            school = "elementalism"
            rank = 1
            damage = "2d6"
            avoid = ["dodge"]
            source = "p. 2"
            """)
        write(self.pack / "inventory.toml", f"""
            source = "Made"
            extract = "{self.book}"

            [items.rules]
            kind = "mechanic"
            pages = [1]
            status = "mapped"
            to = ["system.toml:weapons", "system.toml:rest", "tables/fear"]

            [items.spells]
            kind = "spell"
            pages = [2]
            status = "mapped"
            to = ["spells/firebolt"]

            [items.ghoul]
            kind = "creature"
            pages = [3]
            status = "mapped"
            to = ["bestiary/ghoul"]
            """)

    def change(self, name, old, new):
        """The audit's findings once `old` is `new` in the pack's file `name` (the book's, for pages/)."""
        path = (self.book if name.startswith("pages/") else self.pack) / name
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")
        report = audit.audit(self.pack, "system")
        self.assertTrue(audit.failed(report), f"{name}: {old!r} -> {new!r} passed the audit")
        return "\n".join(report["problems"] + report["unclaimed"] + report["unverified"])

    def test_the_pack_true_to_its_pages_passes(self):
        report = audit.audit(self.pack, "system")
        self.assertFalse(audit.failed(report), audit.render(report))

    def test_two_rows_of_a_table_swapped_are_each_on_the_others_row(self):
        found = self.change("tables/fear.toml", 'text = "Shakes and drops what they hold." },\n  { range = [2, 2], text = "Runs away screaming into the night." }',
                            'text = "Runs away screaming into the night." },\n  { range = [2, 2], text = "Shakes and drops what they hold." }')
        self.assertIn('rules: tables/fear result 1 "Runs away screaming into the night." is row 2 on p. 1, not row 1', found)
        self.assertIn('rules: tables/fear result 2 "Shakes and drops what they hold." is row 1 on p. 1, not row 2', found)

    def test_a_word_put_into_a_row_is_found_on_its_row(self):
        found = self.change("tables/fear.toml", '"Runs away', '"Never runs away')
        self.assertIn('rules: tables/fear result 2 "Never runs away screaming into the night." isn\'t on p. 1 (no never)', found)

    def test_a_table_rolled_on_another_die_than_its_rows(self):
        found = self.change("tables/fear.toml", 'formula = "1d6"', 'formula = "1d20"')
        self.assertIn("rules: tables/fear rolls 1d20 (1-20), and its results, the rows of p. 1, run 1-6", found)

    def test_a_row_that_says_something_else(self):
        found = self.change("tables/fear.toml", '"Freezes on the spot for a round."', '"Resting heals a long sword."')
        self.assertIn('rules: tables/fear result 3-6 "Resting heals a long sword." isn\'t what row 3-6 on p. 1 says ("freezes on the spot for a round")', found)

    def test_a_range_the_page_does_not_print(self):
        found = self.change("tables/fear.toml", '{ range = [2, 2], text = "Runs away screaming into the night." },\n  { range = [3, 6]',
                            '{ range = [2, 3], text = "Runs away screaming into the night." },\n  { range = [4, 6]')
        self.assertIn('rules: tables/fear result 2-3 "Runs away screaming into the night." is row 2 on p. 1, not row 2-3', found)
        self.assertIn('rules: tables/fear result 4-6 "Freezes on the spot for a round." is row 3-6 on p. 1, not row 4-6', found)

    def test_a_row_the_page_does_not_print_at_all(self):
        write(self.pack / "tables" / "fear.toml", (self.pack / "tables" / "fear.toml").read_text(encoding="utf-8").replace('"1d6"', '"1d7"'))
        found = self.change("tables/fear.toml", 'round." },\n', 'round." },\n  { range = [7, 7], text = "Resting heals a long sword." },\n')
        self.assertIn('rules: tables/fear result 7 "Resting heals a long sword." has no row 7 on p. 1: the page doesn\'t print that range', found)

    def test_rows_read_from_a_column_of_numbers_or_set_in_two_halves(self):
        # The numbers come out in a column of their own and the words after them: there are no rows to read.
        write(self.book / "pages" / "0001.txt", self.PAGES[1].replace("1 Shakes", "1\n2\n3-6\nShakes").replace("2 Runs", "Runs").replace("3-6 Freezes", "Freezes"))
        self.assertFalse(audit.failed(audit.audit(self.pack, "system")))
        # Two halves side by side: the second half's rows start in the middle of a line.
        write(self.book / "pages" / "0001.txt", self.PAGES[1].replace("hold.\n2 Runs", "hold. 3-6 Freezes on the spot for a round.\n2 Runs")
              .replace("3-6 Freezes on the spot for a round.\nA", "A"))
        report = audit.audit(self.pack, "system")
        self.assertFalse(audit.failed(report), audit.render(report))
        self.assertIn("is row 2", self.change("tables/fear.toml", '"Shakes and drops what they hold."', '"Runs away screaming into the night."'))

    def test_a_weapons_numbers_are_each_on_its_page(self):
        self.assertIn("rules: system.toml:weapons gives long_sword.durability 4, and p. 1 never says it",
                      self.change("system.toml", "durability = 12", "durability = 4"))
        self.assertIn("rules: system.toml:weapons gives long_sword.str 18, and p. 1 never says it", self.change("system.toml", "str = 10", "str = 18"))

    def test_a_number_the_book_writes_in_words_or_with_its_unit_is_on_the_page(self):
        write(self.book / "pages" / "0001.txt", self.PAGES[1].replace("durability 12", "durability twelve").replace("range 2,", "range 2m,"))
        report = audit.audit(self.pack, "system")
        self.assertFalse(audit.failed(report), audit.render(report))

    def test_the_dice_a_rest_recovers_are_the_ones_the_page_gives_hit_points(self):
        # D4 is on the page too, for a dagger: what matters is the die the page puts before HP.
        self.assertIn("rules: system.toml:rest gives stretch.recover.hp d4, and p. 1 says d6 hp",
                      self.change("system.toml", 'recover = { hp = "1d6" }', 'recover = { hp = "1d4" }'))

    def test_a_spells_dice_and_rank_are_on_its_page(self):
        self.assertIn("spells: spells/firebolt has 4d10, and p. 2 never says it", self.change("spells/firebolt.toml", 'damage = "2d6"', 'damage = "4d10"'))
        self.assertIn("spells: spells/firebolt gives rank 5, and p. 2 never says it", self.change("spells/firebolt.toml", "rank = 1", "rank = 5"))

    def test_a_monsters_stats_are_the_ones_their_labels_carry(self):
        # 12 and 2 are both on the page, but not as the ghoul's HP and armor.
        self.assertIn("ghoul: bestiary/ghoul gives stats.hp 12, and p. 3 says hp: 18", self.change("bestiary/ghoul.toml", "hp = 18", "hp = 12"))
        self.assertIn("ghoul: bestiary/ghoul gives stats.armor 2, and p. 3 says armor: 4", self.change("bestiary/ghoul.toml", "armor = 4", "armor = 2"))

    def test_a_stat_the_page_gives_another_way_is_not_judged_by_the_label_alone(self):
        # Armor a recipe adds up from the gear ("Same as armor") beside another monster's "Armor: 2", and HP given in words.
        write(self.book / "pages" / "0003.txt", self.PAGES[3].replace("Armor: 4", "Armor: Same as armor") + "WIGHT. Armor: 2 HP: 30. A ghoul of the deep has more, with 20 HP.\n")
        write(self.pack / "bestiary" / "ghoul.toml", (self.pack / "bestiary" / "ghoul.toml").read_text(encoding="utf-8").replace("hp = 18", "hp = 20"))
        report = audit.audit(self.pack, "system")
        self.assertFalse(audit.failed(report), audit.render(report))

    def test_a_monsters_movement_and_attack_skill_are_on_its_page(self):
        self.assertIn("ghoul: bestiary/ghoul gives stats.movement 99, and p. 3 never says it", self.change("bestiary/ghoul.toml", "movement = 10", "movement = 99"))

    def test_a_number_the_page_has_only_as_another_stat_is_not_the_entrys(self):
        # The page's only 18 is the ghoul's HP, so it is no proof of an attack at skill 18.
        self.assertIn("ghoul: bestiary/ghoul gives attack.value 18, and p. 3 has 18 only as hp: 18", self.change("bestiary/ghoul.toml", "value = 12", "value = 18"))

    def test_pages_with_no_text_are_no_pass(self):
        for number in self.PAGES:
            write(self.book / "pages" / f"{number:04d}.txt", "\n")  # a scanned book: pictures, no text
        found = self.change("bestiary/ghoul.toml", "hp = 18", "hp = 40")
        self.assertIn("ghoul: p. 3 has no text to read the pack against", found)
        self.assertIn("picture/0003.txt", found)
        # What an agent read off the page's picture is text the audit reads.
        write(self.book / "picture" / "0003.txt", self.PAGES[3])
        self.assertIn("ghoul: bestiary/ghoul gives stats.hp 40, and p. 3 never says it", self.change("bestiary/ghoul.toml", "hp = 40", "hp = 40"))

    def test_a_page_of_a_few_words_is_read_and_not_taken_for_a_scan(self):
        write(self.book / "pages" / "0002.txt", "FIREBOLT\nRank 1. 2D6.\n")
        report = audit.audit(self.pack, "system")
        self.assertFalse(audit.failed(report), audit.render(report))

    def test_a_spell_no_item_claims_is_unclaimed(self):
        write(self.pack / "spells" / "doom.toml", 'name = "Doom"\nschool = "elementalism"\nrank = 2\n')
        report = audit.audit(self.pack, "system")
        self.assertEqual(report["unclaimed"], ["spells/doom"])


class PriceAuditTest(unittest.TestCase):
    """A price is read back beside its item's name, not only found somewhere on the page."""

    ROWS = [("Dagger", "1 gold"), ("Longsword", "25 gold"), ("Mace", "8 gold"), ("Staff", "2 silver"), ("Shield", "4 gold"), ("Lance", "12 gold")]
    PAGE = LONG + "".join(f"{name} {price} Common Some features.\n" for name, price in ROWS)

    def audit(self, prices=None, names=None, page=None):
        prices = prices or dict(self.ROWS)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pack, book = root / "game", root / "book"
            make_extract(book, {1: LONG, 2: page or self.PAGE})
            write(pack / "system.toml", 'name = "Game"\nfamily = "d20-under"\nuntrained = 5\n')
            entries = "".join(f'[gear.{n.lower()}]\nname = "{(names or {}).get(n, n)}"\nprice = "{prices[n]}"\n\n' for n, _ in self.ROWS)
            write(pack / "gear.toml", '[money]\ncoins = { gold = 100, silver = 10, copper = 1 }\n\n' + entries)
            refs = ", ".join(f'"gear.toml:gear.{n.lower()}"' for n, _ in self.ROWS)
            write(pack / "inventory.toml", f'source = "Test"\nextract = "{book}"\n' + textwrap.dedent(f"""
                [items.credits]
                kind = "other"
                pages = [1]
                status = "skipped"
                note = "credits"

                [items.gear]
                kind = "gear"
                pages = [2]
                status = "mapped"
                to = [{refs}, "gear.toml:money", "system.toml:untrained"]
                """))
            return audit.audit(pack, "system")["unverified"]

    def test_prices_beside_their_names_pass(self):
        self.assertEqual(self.audit(), [])

    def test_a_plausible_price_on_the_wrong_row_is_caught(self):
        # Both numbers are on the page, so a check that asks only that can't tell the rows apart.
        found = self.audit({**dict(self.ROWS), "Dagger": "25 gold", "Longsword": "1 gold"})
        self.assertEqual(len(found), 2)
        self.assertIn("prices Dagger at 25 gold, and p. 2 never puts that price beside its name", found[0])

    def test_a_table_that_puts_the_price_first_is_read_that_way(self):
        page = LONG + "".join(f"{price} {name} Common Some features.\n" for name, price in self.ROWS)
        self.assertEqual(self.audit(page=page), [])
        found = self.audit({**dict(self.ROWS), "Mace": "12 gold", "Lance": "8 gold"}, page=page)
        self.assertEqual(len(found), 2)

    def test_a_scrambled_table_is_not_judged(self):
        page = LONG + "".join(f"{name}\n" for name, _ in self.ROWS) + "".join(f"{price}\n" for _, price in self.ROWS)
        self.assertEqual(self.audit({**dict(self.ROWS), "Dagger": "25 gold"}, page=page), [])

    def test_a_name_the_page_does_not_hold_is_not_asked(self):
        self.assertEqual(self.audit(names={"Dagger": "Dirk"}), [])


class AuditCliTest(CliCase):
    def test_audit_prints_the_report_and_fails_when_something_is_unaccounted_for(self):
        pack = self.tmp / "crypt"
        make_adventure(pack)
        write(pack / "inventory.toml", AuditTest.COMPLETE.replace('"npcs/ghoul"', '"skill:solo-gm"'))
        code, out, err = self.solo("audit", "--adventure", str(pack))
        self.assertEqual(code, 1)
        self.assertIn("# Audit of crypt", out)
        self.assertIn("- npcs/ghoul", out)
        self.assertIn("something is unaccounted for", err)
        write(pack / "inventory.toml", AuditTest.COMPLETE)
        code, out, err = self.solo("audit", "--adventure", str(pack))
        self.assertEqual(code, 0, err + out)
        self.assertIn("Everything is accounted for.", out)


if __name__ == "__main__":
    unittest.main()
