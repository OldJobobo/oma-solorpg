"""Pack format numbers: every pack the repository ships declares one, a generated or imported
pack starts with one, and `solo validate` says what to do about a pack that has none or an
older one, and refuses one written for a newer engine."""

import json
import re
import shutil
import unittest
import unittest.mock

from helpers import DRAGONBANE, FIXTURES, RED_TUSK, ROOT
from test_cli import CliCase
from test_generate import Folder, roll

from solo import foundry, packs


def write_format(pack, filename, value):
    """The pack's first file with its `format` line set to `value`, or taken out for None."""
    path = pack / filename
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("format")]
    if value is not None:
        lines.insert(next((i for i, line in enumerate(lines) if not line.startswith("#")), 0), f"format = {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class ShippedPacksTest(unittest.TestCase):
    def test_every_pack_in_the_repository_declares_the_format(self):
        found = [*ROOT.glob("packs/*/system.toml"), *ROOT.glob("examples/*/adventure.toml"),
                 *FIXTURES.rglob("system.toml"), *FIXTURES.rglob("adventure.toml")]
        self.assertGreaterEqual(len(found), 7)
        for path in found:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertEqual(packs.load_data(path).get("format"), packs.FORMAT)

    def test_make_rules_and_supplement_start_the_packs_they_make_at_the_format_it_reads(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        written = re.findall(r"format = (\d+)", makefile)
        self.assertEqual(written, [str(packs.FORMAT)] * 3)  # the rulebook, the top pack, a supplement

    def test_every_older_format_says_what_to_change(self):
        self.assertEqual(sorted(packs.UPGRADES), list(range(1, packs.FORMAT)))
        for sentence in packs.UPGRADES.values():
            self.assertTrue(sentence.endswith("."), sentence)


class ValidateTest(CliCase):
    def adventure(self, value):
        pack = self.tmp / "salt"
        shutil.copytree(RED_TUSK, pack, dirs_exist_ok=True)
        write_format(pack, "adventure.toml", value)
        return pack

    def validate(self, pack):
        return self.solo("validate", "--system", "dragonbane", "--adventure", str(pack))

    def test_a_pack_that_declares_the_format_says_nothing(self):
        code, out, err = self.validate(self.adventure(packs.FORMAT))
        self.assertEqual((code, out.strip(), err), (0, "ok: house and salt", ""))

    def test_no_format_is_one_sentence_and_the_pack_still_plays(self):
        pack = self.adventure(None)
        code, out, err = self.validate(pack)
        self.assertEqual(code, 0, err)
        self.assertIn("worth a look: salt/adventure.toml has no `format`: add `format = 1`", out)
        code, _, err = self.solo("new", str(pack), "--dir", self.game, "--character", "ragna")
        self.assertEqual(code, 0, err)

    def test_a_pack_written_for_a_newer_engine_is_refused_and_says_to_update(self):
        pack = self.adventure(packs.FORMAT + 1)
        code, _, err = self.validate(pack)
        self.assertEqual(code, 1)
        self.assertIn(f"salt/adventure.toml is format {packs.FORMAT + 1} and this engine reads formats up to {packs.FORMAT}", err)
        self.assertIn("update oma-solorpg (Update in its README: fetch, then check out a newer release)", err)
        self.assertNotIn("git pull", err)  # the README installs a detached checkout, where git pull fails
        code, _, err = self.solo("new", str(pack), "--dir", self.game, "--character", "ragna")
        self.assertEqual(code, 1)
        self.assertIn("the packs need fixing first", err)

    def test_a_format_that_is_not_a_number_is_refused(self):
        for value in ('"one"', "0", "true", "1.5"):
            with self.subTest(value=value):
                code, _, err = self.validate(self.adventure(value))
                self.assertEqual(code, 1)
                self.assertIn("salt/adventure.toml: format must be a whole number", err)

    def test_an_older_pack_is_told_what_to_change(self):
        upgrades = {1: "Rename every `people` to `npcs`."}
        with unittest.mock.patch.object(packs, "FORMAT", 2), unittest.mock.patch.dict(packs.UPGRADES, upgrades):
            code, out, err = self.validate(self.adventure(1))
            self.assertEqual(code, 0, err)
            self.assertIn("worth a look: salt/adventure.toml is format 1, and this engine reads format 2. "
                          "Rename every `people` to `npcs`. Then set `format = 2` in it", out)
            # No number at all reads as the first format, and is told the same steps.
            code, out, err = self.validate(self.adventure(None))
            self.assertIn("salt/adventure.toml has no `format`, so it reads as format 1, and this engine reads format 2. "
                          "Rename every `people` to `npcs`.", out)
            # The rules under it are checked too, each layer by its own file (the house pack says 1).
            self.assertIn("worth a look: house/system.toml is format 1", out)

    def test_each_layer_of_a_system_pack_answers_for_itself(self):
        layer = self.tmp / "rules"
        layer.mkdir()
        (layer / "system.toml").write_text(f'extends = "{DRAGONBANE}"\n', encoding="utf-8")
        code, out, err = self.solo("validate", "--system", str(layer))
        self.assertEqual(code, 0, err)
        self.assertIn("worth a look: rules/system.toml has no `format`", out)
        self.assertNotIn("house/system.toml", out)

    def test_the_library_leaves_out_a_pack_from_a_newer_engine_and_says_why(self):
        newer = self.tmp / "games" / "adventures" / "newer"
        shutil.copytree(RED_TUSK, newer)
        write_format(newer, "adventure.toml", packs.FORMAT + 1)
        _, out, _ = self.solo("library")
        listing = json.loads(out)
        self.assertNotIn("newer", [a["id"] for a in listing["adventures"]])
        self.assertTrue(any(p.startswith("adventure newer: newer/adventure.toml is format") for p in listing["problems"]), listing["problems"])


class WrittenPacksTest(Folder):
    def test_a_campaign_rolled_from_a_premise_starts_at_the_format(self):
        pack = self.tmp / "salt"
        roll(pack)
        self.assertEqual(packs.load_adventure(pack)["format"], packs.FORMAT)

    def test_a_foundry_import_starts_its_stub_at_the_format(self):
        out = self.tmp / "mine"
        export = FIXTURES / "foundry" / "adventure"
        foundry.import_adventure([export], out)
        self.assertEqual(packs.load_adventure(out)["format"], packs.FORMAT)


if __name__ == "__main__":
    unittest.main()
