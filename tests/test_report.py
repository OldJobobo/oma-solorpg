"""`solo report`: a bundle for a public bug report, with the books' words left out."""

import json
import os
import stat
import unittest.mock

from helpers import CampaignTest, Dice
from test_cli import CliCase

from solo import campaign, gm, report


class ReportTest(CampaignTest):
    def played(self):
        with self.session() as c:
            c.table("search", rng=Dice(2))                       # a table's result: the pack's words
            c.ask("Is the passage guarded by the smugglers?", rng=Dice(5))  # a question, and the chart's answer
            c.threat("Something hungry follows your trail", threat_id="hungry")
            c.commit({"note": "Marked the secret door on the map", "facts": {"gate.open": True}})
            c.say("The smugglers' lantern swings in the dark.", "gm")
            return c

    def test_it_shows_what_happened_by_ids_and_dice_and_none_of_the_words(self):
        self.played()
        with self.session() as c:
            text = report.report(c, messages=0)
        self.assertIn('table {"table":"search"', text)
        self.assertIn('"total":2', text)
        self.assertIn("oracle", text)
        for words in ("A tripwire across the floor", "Is the passage guarded", "smugglers", "Something hungry", "secret door on the map"):
            self.assertNotIn(words, text)
        self.assertIn("said by gm (", text)  # a message is counted, not quoted
        self.assertNotIn("lantern", text)

    def test_the_stories_last_messages_are_there_unless_left_out(self):
        self.played()
        with self.session() as c:
            self.assertIn("> The smugglers' lantern swings in the dark.", report.report(c))
            self.assertNotIn("lantern", report.report(c, messages=0))
            self.assertIn("read them before you post", report.report(c))

    def test_it_says_which_engine_and_which_pack_formats(self):
        with self.session() as c:
            text = report.report(c)
        self.assertRegex(text, r"- oma-solorpg \S+")
        self.assertIn("pack format of each layer, base first:", text)
        self.assertRegex(text, r"adventure red-tusk, format 1")

    def test_the_gms_commands_are_there_refused_ones_with_their_error_and_cut_short(self):
        with self.session() as c:
            folder = c.root / ".solo"
            folder.mkdir(exist_ok=True)
            long_arg = "x" * 200
            lines = [{"at": "2026-09-30T10:00:00", "argv": ["check", "sneaking", "--boons", "1"], "error": None},
                     {"at": "2026-09-30T10:00:05", "argv": ["setup", "--plugin"], "error": "the GM can't run that"},
                     {"at": "2026-09-30T10:00:09", "argv": ["commit", long_arg], "error": None}]
            (folder / "trace.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")
            text = report.report(c)
        self.assertIn("- 2026-09-30T10:00:00 solo check sneaking --boons 1\n", text)
        self.assertIn("solo setup --plugin  -> refused: the GM can't run that", text)
        self.assertNotIn("x" * 100, text)

    def test_only_ids_numbers_and_flags_survive_the_leaving_out(self):
        self.assertEqual(report.bare({"a": "yes_no", "b": ["Extreme yes", 3, True], "c": {"d": "Some words here"}}),
                         {"a": "yes_no", "b": ["…", 3, True], "c": {"d": "…"}})


class ReportCommand(CliCase):
    def test_solo_report_prints_and_writes(self):
        self.new_game()
        code, out, _ = self.solo("-C", self.game, "report", "--no-messages")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("# oma-solorpg report"))
        target = self.tmp / "report.md"
        code, out, _ = self.solo("-C", self.game, "report", "--out", str(target))
        self.assertEqual(code, 0)
        self.assertIn("read it before you post it", out)
        self.assertTrue(target.read_text().startswith("# oma-solorpg report"))


class TurnTrace(CampaignTest):
    def test_the_books_gm_writes_its_commands_where_a_report_reads_them(self):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        script = bin_dir / "claude"
        script.write_text("#!/usr/bin/env python3\nimport json, os\nprint(json.dumps({'type': 'result', 'subtype': 'success', 'session_id': 's', 'result': os.environ.get('SOLO_TRACE', 'none')}))\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        # The turn reads the stand-in's --help and keeps the answer in XDG_CACHE_HOME: a throwaway one, not the player's.
        with unittest.mock.patch.dict(os.environ, {"PATH": f"{bin_dir}:{os.environ['PATH']}", "AGENT": "claude",
                                                   "XDG_CACHE_HOME": str(self.tmp / "cache")}):
            os.environ.pop("SOLO_TRACE", None)
            gm.turn(self.root, "Hi")
        with self.session() as c:
            said = [e["text"] for e in c.events if e["type"] == "said" and e["by"] == "gm"]
        self.assertEqual(said, [str(self.root / ".solo" / "trace.jsonl")])

    def test_a_long_trace_keeps_its_last_lines(self):
        path = self.tmp / "trace.jsonl"
        path.write_text("".join(json.dumps({"n": n}) + "\n" for n in range(3000)))
        gm._trim(path, keep=100, over=1000)
        lines = path.read_text().splitlines()
        self.assertEqual((len(lines), json.loads(lines[0])["n"], json.loads(lines[-1])["n"]), (100, 2900, 2999))
