"""A made-up adventure book (invented places and people, the typefaces and shapes of the real ones) read into an adventure pack: its places as scenes with their ways on,
its people and monsters as NPCs, its tables, and the whole of it loaded, validated and audited the way a pack an agent wrote is."""

import tempfile
import tomllib
import unittest
from pathlib import Path

from fake_book import CELL, HEADER, FakeBook
from helpers import BEASTS

from solo import audit, packs
from solo import books
from solo.books import adventure
from solo.books.dragonbane_tower import heroes
from solo.books.pack import AdventurePack
from solo.sections import Book

READ = ("MinionPro-SemiboldIt", 10.0, 2301728)
BULLET = ("MinionPro-Regular", 10.0, 2301728)
STAT = ("Hideout-Bold", 9.0, 4926747)
SAID = ("Hideout-Regular", 9.0, 4859142)
MAP = ("Hideout-Bold", 8.0, 16777215)
LETTERED = ("Caveat-Regular", 14.0, 2301728)
PRINTED = ("Hideout-SemiBold", 6.5, 2301728)


def place(made, page, y, title, aloud, *bullets):
    """A numbered place: its heading, the words to read out and the bullets under them; the y where the next thing goes."""
    made.section(page, y, 3, title, *[])
    made.lines(page, y + 20, *aloud, style=READ)
    at = y + 20 + 12 * len(aloud) + 8
    for text in bullets:
        made.line(page, at, text, 62, BULLET)
        at += 14
    return at + 10


class AdventureTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        made = FakeBook(self.tmp / "extract")
        made.section(1, 80, 1, "1. The Barrow", "A barrow stands on a hill.")
        made.section(1, 130, 2, "The Situation", "Lurkers have taken the barrow.", "They wait below.")
        made.section(1, 190, 3, "Sidebar: Leaving?", "Those who leave are followed.")
        made.banner(1, 250, 3, "Table: Omens")
        made.roll_table(1, 280, ["D6", "OMEN"], [("1", "A crow cries."), ("2", "The wind drops."), ("3", "A light in the barrow."), ("4", "Nothing."), ("5", "Nothing."), ("6", "A scream.")], [72, 90])
        # Lurkers: a stat block in the colour of stat blocks, and what the book says of them in another.
        made.line(1, 420, "NPCS: LURKERS", 250, ("Hideout-Bold", 10.0, 6305303))
        made.mark(3, "NPCs: Lurkers")
        made.line(1, 436, "Mov.: 10 Damage Bonus STR: +D4 HP: 12", 85, STAT)
        made.line(1, 448, "Armor: Leather (1)", 85, STAT)
        made.line(1, 460, "Skills: Evade 10, Sneaking 12", 85, STAT)
        made.line(1, 472, "Weapons: Dirk (skill level 12, damage D8), sling (skill level 10, damage D6)", 85, STAT)
        made.section(2, 80, 2, "Locations", "Four places.")
        made.line(1, 760, "5", 300)["running"] = True  # the number printed on the first page
        y = place(made, 2, 120, "1. Mouth", ["A black mouth opens in the hill."], "✦Altar: A flat stone with old stains.", "✦NORTH: A door into the hall (#2).",
                  "✦Fumes: Thick fumes. The heroes must make a CON roll each round.", "✦Omen: Roll D6 on the table on page 5 for each stretch spent here.")
        y = place(made, 2, y, "2. Hall", ["A long hall, pillars on both sides."], "✦SOUTH: Back to the mouth (#1).", "✦EAST: A locked door to the vault (#3).",
                  "✦Crack: A narrow crack leads on (#4).")
        made.line(2, y, "MAP", 400, MAP)
        made.mark(4, "Map: Hall")
        made.line(2, y + 2, "– Two levers are pulled: the vault door opens.", 82, BULLET)
        made.line(2, y + 12, "To #4", 400, MAP)
        made.line(2, y + 20, "(hidden)", 400, MAP)
        y = place(made, 3, 80, "3. Vault", ["Gold glints in the dark."], "✦Chest: A chest, trapped.")
        # Gloom: a monster with its stat lines inside its section, and a table of attacks.
        made.line(3, y, "MONSTER: GLOOM", 250, ("Hideout-Bold", 10.0, 6305303))
        made.mark(4, "Monster: Gloom")
        made.line(3, y + 16, "Gloom drinks light and gives it back as fear. It has a long shadow.", 85, SAID)
        made.line(3, y + 32, "Ferocity: 2   Size: Large", 85, STAT)
        made.line(3, y + 44, "Movement: 12   Armor: 2   HP: 30", 85, STAT)
        made.line(3, y + 64, "MONSTER ATTACKS", 250, ("Hideout-Bold", 10.0, 4859142))
        made.line(3, y + 80, "D2 ATTACK", 68, HEADER)
        for number, text in enumerate(["Shadow! Gloom lashes a victim with 2D6 bludgeoning damage.", "Dread! Everyone within 10 meters suffers a fear attack."]):
            made.line(3, y + 97 + 17 * number, str(number + 1), 72, CELL)
            made.line(3, y + 97 + 17 * number, text, 85, CELL)
        made.line(3, y + 150, "NPC: MARTA", 250, ("Hideout-Bold", 10.0, 6305303))
        made.mark(4, "NPC: Marta")
        made.line(3, y + 166, "Marta keeps the vault and trusts nobody.", 62, BULLET)
        made.line(3, y + 190, "MARTA", 250, STAT)
        made.mark(5, "Statblock")
        made.line(3, y + 204, "Movement: 8   Damage Bonus: —   HP: 10", 85, STAT)
        made.line(3, y + 216, "Armor: —", 85, STAT)
        made.line(3, y + 228, "Skills: Persuasion 12", 85, STAT)
        made.line(3, y + 240, "Weapon: Knife (skill level 8, damage D6)", 85, STAT)
        made.line(3, y + 270, "✦Ward: Marta wards the vault door.", 62, BULLET)
        # A person the book gives by reference to the rulebook, and a place no way leads to.
        made.line(4, 80, "NPCS: SPECTERS", 250, ("Hideout-Bold", 10.0, 6305303))
        made.mark(4, "NPCs: Specters")
        made.line(4, 96, "The specters have the stats of a wraith as per page 9 in the Rulebook.", 85, SAID)
        place(made, 4, 140, "4. Cellar", ["Damp steps lead down."], "✦Barrels: Rotten barrels line the wall.")
        made.save(pages=True)
        self.book = Book(self.tmp / "extract")
        self.system = packs.load_system(BEASTS)
        self.pack = AdventurePack(self.book, self.tmp / "pack", "A Barrow", self.system)
        self.pack.adventure.update({"title": "The Barrow", "system": "dragonbane"})
        self.chapter = self.book.find("1. The Barrow")

    def build(self, **options):
        found = adventure.scenes(self.pack, "barrow", self.chapter, "barrow", **options)
        self.pack.adventure["start"] = found[0].id
        return found, self.pack.chapter("barrow")["scenes"]

    def test_the_numbered_places_are_scenes_in_the_books_order(self):
        found, scenes = self.build()
        self.assertEqual([(p.id, p.keys) for p in found], [("barrow_mouth", ["1"]), ("barrow_hall", ["2"]), ("barrow_vault", ["3"]), ("barrow_cellar", ["4"])])
        self.assertEqual(scenes["barrow_hall"]["title"], "Hall")

    def test_a_bullet_named_for_a_direction_is_a_way_on_and_one_the_text_calls_locked_is_gated(self):
        _, scenes = self.build()
        self.assertEqual(scenes["barrow_mouth"]["exits"]["barrow_hall"], "North: A door into the hall.")
        hall = scenes["barrow_hall"]["exits"]
        self.assertEqual(hall["barrow_mouth"], "South: Back to the mouth.")
        self.assertEqual(hall["barrow_vault"], {"label": "East: A locked door to the vault.", "when": "fact.barrow_hall.to_vault"})
        self.assertTrue(any("the way to Vault is shut" in note for note in self.pack.notes))

    def test_a_way_the_map_labels_hidden_is_gated_and_the_scene_says_which_fact_opens_it(self):
        _, scenes = self.build()
        self.assertEqual(scenes["barrow_hall"]["exits"]["barrow_cellar"]["when"], "fact.barrow_hall.to_cellar")
        text = self.pack.files["scenes/barrow_hall.md"]
        self.assertIn('commit {"facts": {"barrow_hall.to_cellar": true}}', text)

    def test_a_scene_is_what_to_read_aloud_and_then_the_rest_in_a_gm_fence_with_places_named(self):
        self.build()
        text = self.pack.files["scenes/barrow_mouth.md"]
        aloud, _, gm = text.partition("::: gm")
        self.assertEqual(aloud.strip(), "A black mouth opens in the hill.")
        self.assertIn("- **Altar:** A flat stone with old stains.", gm)
        self.assertIn("- **NORTH:** A door into the hall (#2 Hall).", gm)
        self.assertTrue(gm.strip().endswith(":::"))

    def test_words_a_maps_bookmark_holds_stay_in_the_scene_and_the_maps_labels_do_not(self):
        self.build()
        hall = self.pack.files["scenes/barrow_hall.md"]
        self.assertIn("– Two levers are pulled: the vault door opens.", hall)
        self.assertNotIn("(hidden)", hall)

    def test_what_a_place_asks_every_round_is_said_in_every_fight_there(self):
        _, scenes = self.build()
        self.assertEqual(scenes["barrow_mouth"]["each_round"], "The heroes must make a CON roll each round.")
        self.assertNotIn("each_round", scenes["barrow_hall"])

    def test_a_table_sent_to_by_its_page_is_named_and_one_in_the_rulebook_is_not(self):
        self.build()
        self.assertIn("Roll D6 on the table on page 5 (solo table barrow_omens) for each stretch", self.pack.files["scenes/barrow_mouth.md"])
        named = adventure._name_tables("Roll on the table on page 5 in the Rulebook.", {5: ["barrow_omens"]})
        self.assertEqual(named, "Roll on the table on page 5 in the Rulebook.")
        two = {5: ["barrow_random_events", "barrow_leaving"]}
        self.assertEqual(adventure._name_tables("Random Event: pick from the table on page 5.", two), "Random Event: pick from the table on page 5 (solo table barrow_random_events).")
        self.assertEqual(adventure._name_tables("Pick from the table on page 5.", two), "Pick from the table on page 5.")

    def test_the_situation_and_its_sidebars_go_with_the_first_scene_and_its_tables_with_all(self):
        _, scenes = self.build()
        first = self.pack.files["scenes/barrow_mouth.md"]
        self.assertIn("Lurkers have taken the barrow. They wait below.", first)
        self.assertIn("**Leaving?**", first)
        self.assertTrue(all(scene["tables"] == ["barrow_omens"] for scene in scenes.values()))
        self.assertEqual(tomllib.loads(self.pack.files["tables/barrow_omens.toml"])["formula"], "1d6")

    def test_a_place_no_way_leads_to_is_linked_from_the_one_before_it_and_the_recipe_says_so(self):
        made = FakeBook(self.tmp / "other")
        made.section(1, 80, 1, "1. Pit", "A pit.")
        made.section(1, 120, 2, "Locations", "Three places.")
        place(made, 1, 160, "1. Rim", ["The rim."], "✦DOWN: A rope to the ledge (#2).")
        place(made, 1, 260, "2. Ledge", ["A ledge."], "✦Note: Nothing here.")
        place(made, 1, 340, "3. Floor", ["The floor."], "✦Note: Nothing here either.")
        made.save()
        pack = AdventurePack(Book(self.tmp / "other"), self.tmp / "pack2", "A Pit", self.system)
        adventure.scenes(pack, "pit", Book(self.tmp / "other").find("1. Pit"), "pit", situation=False)
        exits = pack.chapter("pit")["scenes"]
        self.assertEqual(sorted(exits["pit_ledge"]["exits"]), ["pit_floor"])
        self.assertEqual(exits["pit_floor"]["exits"], {"pit_ledge": "Back to Ledge"})
        self.assertEqual([note for note in pack.notes if "gives no way on" in note], ["1. Pit: the book's text gives no way on to Floor, so each is linked from the place before it in the book, and back (change them if the map says otherwise)"])

    def test_several_sections_of_a_chapter_without_places_are_one_scene_that_leads_on_naming_the_next(self):
        made = FakeBook(self.tmp / "beats")
        made.section(1, 80, 1, "2. Road", "A road.")
        made.section(1, 120, 2, "First Part", "The first part.")
        made.section(1, 170, 2, "Second Part", "The second part.")
        made.save()
        book = Book(self.tmp / "beats")
        pack = AdventurePack(book, self.tmp / "pack3", "A Road", self.system)
        scene = adventure.scene_of(pack, "road", "road_all", "Road", book.find("2. Road").children, "road", after=("town_arrival", "the town"))
        self.assertEqual((scene, pack.chapter("road")["scenes"]["road_all"]["exits"]), ("road_all", {"town_arrival": "Onward, to the town"}))
        text = pack.files["scenes/road_all.md"]
        self.assertTrue(text.index("**First Part**") < text.index("The first part.") < text.index("**Second Part**") < text.index("The second part."))

    def test_a_person_with_a_stat_block_fights_by_it(self):
        self.build()
        lurkers = tomllib.loads(self.pack.files["npcs/lurkers.toml"])
        self.assertEqual((lurkers["name"], lurkers["many"], lurkers["stats"], lurkers["skills"]), ("Lurkers", True, {"hp": 12, "armor": 1, "movement": 10}, {"evade": 10, "sneaking": 12}))
        self.assertEqual(lurkers["attack"], {"label": "Dirk", "value": 12, "damage": "1d8", "bonus": "1d4"})
        marta = tomllib.loads(self.pack.files["npcs/marta.toml"])
        self.assertEqual((marta["stats"], marta["attack"]["damage"], marta["description"].startswith("Marta keeps the vault")), ({"hp": 10, "armor": 0, "movement": 8}, "1d6", True))
        self.assertIn("Marta wards the vault door.", self.pack.files["scenes/barrow_vault.md"])  # what stood after her block is the place's

    def test_a_monster_has_its_numbers_and_a_table_of_attacks_and_its_words_apart_from_them(self):
        self.build()
        gloom = tomllib.loads(self.pack.files["npcs/gloom.toml"])
        self.assertEqual((gloom["stats"], gloom["attacks"], gloom["attitude"], gloom["description"]),
                         ({"hp": 30, "armor": 2, "ferocity": 2, "movement": 12}, "gloom_attacks", "hostile", "Gloom drinks light and gives it back as fear. It has a long shadow."))
        attacks = tomllib.loads(self.pack.files["tables/gloom_attacks.toml"])
        self.assertEqual([(r["range"], r.get("damage")) for r in attacks["results"]], [([1, 1], "2d6"), ([2, 2], None)])

    def test_a_person_the_book_gives_by_the_rulebook_is_that_monster(self):
        self.build()
        specters = tomllib.loads(self.pack.files["npcs/specters.toml"])
        self.assertEqual(specters["monster"], "wraith")
        self.assertTrue(any("it is the rulebook's wraith" in note for note in self.pack.notes))

    def test_the_whole_pack_loads_validates_and_has_every_part_claimed(self):
        self.build()
        self.pack.item("barrow", "The Barrow", "place", [1, 2, 3, 4], [f"scenes/{scene}" for scene in self.pack.chapter("barrow")["scenes"]])
        self.pack.write(self.tmp / "extract")
        loaded = packs.load_adventure(self.tmp / "pack")
        self.assertEqual(packs.validate(self.system, loaded), [])
        report = audit.audit(self.tmp / "pack", "adventure")
        self.assertEqual((report["unclaimed"], report["problems"]), ([], []))
        # Read back against the made-up book's own pages, every table, number and word is on them.
        self.assertEqual(report["unverified"], [])


class RecipesTest(unittest.TestCase):
    def test_the_adventures_go_after_the_rules_they_are_for_and_each_names_its_system(self):
        recipes = books.recipes()
        kinds = [books.kind_of(recipe) for recipe in recipes]
        self.assertEqual(kinds, sorted(kinds, key=lambda kind: kind == "adventure"))
        self.assertGreaterEqual(kinds.count("adventure"), 2)
        self.assertTrue(all(recipe.SYSTEM == "dragonbane" and recipe.PRINTINGS for recipe in recipes if books.kind_of(recipe) == "adventure"))


class HeroesTest(unittest.TestCase):
    """A pre-generated hero's sheet: printed labels, and the values lettered over them, read by where they stand."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        made = FakeBook(self.tmp / "extract")
        made.section(1, 80, 1, "Pre-Generated Characters", "Heroes.")
        made.line(2, 20, "PLAYER", 34, PRINTED)
        made.mark(2, "Test Hero")
        for text, x, y in (("KIN", 34, 40), ("AGE", 139, 40), ("PROFESSION", 34, 58), (" WEAKNESS", 34, 75), ("STR", 154, 144), ("CON", 211, 144), ("AGL", 270, 144), ("INT", 329, 144),
                           ("WIL", 386, 144), ("CHA", 443, 144), ("ENCUMBRANCE LIMIT", 504, 248), ("GOLD", 42, 510), ("SILVER", 42, 539), ("COPPER", 42, 569)):
            made.line(2, y, text, x, PRINTED)
        for text, x, y in (("DAMAGE BON. STR", 55, 229), ("DAMAGE BON. AGL", 242, 229), ("MOVEMENT", 430, 229), ("WILLPOWER POINTS", 415, 620), ("HIT POINTS", 415, 686), ("WEAPON / SHIELD", 56, 692)):
            made.line(2, y, text, x, ("Hideout-Black", 7.5, 2301728))
        made.line(2, 287, "Awareness (INT) ", 221, ("Hideout-Light", 8.0, 2301728))
        made.line(2, 301, "Swords (STR) ", 348, ("Hideout-Light", 6.5, 2301728))
        for text, x, y in (("Elf", 34, 42), ("Adult", 139, 42), ("Hunter", 34, 59), ("Bigoted. Nightkin are evil.", 34, 76), ("9", 155, 149), ("11", 209, 149), ("13", 271, 149), ("15", 326, 149), ("10", 384, 149),
                           ("8", 441, 149), ("D4", 157, 221), ("—", 344, 221), ("12", 532, 221), ("4", 536, 255), ("7", 115, 533), ("14", 200, 280), ("12", 330, 294),
                           ("Ember", 34, 280), ("Quickdraw", 34, 294), ("Torch", 461, 279), ("Leather", 92, 623), ("13", 426, 632), ("15", 427, 700), ("Sword", 34, 710)):
            made.line(2, y, text, x, LETTERED)
        made.save()
        self.pack = AdventurePack(Book(self.tmp / "extract"), self.tmp / "pack", "Heroes", packs.load_system(BEASTS))

    def test_a_sheet_is_read_into_a_hero_by_where_each_value_stands(self):
        heroes.build(self.pack)
        hero = tomllib.loads(self.pack.files["characters/test_hero.toml"])
        self.assertEqual(hero["attributes"], {"str": 9, "con": 11, "agl": 13, "int": 15, "wil": 10, "cha": 8})
        self.assertEqual(hero["tracks"], {"hp": 15, "wp": 13})
        self.assertEqual(hero["info"], {"kin": "Elf", "profession": "Hunter", "age": "Adult", "weakness": "Bigoted. Nightkin are evil."})
        self.assertEqual(hero["ratings"], {"Movement": 12, "Damage bonus (STR)": "+D4", "Damage bonus (AGL)": "none"})
        self.assertEqual(hero["items"], ["sword", "leather armor", "torch", "7 silver"])
        self.assertEqual(hero["skills"], {"awareness": 14, "swords": 12})  # the numbers that are their base chance are left out
        self.assertEqual((hero["abilities"], hero["spells"]), (["Quickdraw"], ["Ember"]))
        self.assertEqual(hero["prepared"], ["Ember"])

    def test_a_hero_the_adventure_names_is_a_replacement_with_the_npcs_id(self):
        self.pack.facts["npc_ids"] = {"test_hero"}
        heroes.build(self.pack)
        self.assertTrue(tomllib.loads(self.pack.files["characters/test_hero.toml"])["replacement"])


class MendTest(unittest.TestCase):
    def test_a_paragraph_cut_in_a_word_and_its_rest_far_off_are_one(self):
        book = type("Book", (), {"words": set()})()
        items = [("text", "Keep time."), ("bullet", "✦Replace. There is a pos­"), ("text", "Other words."), ("text", "sibility that a hero dies."), ("text", "Last.")]
        mended = adventure.mend(book, items)
        self.assertEqual(mended[1], ("bullet", "✦Replace. There is a possibility that a hero dies."))
        self.assertEqual(len(mended), 4)

    def test_a_paragraph_cut_after_a_word_is_joined_with_a_space(self):
        book = type("Book", (), {"words": set()})()
        mended = adventure.mend(book, [("text", "The heroes may go on"), ("text", "if they dare.")])
        self.assertEqual(mended, [("text", "The heroes may go on if they dare.")])


if __name__ == "__main__":
    unittest.main()
