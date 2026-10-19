import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from helpers import BUNDLED, Dice, DRAGONBANE, RAGNA, RED_TUSK, ROOT, install_rules

from solo import campaign, cli


class CliCase(unittest.TestCase):
    """A throwaway home, library and state folder, and `solo` run in-process."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        env = {
            "XDG_STATE_HOME": str(self.tmp / "state"), "HOME": str(self.tmp / "home"),
            "SOLO_HOME": str(self.tmp / "games"), "SOLO_SEED": "5",
            # A bug fails a test with its traceback, not the player's one line.
            "SOLO_DEBUG": "1",
        }
        patch = unittest.mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        # Run as a player at a terminal, even when the tests run inside Claude Code or a Book turn.
        for name in ("CLAUDECODE", "SOLO_BOOK"):
            os.environ.pop(name, None)
        self.game = str(self.tmp / "game")
        install_rules(self.tmp / "games")

    def solo(self, *args, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), unittest.mock.patch("sys.stdin", io.StringIO(stdin)):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def new_game(self):
        code, _, err = self.solo("new", str(RED_TUSK), "--dir", self.game, "--character", str(RAGNA))
        self.assertEqual(code, 0, err)


class CliTest(CliCase):
    def test_a_living_hero_goes_on_to_a_new_adventure(self):
        self.new_game()
        with campaign.session(self.game) as c:
            c.commit({"pc": {"hp": "-5", "conditions": {"add": ["angry"]}, "items": {"add": ["idol"]}}})
            c.append("advance", results=[{"skill": "swords", "name": "Swords", "roll": 16, "was": 14, "now": 15}])
        later = str(self.tmp / "later")
        code, _, err = self.solo("new", str(RED_TUSK), "--dir", later, "--character", self.game)
        self.assertEqual(code, 0, err)
        with campaign.session(later) as c:
            pc = c.state["pc"]
        self.assertEqual((pc["name"], pc["skills"]["swords"]["value"]), ("Ragna", 15))
        self.assertEqual((pc["tracks"]["hp"]["value"], pc["conditions"]), (14, []))  # rested
        self.assertIn("idol", pc["items"])
        with campaign.session(later) as c:
            c.commit({"pc": {"hp": "-14"}})
            c.death_roll(rng=Dice(20))
            c.death_roll(rng=Dice(20))
        code, _, err = self.solo("new", str(RED_TUSK), "--dir", str(self.tmp / "again"), "--character", later)
        self.assertIn("Hall of the Fallen", err)

    def test_new_writes_a_campaign_with_agent_instructions(self):
        self.new_game()
        agents = (Path(self.game) / "AGENTS.md").read_text()
        self.assertIn(str(ROOT / "skills" / "solo-gm" / "SKILL.md"), agents)
        self.assertEqual((Path(self.game) / "CLAUDE.md").read_text(), "@AGENTS.md\n")
        settings = json.loads((Path(self.game) / ".claude" / "settings.json").read_text())
        allowed = settings["permissions"]["allow"]
        self.assertIn("Bash(solo commit:*)", allowed)
        self.assertFalse({"Bash(solo *)", "Bash(solo setup:*)", "Bash(solo import:*)"} & set(allowed))
        code, _, err = self.solo("new", str(RED_TUSK), "--dir", self.game, "--character", str(RAGNA))
        self.assertEqual((code, "already holds a campaign" in err), (1, True))

    def test_titles_outside_ascii_keep_the_campaign_readable(self):
        code, _, err = self.solo("new", str(RED_TUSK), "--dir", self.game, "--character", str(RAGNA), "--title", "Tusk 🐉")
        self.assertEqual(code, 0, err)
        code, out, err = self.solo("-C", self.game, "state")
        self.assertEqual((code, json.loads(out)["title"]), (0, "The Red Tusk Hall"), err)
        self.assertIn("Tusk 🐉", (Path(self.game) / "campaign.toml").read_text(encoding="utf-8"))

    def test_new_needs_only_the_adventure(self):
        code, out, err = self.solo("new", str(RED_TUSK) + "/", "--seed", "3")
        self.assertEqual(code, 0, err)
        root = next((self.tmp / "games" / "campaigns").iterdir())
        self.assertTrue(root.name.startswith("red-tusk-"))
        self.assertIn(f"Started The Red Tusk Hall in {root}", out)
        self.assertEqual(json.loads(self.solo("state")[1])["pc"]["name"], json.loads((root / "state.json").read_text())["pc"]["name"])
        code, out, _ = self.solo("new", "red-tusk", "--seed", "3")
        self.assertIn(f"in {root}-2", out)

    def test_the_preview_is_the_hero_that_begins(self):
        code, out, _ = self.solo("character", "elf", "mage", "--seed", "11", "--name", "Ilyra", "--system", "dragonbane")
        preview = json.loads(out)
        code, _, err = self.solo("new", "red-tusk", "--character", "elf mage", "--seed", "11", "--name", "Ilyra")
        self.assertEqual(code, 0, err)
        pc = json.loads(self.solo("state")[1])["pc"]
        self.assertEqual({k: pc[k] for k in preview}, preview)
        self.assertEqual((preview["name"], preview["info"]["kin"], preview["info"]["profession"]), ("Ilyra", "Elf", "Mage"))

    def test_pre_made_heroes_by_id(self):
        code, _, err = self.solo("new", "red-tusk", "--character", "ragna")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(self.solo("state")[1])["pc"]["name"], "Ragna")

    def test_unknown_adventure_lists_what_there_is(self):
        code, _, err = self.solo("new", "blue-tusk")
        self.assertEqual(code, 1)
        self.assertIn("no adventure called 'blue-tusk'; available:", err)
        self.assertIn("red-tusk", err)

    def test_library_lists_packs_heroes_and_campaigns(self):
        self.new_game()
        library = json.loads(self.solo("library")[1])
        adventure = next(a for a in library["adventures"] if a["id"] == "red-tusk")
        self.assertEqual((adventure["system"], adventure["title"]), ("dragonbane", "The Red Tusk Hall"))
        system = next(s for s in library["systems"] if s["id"] == "dragonbane")
        self.assertEqual([t["id"] for t in system["creation"]], ["kin", "profession", "craft", "school", "age"])
        self.assertEqual(next(t for t in system["creation"] if t["id"] == "school")["after"], ["mage"])
        self.assertIn({"id": "ragna", "name": "Ragna", "info": "Dwarf, Fighter, Adult"}, system["characters"])
        # A campaign outside ~/Games/solo still shows up while it is the current one.
        [card] = library["campaigns"]
        self.assertEqual((card["path"], card["hero"], card["scene"], card["current"]), (self.game, "Ragna", "The Old Road", True))

    def test_a_pack_that_doesnt_load_is_left_out_not_the_whole_library(self):
        self.new_game()
        games = self.tmp / "games"
        (games / "systems" / "broken").mkdir(parents=True)
        (games / "systems" / "broken" / "system.toml").write_text('name = "Broken\n')
        (games / "adventures" / "torn").mkdir(parents=True)
        (games / "adventures" / "torn" / "adventure.toml").write_text("title = [\n")
        (Path(self.game) / "campaign.toml").write_text("title = \n")
        code, out, err = self.solo("library")
        self.assertEqual(code, 0, err)
        library = json.loads(out)
        self.assertEqual([p.split(":")[0] for p in library["problems"]], ["system broken", "adventure torn"])
        self.assertIn("dragonbane", [s["id"] for s in library["systems"]])
        self.assertIn("red-tusk", [a["id"] for a in library["adventures"]])
        self.assertEqual([c["title"] for c in library["campaigns"]], ["game"])  # listed by its folder, to delete

    def test_rest_through_the_cli(self):
        self.new_game()
        self.solo("-C", self.game, "commit", '{"pc": {"hp": "-5", "conditions": {"add": ["scared", "angry"]}}}')
        code, out, _ = self.solo("-C", self.game, "rest", "stretch", "--heal", "angry")
        report = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(report["summary"].startswith("Stretch rest; hp 9 -> "))
        self.assertIn("-angry", report["summary"])
        code, _, err = self.solo("-C", self.game, "rest", "stretch")
        self.assertIn("already taken a stretch rest this shift", err)

    def test_play_through_the_cli(self):
        os.environ["SOLO_SEED"] = "164"
        self.new_game()
        code, out, _ = self.solo("-C", self.game, "check", "sneaking")
        report = json.loads(out)
        # SOLO_SEED=164 rolls a 20 here: a Demon, which rolls its effect, ticks the ritual clock and rolls an omen
        self.assertEqual((code, report["summary"]), (0, "Sneaking: 20 vs 4, Demon!"))
        self.assertEqual(report["then"][:2], ["Demon effect (3): Someone noticed", "The ritual below 1/6"])
        self.assertNotIn("push", report)
        code, out, _ = self.solo("-C", self.game, "commit", '{"note": "horns", "facts": {"hall.alarm": true}}')
        self.assertEqual(json.loads(out)["then"][0], "The ritual below 2/6")
        code, out, _ = self.solo("-C", self.game, "move", "gate")
        code, out, _ = self.solo("-C", self.game, "scene")
        self.assertIn("# The Palisade Gate (gate)", out)
        self.assertIn("## Exits\n- hall: Into the hall", out)
        code, out, _ = self.solo("-C", self.game, "npc", "orc_leader")
        self.assertIn("## Secrets (GM only)", out)
        self.assertIn("[reveal when npc.orc_leader.attitude >= friendly]", out)

    def test_a_seeded_roll_says_so_in_the_log_and_the_book(self):
        # A GM could try seeds on a copy of the campaign and roll the one that lands well:
        # every event written under SOLO_SEED carries it, and the Book's beat shows it.
        self.new_game()
        code, out, _ = self.solo("-C", self.game, "check", "sneaking")
        self.assertEqual((code, json.loads(out)["event"]["seed"]), (0, 5))
        with campaign.session(self.game) as c:
            beat = [b for b in c.state["story"] if b["kind"] == "roll"][-1]
            opened = len(c.events)
        self.assertEqual(beat["seed"], 5)
        with unittest.mock.patch.dict(os.environ):
            del os.environ["SOLO_SEED"]
            code, out, _ = self.solo("-C", self.game, "check", "sneaking")
            self.assertEqual(code, 0)
            self.assertNotIn("seed", json.loads(out)["event"])
            with campaign.session(self.game) as c:
                self.assertFalse(any("seed" in e for e in c.events[opened:]))
                self.assertNotIn("seed", [b for b in c.state["story"] if b["kind"] == "roll"][-1])
            os.environ["SOLO_SEED"] = "lucky"
            code, _, err = self.solo("-C", self.game, "check", "sneaking")
        self.assertEqual(code, 1)
        self.assertIn("SOLO_SEED must be a whole number", err)

    def test_a_seeded_run_repeats_and_its_rolls_differ(self):
        # Every command's dice were seeded alike: under SOLO_SEED every 1d20 was the same number.
        totals = []
        for game in (self.game, str(self.tmp / "again")):
            self.solo("new", str(RED_TUSK), "--dir", game, "--character", str(RAGNA))
            totals.append([json.loads(self.solo("-C", game, "roll", "1d100")[1])["event"]["result"]["total"] for _ in range(6)])
        self.assertEqual(totals[0], totals[1])  # the same seed, the same run
        self.assertGreater(len(set(totals[0])), 1)

    def test_fights_and_the_oracle_through_the_cli(self):
        code, _, err = self.solo("new", str(RED_TUSK), "--dir", self.game, "--character", str(RAGNA), "--line", "spiders")
        self.assertEqual(code, 0, err)
        state = json.loads((Path(self.game) / "state.json").read_text())
        self.assertEqual(state["prefs"]["lines"], ["spiders"])
        self.assertEqual([w["id"] for w in state["kit"]["weapons"]], ["broadsword", "shield", "unarmed"])
        code, out, _ = self.solo("-C", self.game, "fight", "priest")
        report = json.loads(out)
        self.assertTrue(report["summary"].startswith("fight: "))
        self.assertIn("round 1; The hooded priest HP 14/14, armor 1", report["now"])
        code, out, err = self.solo("-C", self.game, "attack", "--with", "broadsword")
        self.assertEqual(code, 0, err)
        self.assertIn("(attack priest with Broadsword)", json.loads(out)["summary"])
        code, _, err = self.solo("-C", self.game, "attack", "--with", "shield")
        self.assertIn("Shield can't be used to attack", err)
        code, out, _ = self.solo("-C", self.game, "ask", "--meaning")
        self.assertTrue(json.loads(out)["summary"].startswith("meaning: "))
        code, _, err = self.solo("-C", self.game, "ask")
        self.assertIn("--meaning", err)
        code, out, _ = self.solo("-C", self.game, "prefs", "--veil", "drowning")
        self.assertEqual(json.loads(out), {"tone": "", "lines": ["spiders"], "veils": ["drowning"]})

    def test_the_current_campaign_is_found_without_flags(self):
        self.new_game()
        code, out, _ = self.solo("state")
        self.assertEqual((code, json.loads(out)["scene"]), (0, "road"))

    def test_errors_go_to_stderr_with_status_1(self):
        self.new_game()
        code, out, err = self.solo("-C", self.game, "commit", '{"mood": 1}')
        self.assertEqual((code, out), (1, ""))
        self.assertIn("unknown commit keys", err)
        code, _, err = self.solo("-C", self.game, "commit", "{not json")
        self.assertIn("isn't valid JSON", err)
        # A number too long for Python to read is a ValueError, not a JSONDecodeError.
        code, _, err = self.solo("-C", self.game, "commit", '{"chaos": ' + "1" * 5000 + "}")
        self.assertEqual(code, 1)
        self.assertIn("isn't valid JSON", err)

    def test_a_folder_named_with_c_never_falls_back_to_the_current_game(self):
        self.new_game()
        code, out, err = self.solo("-C", str(self.tmp / "gone"), "check", "sneaking")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("isn't a campaign folder", err)
        with campaign.session(self.game) as c:
            self.assertFalse([e for e in c.events if e["type"] == "check"])

    def test_a_bug_reaches_the_panel_as_one_line(self):
        self.new_game()
        os.environ.pop("SOLO_DEBUG")
        with unittest.mock.patch.object(campaign.Campaign, "check", side_effect=KeyError("hp")):
            code, out, err = self.solo("-C", self.game, "check", "sneaking")
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err.count("\n"), 1)
        self.assertIn("something went wrong (KeyError: 'hp')", err)
        self.assertNotIn("Traceback", err)

    def test_log_shows_the_last_n_events_and_none_for_zero(self):
        self.new_game()
        self.solo("-C", self.game, "commit", '{"note": "the gate creaks"}')
        code, out, _ = self.solo("-C", self.game, "log", "-n", "0")
        self.assertEqual((code, out), (0, ""))  # -0 was the whole log
        code, out, _ = self.solo("-C", self.game, "log", "-n", "1")
        self.assertEqual(out.splitlines(), ["#2 the gate creaks"])
        code, out, err = self.solo("-C", self.game, "log", "-n", "-3")  # all but three, it was
        self.assertEqual((code, out), (1, ""))
        self.assertIn("-n is how many of the last events to show, from 0 up; not -3", err)

    def test_a_reader_that_stops_early_ends_the_log_quietly(self):
        # solo log | head: the pipe closes under the output, and that was "something went wrong (BrokenPipeError)".
        self.new_game()
        with campaign.session(self.game) as c:
            for number in range(20):
                c.commit({"note": f"{number}: " + "the gate creaks " * 500})
        solo = subprocess.Popen([sys.executable, str(ROOT / "bin" / "solo"), "-C", self.game, "log", "-n", "30"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        solo.stdout.readline()
        solo.stdout.close()
        err = solo.stderr.read().decode()
        solo.stderr.close()
        self.assertEqual((solo.wait(), err), (1, ""))

    def test_help_initializes_the_formatter_in_a_fresh_process(self):
        for args in (("--help",), ("roll", "--help")):
            for color in ("0", "1"):
                with self.subTest(args=args, color=color):
                    env = {**os.environ, "FORCE_COLOR": color}
                    env.pop("NO_COLOR", None)
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "bin" / "solo"), *args],
                        env=env, capture_output=True, text=True, timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("usage:", result.stdout)
                    self.assertEqual(result.stderr, "")

    def test_a_usage_mistake_is_one_line_too(self):
        with self.assertRaises(SystemExit) as exit:
            self.solo("check")
        self.assertEqual(exit.exception.code, 2)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), self.assertRaises(SystemExit):
            cli.main(["ask", "--likely"])
        self.assertEqual(err.getvalue(), "solo: argument --likely: expected one argument (see solo ask --help)\n")

    def test_validate_the_example_packs(self):
        code, out, _ = self.solo("validate", "--system", "dragonbane", "--adventure", str(RED_TUSK))
        self.assertEqual((code, out.strip()), (0, "ok: house and red-tusk"))  # the rules the tests link in as dragonbane

    def test_the_bundled_names_alone_send_the_player_to_their_book(self):
        code, _, err = self.solo("validate", "--system", str(BUNDLED))
        self.assertEqual(code, 1)
        self.assertIn("make dragonbane BOOKS=<folder of your PDFs>", err)
        self.assertIn("Missing: time, push, rest", err)
        os.environ["SOLO_HOME"] = str(self.tmp / "empty")
        code, _, err = self.solo("new", str(RED_TUSK), "--dir", self.game, "--character", "ragna")
        self.assertEqual(code, 1)
        self.assertIn("Its rules come from your own book", err)
        _, out, _ = self.solo("library")
        library = json.loads(out)
        # Ironsworn ships complete, so it is the one game there is to play without a book.
        self.assertEqual([system["id"] for system in library["systems"]], ["ironsworn"])
        self.assertIn("system dragonbane: Dragonbane has only its names so far", library["problems"][0])

    def setup_on(self, *commands, plugin=False):
        """`solo setup` on a machine where only these commands are on PATH."""
        found = lambda name: f"/usr/bin/{name}" if name in commands else None
        with unittest.mock.patch("shutil.which", side_effect=found), unittest.mock.patch("subprocess.run"):
            return self.solo("setup", *(["--plugin"] if plugin else []))[1]

    def test_setup_links_are_idempotent(self):
        (self.tmp / "home" / ".claude").mkdir(parents=True)
        first = self.setup_on()
        second = self.setup_on()
        link = self.tmp / "home" / ".claude" / "skills" / "solo-gm"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (ROOT / "skills" / "solo-gm").resolve())
        self.assertIn("linked", first)
        self.assertFalse([line for line in second.splitlines() if line.startswith(("linked", "updated", "skipped"))])

    def test_setup_never_replaces_a_real_file(self):
        target = self.tmp / "home" / ".local" / "bin" / "solo"
        target.parent.mkdir(parents=True)
        target.write_text("mine")
        self.assertIn("skipped", self.setup_on())
        self.assertEqual(target.read_text(), "mine")

    def test_setup_links_skills_only_for_the_agents_that_are_installed(self):
        home = self.tmp / "home"
        (home / ".claude").mkdir(parents=True)
        self.setup_on()
        self.assertTrue((home / ".claude" / "skills" / "solo-gm").is_symlink())
        self.assertFalse([folder for folder in (".codex", ".agents", ".pi") if (home / folder).exists()])
        # Codex on PATH: its own folder and the shared one it also reads.
        self.setup_on("codex")
        self.assertTrue((home / ".codex" / "skills" / "solo-gm").is_symlink())
        self.assertTrue((home / ".agents" / "skills" / "solo-gm").is_symlink())
        self.assertFalse((home / ".pi").exists())

    def test_setup_says_what_is_missing_and_what_to_do(self):
        os.environ["AGENT"] = "claude"
        out = self.setup_on(plugin=True)
        self.assertIn("ok       Python 3.", out)
        self.assertIn("todo     omarchy and omarchy-shell not found", out)
        self.assertIn("optional hyprctl not found", out)
        self.assertIn("todo     the default agent is claude, and claude isn't on PATH", out)
        self.assertIn("no agent found (claude, codex or pi), so no skills were linked", out)
        self.assertIn("PyMuPDF", out)
        self.assertIn("Enable it with: omarchy plugin enable", out)
        out = self.setup_on("omarchy", "omarchy-shell", "hyprctl", "claude", plugin=True)
        self.assertIn("ok       omarchy and omarchy-shell", out)
        self.assertIn("ok       hyprctl", out)
        self.assertIn("ok       the GM is claude, which the Book runs", out)
        self.assertIn("todo     ~/.local/bin isn't on PATH", out)
        os.environ["PATH"] = str(self.tmp / "home" / ".local" / "bin")
        out = self.setup_on("omarchy", "omarchy-shell", "hyprctl", "claude", plugin=True)
        self.assertNotIn("todo", out)
        # make install enables the plugin itself when omarchy is there.
        self.assertNotIn("Enable it with", out)

    def test_setup_tells_an_agent_the_book_cant_run_from_one_it_can(self):
        os.environ["AGENT"] = "opencode"
        self.assertIn("the default agent is opencode, which the Book can't run", self.setup_on("opencode"))

    def test_solo_on_a_python_older_than_3_11_says_so_in_a_sentence(self):
        import runpy
        err = io.StringIO()
        with unittest.mock.patch("sys.version_info", (3, 10, 12)), redirect_stderr(err), \
                self.assertRaises(SystemExit) as stopped:
            runpy.run_path(str(ROOT / "bin" / "solo"), run_name="__main__")
        self.assertEqual(stopped.exception.code, 1)
        self.assertEqual(err.getvalue(), "solo needs Python 3.11 or newer, and this is Python 3.10: install a newer python3 and run it again.\n")

    def test_play_without_omarchy_explains_what_to_do(self):
        self.new_game()
        (self.tmp / "home" / ".claude").mkdir(parents=True, exist_ok=True)
        with unittest.mock.patch("shutil.which", return_value=None):
            code, out, _ = self.solo("play", self.game)
        self.assertEqual(code, 0)
        self.assertIn("omarchy-agent isn't available", out)
        # The GM needs solo and the skills, so play links them the first time, for the agents
        # that are there (Claude Code's folder is) and no others, as setup does.
        self.assertTrue((self.tmp / "home" / ".claude" / "skills" / "solo-gm").is_symlink())
        self.assertFalse([folder for folder in (".codex", ".agents", ".pi") if (self.tmp / "home" / folder).exists()])

    def test_play_focuses_a_gm_that_is_already_open(self):
        self.new_game()
        with unittest.mock.patch.object(cli, "_gm_window", return_value="0xabc"), \
                unittest.mock.patch("subprocess.run") as run, unittest.mock.patch("subprocess.Popen") as popen:
            _, out, _ = self.solo("play", self.game)
        self.assertIn("already open", out)
        run.assert_called_once_with(["hyprctl", "dispatch", "focuswindow", "address:0xabc"], capture_output=True)
        popen.assert_not_called()

    def test_the_gm_window_is_found_through_its_marked_process(self):
        root = Path(self.game)
        clients = json.dumps([{"pid": 100, "address": "0xgm"}, {"pid": 7, "address": "0xother"}])
        environ = {"300": f"PATH=/bin\0SOLO_GM={root}\0".encode(), "400": b"SOLO_GM=/elsewhere\0"}
        parents = {300: 200, 200: 100, 400: 7}

        def read_bytes(path):
            return environ[path.parent.name]

        with unittest.mock.patch("shutil.which", return_value="/usr/bin/hyprctl"), \
                unittest.mock.patch("subprocess.run", return_value=unittest.mock.Mock(stdout=clients)), \
                unittest.mock.patch("pathlib.Path.glob", return_value=[Path("/proc/400"), Path("/proc/300")]), \
                unittest.mock.patch("pathlib.Path.read_bytes", read_bytes), \
                unittest.mock.patch.object(cli, "_parent", lambda pid: parents.get(pid, 0)):
            self.assertEqual(cli._gm_window(root), "0xgm")

    def test_delete_takes_a_campaign_away_for_good(self):
        self.new_game()
        code, _, err = self.solo("delete", self.game)
        self.assertEqual(code, 1)
        self.assertIn("--yes", err)
        self.assertTrue(Path(self.game, "campaign.toml").exists())
        code, _, err = self.solo("delete", self.game, "--yes")
        self.assertEqual(code, 0, err)
        self.assertFalse(Path(self.game).exists())
        # It was the current campaign, so nothing is current now.
        self.assertFalse((self.tmp / "state" / "solo" / "current").exists())
        code, _, err = self.solo("delete", str(self.tmp), "--yes")
        self.assertEqual(code, 1)
        self.assertIn("isn't a campaign folder", err)

    def test_the_gm_cant_delete_a_campaign(self):
        self.new_game()
        with unittest.mock.patch.dict(os.environ, {"SOLO_BOOK": "1"}):
            code, _, err = self.solo("delete", self.game, "--yes")
        self.assertEqual(code, 1)
        self.assertTrue(Path(self.game, "campaign.toml").exists())

    def test_strike_cuts_the_last_gm_message_and_can_add_a_line_or_a_veil(self):
        self.new_game()
        self.assertEqual(self.solo("-C", self.game, "strike")[0], 1)  # nothing said yet
        self.solo("-C", self.game, "say", "A spider drops onto the road. What do you do?")
        code, out, _ = self.solo("-C", self.game, "strike", "--note", "no spiders", "--line", "spiders", "--veil", "the bite")
        self.assertEqual(code, 0)
        shown = json.loads(out)
        self.assertEqual((shown["struck"], shown["prefs"]["lines"], shown["prefs"]["veils"]), (2, ["spiders"], ["the bite"]))
        digest = self.solo("-C", self.game, "resume")[1]
        self.assertIn("Line (never in the story): spiders", digest)
        self.assertIn("## Cut by the player", digest)

    def test_the_gm_budget_is_the_players_to_see_and_raise(self):
        self.assertEqual(json.loads(self.solo("gm", "budget")[1]), {"limit": {"usd": 10.0, "turns": 200}})
        self.new_game()
        shown = json.loads(self.solo("-C", self.game, "gm", "budget", "25", "--turns", "300")[1])
        self.assertEqual(shown, {"limit": {"usd": 25.0, "turns": 300}, "spent": {"turns": 0, "cost_usd": 0.0}})
        code, _, err = self.solo("gm", "budget", "plenty")
        self.assertEqual(code, 1)
        self.assertIn("a budget is dollars", err)
        self.assertEqual(json.loads(self.solo("-C", self.game, "gm", "budget", "--reset")[1])["limit"], {"usd": 25.0, "turns": 300})

    def test_the_gm_pace_is_the_players_and_needs_no_campaign(self):
        self.assertEqual(json.loads(self.solo("gm", "pace")[1]), {"pace": "normal"})
        self.assertEqual(json.loads(self.solo("gm", "pace", "careful")[1]), {"pace": "careful"})
        self.assertEqual(json.loads(self.solo("gm", "pace")[1]), {"pace": "careful"})
        code, _, err = self.solo("gm", "pace", "ludicrous")
        self.assertEqual(code, 1)
        self.assertIn("quick, normal, careful", err)


class TranscriptCliTest(CliCase):
    def hook(self, **data):
        code, out, err = self.solo("say", "--hook", stdin=json.dumps({"cwd": self.game, **data}))
        self.assertEqual((code, out), (0, ""), err)
        return err

    def said(self):
        events = [json.loads(line) for line in (Path(self.game) / "events.jsonl").read_text().splitlines()]
        return [(e["by"], e["text"]) for e in events if e["type"] == "said"]

    def test_new_campaigns_record_the_conversation_through_hooks(self):
        self.new_game()
        settings = json.loads((Path(self.game) / ".claude" / "settings.json").read_text())
        for event in cli.HOOK_EVENTS:
            self.assertEqual(settings["hooks"][event], [{"hooks": [{"type": "command", "command": cli.HOOK}]}])
        self.assertIn("Bash(solo resume:*)", settings["permissions"]["allow"])
        self.assertIn("Bash(solo say:*)", settings["permissions"]["allow"])

    def test_play_brings_an_older_campaign_up_to_date(self):
        self.new_game()
        root = Path(self.game)
        (root / "AGENTS.md").write_text("Start every session with solo scene.")
        (root / ".claude" / "settings.json").write_text(json.dumps({
            "permissions": {"allow": ["Bash(solo scene:*)", "Bash(git status)"], "deny": ["Edit", "Write"]},
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify-send done"}]}]},
            "model": "mine",
        }))
        with unittest.mock.patch("shutil.which", return_value=None):
            self.solo("play", self.game)
            self.solo("play", self.game)
        self.assertIn("solo resume", (root / "AGENTS.md").read_text())
        settings = json.loads((root / ".claude" / "settings.json").read_text())
        self.assertEqual(settings["model"], "mine")
        self.assertEqual(settings["permissions"]["allow"].count("Bash(solo scene:*)"), 1)
        self.assertIn("Bash(git status)", settings["permissions"]["allow"])
        self.assertEqual([h["command"] for g in settings["hooks"]["Stop"] for h in g["hooks"]], ["notify-send done", cli.HOOK])

    def test_hooks_record_both_sides_of_the_table(self):
        self.new_game()
        self.hook(hook_event_name="UserPromptSubmit", prompt=cli.PLAY_PROMPT)
        self.hook(hook_event_name="Stop", last_assistant_message="Rain on the road. What do you do?")
        self.hook(hook_event_name="UserPromptSubmit", prompt="/compact")
        self.hook(hook_event_name="UserPromptSubmit", prompt="I walk up to the gate.")
        self.assertEqual(self.said(), [("gm", "Rain on the road. What do you do?"), ("player", "I walk up to the gate.")])

    def test_in_a_book_turn_the_hook_stands_down(self):
        # gm turn records the GM's words once, with its notes dropped; a second, raw copy would show twice.
        self.new_game()
        with unittest.mock.patch.dict(os.environ, {"SOLO_BOOK": "1"}):
            self.hook(hook_event_name="Stop", last_assistant_message="Time to narrate.\n\nRain on the road. What do you do?")
        self.assertEqual(self.said(), [])

    def test_the_stop_hook_reads_the_transcript_when_it_has_to(self):
        self.new_game()
        transcript = self.tmp / "transcript.jsonl"
        lines = [
            {"type": "user", "message": {"role": "user", "content": "I knock"}},
            {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "Let me look."}]}},
            {"type": "assistant", "message": {"id": "m1", "content": [{"type": "tool_use", "name": "Bash", "input": {}}]}},
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}},
            {"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "The gate creaks open."}]}},
            {"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "Who goes there?"}]}},
        ]
        transcript.write_text("\n".join(json.dumps(line) for line in lines) + "\nnot json\n")
        self.hook(hook_event_name="Stop", transcript_path=str(transcript))
        self.assertEqual(self.said(), [("gm", "The gate creaks open.\n\nWho goes there?")])

    def test_hooks_never_fail_the_turn(self):
        self.new_game()
        code, out, err = self.solo("say", "--hook", stdin="{broken")
        self.assertEqual((code, out), (0, ""))
        self.assertIn("solo say --hook", err)
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        code, out, _ = self.solo("say", "--hook", stdin=json.dumps({"cwd": str(outside), "hook_event_name": "Stop", "last_assistant_message": "hi"}))
        self.assertEqual((code, out, self.said()), (0, "", []))

    def test_a_gm_whose_reply_is_recorded_anyway_doesnt_record_a_draft(self):
        self.new_game()
        with unittest.mock.patch.dict(os.environ, {"SOLO_BOOK": "1"}):
            self.assertIn("not recorded", self.solo("-C", self.game, "say", "A draft.")[1])
            self.solo("-C", self.game, "say", "--player", "I wait.")  # the player's words still are
        with unittest.mock.patch.dict(os.environ, {"CLAUDECODE": "1"}):
            self.assertIn("not recorded", self.solo("-C", self.game, "say", "Another draft.")[1])
        with campaign.session(self.game) as c:
            self.assertEqual([(e["by"], e["text"]) for e in c.events if e["type"] == "said"], [("player", "I wait.")])

    def test_say_by_hand(self):
        self.new_game()
        self.assertEqual(self.solo("-C", self.game, "say", "What", "now?")[1], "recorded #2\n")
        self.assertEqual(self.solo("-C", self.game, "say", "-", stdin="What now?\n")[1], "already recorded\n")
        self.solo("-C", self.game, "say", "--player", "Run.")
        self.assertEqual(self.said(), [("gm", "What now?"), ("player", "Run.")])

    def test_resume_opens_a_new_campaign(self):
        self.new_game()
        code, out, _ = self.solo("-C", self.game, "resume")
        self.assertEqual(code, 0)
        self.assertIn("this is the opening", out)
        self.assertNotIn("Last said", out)

    def test_resume_gives_back_the_last_words_and_what_came_after(self):
        os.environ["SOLO_SEED"] = "16"  # the check below rolls a Demon, which sets off what the player doesn't see
        self.new_game()
        self.solo("-C", self.game, "say", "The road forks.")
        self.solo("-C", self.game, "say", "--player", "I go left.")
        opening = "Rain on the road.\n\n*Awareness 7 vs 10: success*\n\nWhat do you do?"
        self.solo("-C", self.game, "say", "-", stdin=opening)
        self.solo("-C", self.game, "check", "sneaking")
        code, out, _ = self.solo("-C", self.game, "resume")
        self.assertEqual(code, 0)
        self.assertIn(f"## Last said\n\n{opening}\n", out)
        self.assertIn("word for word", out)
        since = out.split("## Since then\n")[1].split("\n\n")[0].splitlines()
        self.assertEqual(since[0], "- #5 Sneaking: 20 vs 4, Demon!")
        self.assertTrue(any("(hidden from the player)" in line for line in since))
        self.assertIn("## Earlier (for you, don't repeat)\nGM: The road forks.\n\nPlayer: I go left.", out)
        self.assertIn("Wait for the player's answer.", out)
        self.solo("-C", self.game, "say", "--player", "I hide.")
        out = self.solo("-C", self.game, "resume")[1]
        self.assertIn("## Player since\nI hide.", out)
        self.assertIn("carry on from their words", out)

    def test_the_library_shows_where_each_game_stopped(self):
        self.new_game()
        self.solo("-C", self.game, "say", "-", stdin="\nThe gate is shut.\nWhat do you do?")
        card = json.loads(self.solo("library")[1])["campaigns"][0]
        self.assertEqual(card["said"], "The gate is shut.")


if __name__ == "__main__":
    unittest.main()
