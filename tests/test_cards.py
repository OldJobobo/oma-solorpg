"""The three decks of cards on made-up decks: a card to a page, a back with a word of art, the frame's words among the card's lines (invented cards, the shapes of the
real ones)."""

import os
import tempfile
import tomllib
import unittest
import unittest.mock
from pathlib import Path

from fake_book import CELL, FakeBook

from solo import audit
from solo.books import cards
from solo.books.dragonbane_cards import adventure, improvised, treasure
from solo.books.pack import Pack
from solo.sections import Book


def deck(folder, faces):
    """A deck: the odd page of each card is its back (a word of art), the even page its face, whose lines are given, with the frame's words in the middle of them."""
    made = FakeBook(folder)
    for number, lines in enumerate(faces):
        made.line(2 * number + 1, 100, "INN" if number % 2 else "CAVE", 60, CELL)
        for at, text in enumerate(lines):
            made.line(2 * number + 2, 40 + 12 * at, text, 60, CELL)
        made.line(2 * number + 2, 200, "DRAGONBANE CORE SET", 60, CELL)
    made.save()
    return Book(folder)


class TreasureTest(unittest.TestCase):
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
        self.book = deck(self.tmp / "extract", [
            ["COPPER COINS", "2D6 × 10 copper coins"], ["CHALICE", "2D6 × 5 gold coins DRAGONBANE CORE SET"], ["GEMSTONE", "Roll D6. 1: glass (worth 2 copper),", "2: ruby (worth 25 gold)"],
            ["MASTERCRAFTED", "WEAPON", "Roll D6. 1: dagger, 2: short sword."], ["RUSTY NAIL", "Roll for EVADE. Fail it and you take D6 damage.", "Armor does nothing."],
            ["BOTTLE", "A HEALING roll reveals the contents.", "Roll D6. 1: booze, 2: tonic. The GM rolls in secret."], ["COPPER COINS", "D6 copper coins"]])
        self.pack = Pack(self.book, self.tmp / "out", treasure.NAME, "dragonbane-rulebook")
        treasure.build(self.pack)
        self.table = tomllib.loads(self.pack.files["tables/treasure.toml"])

    def results(self):
        return [{key: value for key, value in row.items() if key != "range"} for row in self.table["results"]]

    def test_the_cards_are_a_table_of_one_die_a_card_and_a_back_is_not_a_card(self):
        self.assertEqual((self.table["formula"], len(self.table["results"]), [row["page"] for row in self.table["results"]]), ("1d7", 7, [2, 4, 6, 8, 10, 12, 14]))
        self.assertEqual([row["range"] for row in self.table["results"]][:3], [[1, 1], [2, 2], [3, 3]])

    def test_coins_roll_their_own_number_and_a_valuable_is_worth_a_roll_of_coins(self):
        found = self.results()
        self.assertEqual((found[0]["text"], found[0]["roll"]), ("{value} copper coins", "2d6x10"))
        self.assertEqual((found[1]["text"], found[1]["roll"]), ("Chalice, worth {value} gold coins", "2d6x5"))
        self.assertEqual((found[6]["text"], found[6]["roll"]), ("{value} copper coins", "1d6"))

    def test_a_card_that_lists_things_to_choose_among_has_them_as_choices_and_keeps_what_else_it_says(self):
        found = self.results()
        self.assertEqual({key: found[2][key] for key in ("text", "choices")}, {"text": "Gemstone", "choices": ["glass (worth 2 copper)", "ruby (worth 25 gold)"]})
        self.assertEqual(found[3]["text"], "Mastercrafted weapon")
        self.assertEqual(found[5], {"page": 12, "text": "Bottle. A HEALING roll reveals the contents. The GM rolls in secret.", "choices": ["booze", "tonic"]})

    def test_dice_in_the_words_of_a_card_are_a_value_to_roll(self):
        self.assertEqual(self.results()[4], {"page": 10, "text": "Rusty nail. Roll for EVADE. Fail it and you take {value} damage. Armor does nothing.", "roll": "1d6"})

    def test_the_pack_says_where_it_went_and_the_audit_finds_it_claimed(self):
        self.pack.write(self.tmp / "extract")
        report = audit.audit(self.tmp / "out", "system")
        self.assertEqual(report["unclaimed"], [])
        self.assertEqual(report["problems"], [])


class FrameTest(unittest.TestCase):
    def test_the_frames_words_come_out_in_one_order_whatever_order_they_were_found_in(self):
        # Two frame lines as long as each other overlap in a card's line: which goes first decides what is left.
        for frame in (["AB CD", "CD EF"], ["CD EF", "AB CD"]):
            self.assertEqual(cards.without("AB CD EF", frame), "EF", frame)


class OtherDecksTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)

    def test_an_improvised_weapon_is_a_page_of_the_lines_it_has_with_the_frame_taken_out_of_the_middle(self):
        book = deck(self.tmp / "extract", [["BUCKET OF SUDS", "✦Splash the suds across a cone four", "meters long.", "✦Everyone caught in it slips", "over.", "✦It can be dodged."], ["WASP NEST", "✦Throw it.", "✦It stings."]])
        pack = Pack(book, self.tmp / "out", improvised.NAME, "dragonbane-rulebook")
        improvised.build(pack)
        self.assertEqual(pack.files["rules/improvised_weapon_bucket_of_suds.md"], "\n".join([
            "# Improvised weapon: Bucket of Suds", "Search: bucket of suds", "", "- Splash the suds across a cone four meters long.", "- Everyone caught in it slips over.", "- It can be dodged.", "",
            f"Source: {improvised.NAME}, PDF p. 2"]) + "\n")
        self.assertIn("Bucket of Suds; Wasp Nest", pack.files["rules/improvised_weapon_cards.md"])

    def test_an_adventure_card_is_a_place_and_what_is_said_of_it_and_a_title_may_take_two_lines(self):
        book = deck(self.tmp / "extract", [["RIDDERMOUND", "“There is an unholy place with huge stones.”"], ["THE HAMLET", "OF THE LONG NIGHT", "“Nine winters back a hamlet burned.”"]])
        pack = Pack(book, self.tmp / "out", adventure.NAME, "dragonbane-rulebook")
        adventure.build(pack)
        table = tomllib.loads(pack.files["tables/adventure_cards.toml"])
        self.assertEqual((table["formula"], [row["text"] for row in table["results"]]), ("1d2", ["Riddermound. “There is an unholy place with huge stones.”",
                                                                                                "The Hamlet of the Long Night. “Nine winters back a hamlet burned.”"]))

    def test_a_deck_is_known_by_its_pages_and_its_first_card(self):
        book = deck(self.tmp / "extract", [["RIDDERMOUND", "“Stones.”"]])
        self.assertEqual(len(cards.fingerprint(book)), 16)
        self.assertFalse(adventure.recognizes(book))


if __name__ == "__main__":
    unittest.main()
