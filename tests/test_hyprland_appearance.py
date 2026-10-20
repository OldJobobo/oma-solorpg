"""Resolved options from Lua/hyprlang share the same hyprctl JSON contract."""

import json
import subprocess
import unittest
from unittest.mock import patch

from solo.hyprland import OPTIONS, appearance, decode_appearance


def options(**overrides):
    values = [
        {"css": "10 20 30 40"}, {"int": 8}, {"int": 2},
        {"gradient": "ff123456 ffabcdef 45deg"}, {"bool": True},
        {"int": 12}, {"gradient": "99000000 0deg"}, {"vec2": [-2, 3]},
    ]
    return "\n\n".join(json.dumps({"option": key, **overrides.get(key, value)})
                       for key, value in zip(OPTIONS, values))


class HyprlandAppearanceTests(unittest.TestCase):
    def test_batch_resolves_asymmetric_gaps_argb_gradient_and_shadow(self):
        result = decode_appearance(options())
        self.assertTrue(result["available"])
        self.assertEqual(result["gaps"], dict(top=10, right=20, bottom=30, left=40))
        self.assertEqual(result["rounding"], 8)
        self.assertEqual(result["border_width"], 2)
        self.assertEqual(result["border"], dict(colors=["#ff123456", "#ffabcdef"], angle=45, enabled=True))
        self.assertEqual(result["shadow"], dict(enabled=True, range=12, color="#99000000", offset=[-2, 3]))

    def test_css_shorthand_and_disabled_decoration(self):
        for css, expected in (("0", [0, 0, 0, 0]), ("1 2", [1, 2, 1, 2]), ("1 2 3", [1, 2, 3, 2])):
            result = decode_appearance(options(**{"general:gaps_out": {"css": css},
                                                  "decoration:shadow:enabled": {"bool": False},
                                                  "general:border_size": {"int": 0}}))
            self.assertEqual(list(result["gaps"].values()), expected)
            self.assertFalse(result["shadow"]["enabled"])
            self.assertEqual(result["border_width"], 0)

    def test_one_read_only_batch_and_safe_unavailable_fallback(self):
        with patch("solo.hyprland.subprocess.run", return_value=subprocess.CompletedProcess([], 0, options())) as run:
            self.assertTrue(appearance()["available"])
            command = run.call_args.args[0]
            self.assertEqual(command[:3], ["hyprctl", "--batch", "-j"])
            self.assertEqual(command[3].count("getoption "), len(OPTIONS))
        for failure in (FileNotFoundError(), subprocess.TimeoutExpired("hyprctl", 3),
                        subprocess.CalledProcessError(1, "hyprctl")):
            with patch("solo.hyprland.subprocess.run", side_effect=failure):
                self.assertFalse(appearance()["available"])
        for output in ("", "not JSON", '{}', options(**{"general:gaps_out": {"css": "nan"}}),
                       options(**{"general:col.active_border": {"gradient": "bad colour"}}),
                       options(**{"decoration:shadow:offset": {"vec2": [1]}})):
            with patch("solo.hyprland.subprocess.run", return_value=subprocess.CompletedProcess([], 0, output)):
                self.assertFalse(appearance()["available"], output)
