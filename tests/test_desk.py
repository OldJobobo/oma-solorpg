"""Desktop effects, against a fake hyprctl that remembers what it was told."""

import json
import os
import shutil
import stat
import subprocess
import textwrap
import unittest
import unittest.mock
import wave
from pathlib import Path

from helpers import CampaignTest

from solo import desk, sounds


class DeskTest(CampaignTest):
    def setUp(self):
        super().setUp()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.calls = self.tmp / "hyprctl.calls"
        self.temperature = self.tmp / "temperature"
        self.temperature.write_text("6000")
        hyprctl = self.bin / "hyprctl"
        hyprctl.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import json, sys
            args = sys.argv[1:]
            with open({str(self.calls)!r}, "a") as f:
                f.write(json.dumps(args) + "\\n")
            if args[:2] == ["getoption", "general:col.active_border"]:
                print(json.dumps({{"option": "general:col.active_border", "custom": "ee33ccff ee00ff99 45deg", "set": True}}))
            elif args[:2] == ["getoption", "decoration:screen_shader"]:
                print(json.dumps({{"option": "decoration:screen_shader", "str": "/home/me/vibrance.frag", "set": True}}))
            elif args == ["hyprsunset", "temperature"]:
                print(open({str(self.temperature)!r}).read())
            elif args[:2] == ["hyprsunset", "temperature"] and len(args) == 3:
                open({str(self.temperature)!r}, "w").write(args[2])
            """))
        hyprctl.chmod(hyprctl.stat().st_mode | stat.S_IEXEC)
        patch = unittest.mock.patch.dict(os.environ, {"PATH": f"{self.bin}:/usr/bin:/bin", "XDG_RUNTIME_DIR": str(self.tmp / "run")})
        patch.start()
        self.addCleanup(patch.stop)
        # Never refresh the real shell or send a desktop notification from a test.
        which = shutil.which
        patcher = unittest.mock.patch.object(shutil, "which", side_effect=lambda name: which(name, path=str(self.bin))
                                            if name in ("omarchy-shell", "omarchy-notification-send", "notify-send") else which(name))
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, value in (("PACE", 0), ("SCREENSAVER", self.tmp / "branding" / "screensaver.txt")):
            patcher = unittest.mock.patch.object(desk, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def told(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def evals(self):
        return [c[1] for c in self.told() if c[0] == "eval" and "active_border" in c[1]]

    def shaders(self):
        """The screen shaders put up, in order (the path, "" for none)."""
        return [c[1].split("screen_shader = ", 1)[1].rsplit(" }", 2)[0].strip('"') for c in self.told()
                if c[0] == "eval" and "screen_shader" in c[1]]

    def test_a_flash_puts_the_players_gradient_back(self):
        self.assertTrue(desk.flash("dragon"))
        gold, back = self.evals()
        self.assertIn('active_border = "rgba(e8b923ff)"', gold)
        self.assertIn('active_border = { colors = { "rgba(33ccffee)", "rgba(00ff99ee)" }, angle = 45 }', back)

    def test_dying_holds_the_red_through_a_flash_until_it_ends(self):
        desk.dying(True)
        desk.flash("demon")
        desk.dying(False)
        dark, red, still_dark, back = self.evals()
        self.assertIn("7a0c0cff", dark)
        self.assertIn("d62828ff", red)
        self.assertIn("7a0c0cff", still_dark)
        self.assertIn("rgba(33ccffee)", back)

    def test_switched_off_effects_do_nothing(self):
        desk.set_settings({"borders": False, "screen": False})
        self.assertFalse(desk.flash("dragon"))
        self.assertEqual(self.evals(), [])
        self.assertEqual(self.shaders(), [])

    def test_candlelight_is_opt_in_even_with_other_settings_saved(self):
        self.assertFalse(desk.settings()["candle"])
        self.assertFalse(desk.candle(True))  # no settings file yet
        self.assertTrue(all(on for name, on in desk.settings().items() if name != "candle"))
        for changes in ({}, {"sound": False}):
            with self.subTest(changes=changes):
                desk.set_settings(changes)
                self.assertFalse(desk.settings()["candle"])
                self.assertFalse(desk.candle(True))
                self.assertEqual(self.temperature.read_text(), "6000")
                self.assertIsNone(desk._saved("temperature"))
        self.assertEqual(self.told(), [])

    def test_candlelight_warms_and_restores_the_temperature(self):
        desk.set_settings({"candle": True})
        desk.candle(True)
        desk.candle(True)  # twice: still remembers 6000, not the candle
        desk.candle(False)
        sets = [c[2] for c in self.told() if c[:2] == ["hyprsunset", "temperature"] and len(c) == 3]
        self.assertEqual(sets, ["3400", "3400", "6000"])
        self.assertIsNone(desk._saved("temperature"))

    def test_candlelight_restores_both_daylight_and_a_warmer_nightlight(self):
        desk.set_settings({"candle": True})
        for original in (6500, 3000):
            with self.subTest(original=original):
                self.temperature.write_text(str(original))
                self.assertTrue(desk.candle(True))
                self.assertEqual(int(self.temperature.read_text()), min(original, desk.CANDLE))
                self.assertTrue(desk.restore()["candle"])
                self.assertEqual(int(self.temperature.read_text()), original)

    def test_restoring_candlelight_leaves_a_manual_nightlight_change_alone(self):
        desk.set_settings({"candle": True})
        for chosen in (6500, 4000, 3000):
            with self.subTest(chosen=chosen):
                self.temperature.write_text("4000")  # nightlight was on before the Book opened
                desk.candle(True)
                self.temperature.write_text(str(chosen))  # the player changes it while reading
                self.assertFalse(desk.restore()["candle"])
                self.assertEqual(int(self.temperature.read_text()), chosen)
                self.assertIsNone(desk._saved("temperature"))

    def test_switching_candlelight_off_restores_an_effect_already_in_place(self):
        desk.set_settings({"candle": True})
        desk.candle(True)
        desk.set_settings({"candle": False})
        self.assertEqual(self.temperature.read_text(), "6000")
        self.assertFalse(desk.candle(True))
        self.assertEqual(self.temperature.read_text(), "6000")

    def test_a_failed_candlelight_restore_keeps_the_temperature_for_a_retry(self):
        desk.set_settings({"candle": True})
        desk.candle(True)
        run = desk._run
        for failed in (["hyprctl", "hyprsunset", "temperature"],
                       ["hyprctl", "hyprsunset", "temperature", "6000"]):
            with self.subTest(failed=failed):
                with unittest.mock.patch.object(desk, "_run", side_effect=lambda cmd: None if cmd == failed else run(cmd)):
                    self.assertFalse(desk.candle(False))
                self.assertEqual(desk._saved("temperature"), 6000)
                self.assertEqual(self.temperature.read_text(), "3400")
        self.assertTrue(desk.candle(False))
        self.assertEqual(self.temperature.read_text(), "6000")
        self.assertIsNone(desk._saved("temperature"))

    def test_the_screensaver_shows_the_hero_and_goes_back(self):
        saver = desk.SCREENSAVER
        saver.parent.mkdir()
        saver.write_text("OMARCHY\n")
        with self.session() as c:
            c.say("The rain falls on the old road. What do you do?")
        self.assertTrue(desk.screensaver(True, self.root))
        text = saver.read_text()
        self.assertIn("Ragna", text)
        self.assertIn("The rain falls on the old road.", text)
        self.assertIn("[=====|==|=====]", text)  # the portrait's helmet
        desk.restore()
        self.assertEqual(saver.read_text(), "OMARCHY\n")
        self.assertFalse(saver.with_name("screensaver.txt.solo-play").exists())

    def remembering(self):
        """A hyprctl that keeps the border it is given, and fails every call while a file says so."""
        border, failing = self.tmp / "border", self.tmp / "failing"
        border.write_text("ee33ccff ee00ff99 45deg")
        (self.bin / "hyprctl").write_text(textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import json, os, re, sys
            args = sys.argv[1:]
            if os.path.exists({str(failing)!r}):
                sys.exit(1)
            if args[:2] == ["getoption", "general:col.active_border"]:
                print(json.dumps({{"custom": open({str(border)!r}).read()}}))
            elif args[:2] == ["getoption", "decoration:screen_shader"]:
                print(json.dumps({{"str": "[[EMPTY]]"}}))
            elif args[0] == "eval" and "active_border" in args[1]:
                colours = re.findall(r"rgba\\(([0-9a-f]{{6}})([0-9a-f]{{2}})\\)", args[1])
                angle = re.search(r"angle = (\\d+)", args[1])
                open({str(border)!r}, "w").write(" ".join(a + c for c, a in colours) + (f" {{angle.group(1)}}deg" if angle else ""))
            """))
        return border, failing

    def test_a_restore_that_failed_keeps_the_players_border_for_the_next(self):
        # The saved border was forgotten even when hyprctl failed; the next effect then saved its own dark red as the player's.
        border, failing = self.remembering()
        desk.dying(True)
        self.assertEqual(border.read_text(), "ff7a0c0c")
        failing.write_text("yes")
        self.assertEqual(desk.restore()["borders"], False)
        failing.unlink()
        desk.flash("dragon")
        self.assertEqual(border.read_text(), "ee33ccff ee00ff99 45deg")
        self.assertIsNone(desk._saved("border"))

    def test_an_effects_own_colour_is_never_kept_as_the_players(self):
        border, _ = self.remembering()
        border.write_text("ff7a0c0c")  # the dying red, left by a run that lost what it saved
        desk.set_settings({"screen": False})
        self.assertFalse(desk.flash("dragon"))
        self.assertIsNone(desk._saved("border"))
        self.assertEqual(border.read_text(), "ff7a0c0c")

    def test_an_omens_words_are_never_read_as_an_option(self):
        calls = self.tmp / "notify.calls"
        for name in ("notify-send", "omarchy-notification-send"):
            script = self.bin / name
            script.write_text(f"#!/usr/bin/env python3\nimport json, sys\nopen({str(calls)!r}, 'a').write(json.dumps(sys.argv) + '\\n')\n")
            script.chmod(script.stat().st_mode | stat.S_IEXEC)
            desk.omen("--urgency=critical")
            script.unlink()
        sent, omarchy = [json.loads(line) for line in calls.read_text().splitlines()]
        self.assertEqual(sent[-3:], ["--", "An omen", "--urgency=critical"])  # GLib reads no option after --
        self.assertEqual(omarchy[-2:], ["An omen", "\u200b--urgency=critical"])  # no "--" there: no option by that name

    def test_nothing_is_changed_when_the_border_cant_be_read(self):
        (self.bin / "hyprctl").write_text("#!/bin/sh\nexit 1\n")
        self.assertFalse(desk.flash("dragon"))
        self.assertFalse(desk.dying(True))

    def test_a_flash_floods_the_screen_and_puts_the_players_shader_back(self):
        self.assertTrue(desk.flash("dragon"))
        shown = self.shaders()
        self.assertGreater(len(shown), 10)  # it rises and falls a step at a time
        self.assertTrue(all("/shaders/dragon-" in path for path in shown[:-1]))
        self.assertEqual(shown[-1], "/home/me/vibrance.frag")
        levels = [float(Path(path).read_text().split("const float level = ")[1].split(";")[0]) for path in shown[:-1]]
        self.assertEqual(max(levels), 1.0)
        self.assertLess(levels[-1], 0.1)
        self.assertEqual(levels.index(1.0), next(i for i, v in enumerate(levels) if v == max(levels)))

    def test_a_blow_jolts_the_screen_but_leaves_the_borders(self):
        self.assertTrue(desk.flash("hit"))
        self.assertEqual(self.evals(), [])
        self.assertIn("/shaders/hit-", self.shaders()[0])

    def test_dying_holds_through_a_flash_and_closes_in_with_failures(self):
        desk.dying(True, failures=0)
        desk.flash("demon")
        desk.dying(True, failures=2)
        desk.dying(False)
        shown = self.shaders()
        self.assertIn("/shaders/dying-", shown[0])
        self.assertIn("const float weak = 0.000;", Path(shown[0]).read_text())
        self.assertIn("/shaders/demon-", shown[1])
        after_flash = shown.index(next(p for p in shown[1:] if "/dying-" in p))
        self.assertTrue(all("/demon-" in p for p in shown[1:after_flash]))
        self.assertIn("const float weak = 0.800;", Path(shown[-2]).read_text())
        self.assertEqual(shown[-1], "/home/me/vibrance.frag")

    def test_death_greys_the_screen_ends_the_dying_and_gives_it_back(self):
        desk.dying(True)
        self.assertTrue(desk.death())
        shown = self.shaders()
        greys = [p for p in shown if "/death-" in p]
        self.assertGreater(len(greys), 20)
        self.assertEqual(shown[-1], "/home/me/vibrance.frag")
        self.assertIn("rgba(33ccffee)", self.evals()[-1])  # the borders are back too

    def test_a_newer_moment_takes_the_screen_over(self):
        old = desk._screen_begin()
        new = desk._screen_begin()
        self.assertFalse(desk._screen_step(old, "hit", level=1))
        self.assertTrue(desk._screen_step(new, "hit", level=1))
        desk._screen_end(old)  # the old one ending hands nothing back
        self.assertIn("/shaders/hit-", self.shaders()[-1])
        desk._screen_end(new)
        self.assertEqual(self.shaders()[-1], "/home/me/vibrance.frag")

    def test_an_omen_ripples_the_screen_and_notifies(self):
        self.assertTrue(desk.omen("The bells ring by themselves."))
        ripples = [p for p in self.shaders() if "/shaders/omen-" in p]
        self.assertGreater(len(set(ripples)), 10)  # the phase moves the ripple a step at a time
        self.assertEqual(self.shaders()[-1], "/home/me/vibrance.frag")

    def test_restore_takes_down_a_held_screen_and_switching_it_off_stops_it(self):
        desk.dying(True)
        desk.restore()
        self.assertEqual(self.shaders()[-1], "/home/me/vibrance.frag")
        desk.set_settings({"screen": False})
        before = len(self.shaders())
        desk.flash("hit")
        desk.death()
        self.assertEqual(len(self.shaders()), before)

    def test_leftover_shaders_of_ours_are_not_taken_for_the_players(self):
        (self.bin / "hyprctl").write_text(textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import json, sys
            if sys.argv[1:3] == ["getoption", "decoration:screen_shader"]:
                print(json.dumps({{"str": {str(desk._runtime() / "shaders" / "hit-0.frag")!r}}}))
            """))
        self.assertEqual(desk._shader_now(), {"path": ""})

    @unittest.skipUnless(shutil.which("glslangValidator"), "glslangValidator is not installed")
    def test_every_shader_compiles_at_every_level(self):
        for name, values in (("dragon", {"level": 1}), ("demon", {"level": 0.5}), ("hit", {"level": 0.05}),
                             ("death", {"level": 1}), ("omen", {"level": 0.3, "phase": 1.2}), ("dying", {"weak": 0.4})):
            path = desk._bake(name, **values)
            self.assertNotIn("{{", Path(path).read_text())
            self.assertNotIn("uniform float time", Path(path).read_text())  # it needs damage tracking off
            done = subprocess.run(["glslangValidator", path], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, f"{name}: {done.stdout}")


class SoundTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache.cleanup)
        patch = unittest.mock.patch.dict(os.environ, {"XDG_CACHE_HOME": self.cache.name,
                                                     "XDG_CONFIG_HOME": str(Path(self.cache.name) / "config")})
        patch.start()
        self.addCleanup(patch.stop)

        bundle = unittest.mock.patch.object(sounds, "BUNDLED", Path(self.cache.name) / "no-bundle")
        bundle.start()
        self.addCleanup(bundle.stop)

    def test_every_sound_is_a_short_clean_wav(self):
        for name in sounds.names():
            with wave.open(str(sounds.path(name))) as w:
                self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, sounds.RATE))
                seconds = w.getnframes() / w.getframerate()
                frames = w.readframes(w.getnframes())
            self.assertTrue(0.3 < seconds < 6, name)
            samples = memoryview(frames).cast("h")
            self.assertLess(max(abs(s) for s in samples), 32767 * 0.75, name)  # headroom, no clipping
            self.assertLess(abs(samples[-1]), 50, name)  # ends in silence, no click

    def test_the_dice_land_with_the_books(self):
        self.assertAlmostEqual(sounds.LAND, 1.94, places=2)
        with wave.open(str(sounds.path("dice"))) as w:
            samples = memoryview(w.readframes(w.getnframes())).cast("h")
        loudest = max(range(len(samples)), key=lambda i: abs(samples[i]))
        self.assertAlmostEqual(loudest / sounds.RATE, sounds.LAND, delta=0.03)

    def test_a_changed_recipe_replaces_the_old_file(self):
        first = sounds.path("page")
        with unittest.mock.patch.object(sounds, "VERSION", sounds.VERSION + 1):
            second = sounds.path("page")
        self.assertNotEqual(first, second)
        self.assertFalse(first.exists())
