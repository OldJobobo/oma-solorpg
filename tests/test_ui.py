"""Independent, persistent player-owned Book and Table/Settings scales."""

import json
import os
import subprocess
import sys
import unittest.mock

from test_cli import CliCase
import solo.ui as ui
from solo import SoloError
from solo.library import REPO


class AppScaleTest(CliCase):
    def test_all_five_scales_round_trip_without_changing_the_other_surface(self):
        expected = {"book_scale": 1, "table_scale": 1, "honor_hyprland": False}
        self.assertEqual(ui.settings(), expected)
        for target in ("book", "table"):
            for scale in ui.SCALES:
                code, out, err = self.solo("ui", f"--{target}-scale={scale}")
                self.assertEqual(code, 0, err)
                expected[target + "_scale"] = scale
                self.assertEqual(json.loads(out), expected)
                self.assertEqual(ui.settings(), expected)
                self.assertEqual(json.loads(self.solo("ui")[1]), expected)
        self.assertFalse((self.tmp / "state" / "solo" / "current").exists())

    def test_legacy_shared_scale_migrates_without_resizing_either_surface(self):
        path = self.tmp / "state" / "solo" / "ui.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"scale": 1.75}')
        self.assertEqual(ui.settings(), {"book_scale": 1.75, "table_scale": 1.75, "honor_hyprland": False})
        self.assertEqual(json.loads(path.read_text()), {"scale": 1.75})  # reading does not rewrite preferences
        self.assertEqual(ui.set_scales(book_scale=2), {"book_scale": 2, "table_scale": 1.75, "honor_hyprland": False})
        self.assertEqual(json.loads(path.read_text()), {"book_scale": 2, "table_scale": 1.75, "honor_hyprland": False})

    def test_both_scoped_flags_and_the_legacy_explicit_both_option(self):
        code, out, err = self.solo("ui", "--book-scale=1.25", "--table-scale=1.75")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {"book_scale": 1.25, "table_scale": 1.75, "honor_hyprland": False})
        code, out, err = self.solo("ui", "--scale=1.5")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {"book_scale": 1.5, "table_scale": 1.5, "honor_hyprland": False})
        code, _, _ = self.solo("ui", "--scale=2", "--book-scale=1")
        self.assertEqual(code, 1)
        self.assertEqual(ui.settings(), {"book_scale": 1.5, "table_scale": 1.5, "honor_hyprland": False})

    def test_bad_scale_never_replaces_either_saved_choice(self):
        expected = ui.set_scales(book_scale=1.5, table_scale=1.75)
        for key in ("book_scale", "table_scale"):
            for scale in (0, -1, 1.1, 3, float("nan"), float("inf"), True, "1.5"):
                with self.subTest(key=key, scale=scale):
                    with self.assertRaisesRegex(SoloError, "scale must be"):
                        ui.set_scales(**{key: scale})
                    self.assertEqual(ui.settings(), expected)
        with self.assertRaises(SoloError):
            ui.set_scale(None)
        with self.assertRaises(SoloError):
            ui.set_scales(book_scale=2, table_scale=3)
        for target in ("book", "table"):
            for scale in ("nan", "inf", "1.1", "0", "3"):
                code, _, err = self.solo("ui", f"--{target}-scale={scale}")
                self.assertEqual(code, 1, err)
                self.assertEqual(ui.settings(), expected)

    def test_corrupt_scoped_values_do_not_reset_a_valid_sibling(self):
        path = self.tmp / "state" / "solo" / "ui.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        defaults = {"book_scale": 1, "table_scale": 1, "honor_hyprland": False}
        for text in ('{', 'null', '[]', 'true', '{}', '{"scale": true}', '{"scale": 100}', '{"scale": "1.5"}'):
            path.write_text(text)
            self.assertEqual(ui.settings(), defaults, text)
        path.write_text('{"book_scale": 1.25, "table_scale": "bad"}')
        self.assertEqual(ui.settings(), {"book_scale": 1.25, "table_scale": 1, "honor_hyprland": False})
        path.write_text('{"scale": 1.75, "book_scale": 2}')
        self.assertEqual(ui.settings(), {"book_scale": 2, "table_scale": 1.75, "honor_hyprland": False})

    def test_publish_failure_preserves_both_choices_and_cleans_up(self):
        expected = ui.set_scales(book_scale=1.25, table_scale=1.75)
        with unittest.mock.patch.object(ui.os, "replace", side_effect=OSError("not writable")):
            with self.assertRaises(OSError):
                ui.set_scales(book_scale=2)
        self.assertEqual(ui.settings(), expected)
        self.assertEqual({p.name for p in (self.tmp / "state" / "solo").iterdir()}, {"ui.json", "ui.lock"})

    def test_concurrent_scoped_writers_keep_both_choices(self):
        for _ in range(3):
            ui.set_scale(1)
            children = [subprocess.Popen([sys.executable, str(REPO / "bin" / "solo"), "ui", flag],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        for flag in ("--book-scale=2", "--table-scale=1.75")]
            for child in children:
                _, error = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, error)
            self.assertEqual(ui.settings(), {"book_scale": 2, "table_scale": 1.75, "honor_hyprland": False})

    def test_the_gm_can_read_but_cannot_change_either_scale(self):
        from solo import cli
        self.assertNotIn("ui", cli.GM_COMMANDS)
        with unittest.mock.patch.dict(os.environ, {"SOLO_BOOK": "1"}):
            self.assertEqual(self.solo("ui")[0], 0)
            for flag in ("--book-scale=2", "--table-scale=2", "--scale=2", "--honor-hyprland=on"):
                code, _, err = self.solo("ui", flag)
                self.assertEqual(code, 1)
                self.assertIn("the player's", err)
        self.assertEqual(ui.settings(), {"book_scale": 1, "table_scale": 1, "honor_hyprland": False})

    def test_hyprland_preference_preserves_scales_and_survives_scale_changes(self):
        ui.set_scales(book_scale=1.5, table_scale=2)
        for enabled in (True, False, True):
            code, out, err = self.solo("ui", "--honor-hyprland=" + ("on" if enabled else "off"))
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out), {"book_scale": 1.5, "table_scale": 2, "honor_hyprland": enabled})
        self.assertTrue(ui.set_scale(1)["honor_hyprland"])
        for invalid in ("on", 1, [], {}):
            with self.assertRaises(SoloError):
                ui.set_scales(honor_hyprland=invalid)
        path = self.tmp / "state" / "solo" / "ui.json"
        path.write_text('{"honor_hyprland": "true"}')
        self.assertFalse(ui.settings()["honor_hyprland"])
