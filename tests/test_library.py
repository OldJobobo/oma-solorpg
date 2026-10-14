"""An adventure whose rules are only the bundled names (the repository as it is cloned, before make dragonbane): the library says it can't
begin yet and why, and solo new says the rules come first, before it tries to make a hero."""

import json
import unittest

from helpers import RAGNA, RED_TUSK, install_rules
from test_cli import CliCase

from solo import SoloError, creation


class RulesNotBuiltTest(CliCase):
    def setUp(self):
        super().setUp()
        (self.tmp / "games" / "systems" / "dragonbane").unlink()  # only the bundled names are left

    def test_a_new_campaign_says_the_rules_come_from_the_players_books_first(self):
        for hero in ((), ("--character", str(RAGNA)), ("--character", "ragna")):
            code, _, err = self.solo("new", str(RED_TUSK), "--dir", self.game, *hero)
            self.assertEqual(code, 1, err)
            self.assertIn("The Red Tusk Hall can't begin until the rules it plays on are built. Dragonbane has only its names so far. "
                          "Its rules come from your own book: build them with `make dragonbane", err)
            self.assertTrue(err.rstrip().endswith("."), err)
            self.assertNotIn("pre-made hero", err)

    def test_a_hero_rolled_on_its_own_says_the_rules_come_first_too(self):
        code, _, err = self.solo("character", "--system", "dragonbane")
        self.assertEqual(code, 1, err)
        self.assertIn("Dragonbane has only its names so far. Its rules come from your own book: build them with `make dragonbane", err)
        self.assertNotIn("pre-made hero", err)
        # A game that needs nothing from a book and has no creation tables has its heroes to offer, and no book to send the player to.
        with self.assertRaisesRegex(SoloError, r"^Lanterns has no creation tables: pick a pre-made hero or a character file\.$"):
            creation.build({"name": "Lanterns", "creation": {}})

    def test_the_library_says_which_adventures_can_begin_and_why_not(self):
        (self.tmp / "games" / "adventures" / "elsewhere").mkdir(parents=True)
        (self.tmp / "games" / "adventures" / "elsewhere" / "adventure.toml").write_text('title = "Elsewhere"\nsystem = "nowhere"\n')
        adventures = {a["id"]: a for a in json.loads(self.solo("library")[1])["adventures"]}
        tusk = adventures["red-tusk"]
        self.assertEqual((tusk["ready"], tusk["system_name"], tusk["system"], tusk["title"]), (False, "Dragonbane", "dragonbane", "The Red Tusk Hall"))
        self.assertTrue(tusk["why"].startswith("Dragonbane has only its names so far. Its rules come from your own book"), tusk["why"])
        self.assertEqual({key: adventures["elsewhere"][key] for key in ("ready", "why", "system_name")},
                         {"ready": False, "why": "It plays on nowhere, and there is no system pack by that name.", "system_name": None})
        self.assertEqual({key: adventures["bell-under-the-hill"][key] for key in ("ready", "why", "system_name")}, {"ready": True, "why": "", "system_name": "Ironsworn"})
        # Once the rules are built from the books, the Red Tusk Hall can begin.
        install_rules(self.tmp / "games")
        tusk = next(a for a in json.loads(self.solo("library")[1])["adventures"] if a["id"] == "red-tusk")
        self.assertEqual({key: tusk[key] for key in ("ready", "why", "system_name")}, {"ready": True, "why": "", "system_name": "Dragonbane"})

    def test_an_adventure_on_a_system_that_doesnt_load_says_why_in_a_sentence(self):
        broken = self.tmp / "games" / "systems" / "dragonbane"
        broken.mkdir()
        for text in ('format = 1\nextends = "dragonbane-rulebook"\n', "format = 1\nname = [half"):
            with self.subTest(text=text):
                (broken / "system.toml").write_text(text)
                tusk = next(a for a in json.loads(self.solo("library")[1])["adventures"] if a["id"] == "red-tusk")
                self.assertFalse(tusk["ready"])
                self.assertTrue(tusk["why"].startswith("The system pack it plays on, dragonbane, doesn't load: "), tusk["why"])
                self.assertTrue(tusk["why"].endswith(".") and not tusk["why"].endswith(".."), tusk["why"])


class MissingRulesTextTest(unittest.TestCase):
    def test_a_game_that_says_how_its_rules_are_built_is_told_that_and_no_other_game_is_told_dragonbanes(self):
        from solo import packs
        dragonbane = {"name": "Dragonbane", "build": "make dragonbane BOOKS=<folder of your PDFs>"}
        self.assertIn("build them with `make dragonbane BOOKS=<folder of your PDFs>`", packs.missing_text(dragonbane, ["combat"]))
        other = packs.missing_text({"name": "Lanterns"}, ["combat", "weapons"])
        self.assertNotIn("dragonbane", other.lower())
        self.assertEqual(other, "Lanterns has only its names so far. Its rules come from your own book: "
                                "a pack built from your book has to supply them. Missing: combat, weapons")


class HalfBuiltTest(CliCase):
    def test_a_pack_an_import_was_still_building_when_it_was_killed_is_never_listed(self):
        # solo import book builds in .<pack>.building beside where the pack goes; a SIGKILL or a hangup leaves it there.
        for kind, marker in (("systems", "system.toml"), ("adventures", "adventure.toml")):
            left = self.tmp / "games" / kind / ".lanterns.building"
            left.mkdir(parents=True)
            (left / marker).write_text('format = 1\nname = "Lanterns"\ntitle = "Lanterns"\nsystem = "dragonbane"\n')  # no family yet
        code, out, err = self.solo("library")
        self.assertEqual(code, 0, err)
        library = json.loads(out)
        self.assertEqual([s["id"] for s in library["systems"] if s["id"].startswith(".")], [])
        self.assertEqual([a["id"] for a in library["adventures"] if a["id"].startswith(".")], [])
        self.assertEqual(library["problems"], [])
        code, _, err = self.solo("character", "--system", "nope")
        self.assertEqual(code, 1)
        self.assertNotIn(".lanterns.building", err)
