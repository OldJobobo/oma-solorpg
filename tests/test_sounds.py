"""Recorded CC0 assets, local overrides, and the synthesis fallback; no audio device."""

import os
import tempfile
import unittest
from unittest.mock import patch
import wave
from pathlib import Path

from solo import desk, sounds


class Recordings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "config"
        env = patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.root / "cache"),
                                      "XDG_CONFIG_HOME": str(self.config)})
        env.start()
        self.addCleanup(env.stop)

    def recording(self, name, folder=None, channels=2, rate=48000, seconds=0.1):
        target = (folder or self.config / "solo" / "sounds") / f"{name}.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target), "wb") as out:
            out.setnchannels(channels)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(b"\0\0" * int(rate * seconds) * channels)
        return target

    def test_bundled_recordings_are_available_without_local_setup(self):
        kit = desk.sound_kit()
        self.assertTrue(kit["split_dice"])
        for name in (*sounds.DICE_PARTS, "page"):
            path = Path(kit["sounds"][name])
            self.assertEqual(path, sounds.BUNDLED / f"{name}.wav")
            self.assertEqual(sounds._recording(path), path)
            with wave.open(str(path)) as w:
                self.assertEqual((w.getnchannels(), w.getsampwidth()), (2, 2))
                self.assertGreater(w.getnframes(), 0)
        self.assertFalse((self.root / "cache" / "solo-play" / "sounds" / f"page-{sounds.VERSION}.wav").exists())

    def test_local_page_overrides_bundle_without_modifying_the_file(self):
        custom = self.recording("page")
        before = custom.read_bytes()
        self.assertEqual(sounds.path("page"), custom)
        self.assertEqual(custom.read_bytes(), before)
        custom.unlink()
        self.assertEqual(sounds.path("page"), sounds.BUNDLED / "page.wav")
        with self.assertRaises(KeyError):
            sounds.path("../page")

    def test_dice_use_a_complete_local_set_or_a_complete_bundle_not_a_mix(self):
        bundled = sounds.dice_parts()
        self.recording("dice-roll")
        self.assertEqual(sounds.dice_parts(), bundled)
        for name in sounds.DICE_PARTS[1:]:
            self.recording(name)
        self.assertEqual(sounds.dice_parts(), {
            name: str(self.config / "solo" / "sounds" / f"{name}.wav") for name in sounds.DICE_PARTS})
        (self.config / "solo" / "sounds" / "dice-land.wav").write_bytes(b"broken")
        self.assertEqual(sounds.dice_parts(), bundled)

    def test_invalid_empty_truncated_and_oversized_overrides_fall_back(self):
        expected = sounds.path("page")
        for options in ({"seconds": 0}, {"seconds": 31, "rate": 8000}, {"channels": 3}, {"rate": 1000}):
            self.recording("page", **options)
            self.assertEqual(sounds.path("page"), expected)
        custom = self.recording("page")
        for bad in (custom.read_bytes()[:-20], b"not a WAV"):
            custom.write_bytes(bad)
            self.assertEqual(sounds.path("page"), expected)
            self.assertEqual(custom.read_bytes(), bad)
        custom = self.recording("page")
        with custom.open("r+b") as out:
            out.truncate(16 * 1024 * 1024 + 1)
        self.assertEqual(sounds.path("page"), expected)

    def test_missing_or_incomplete_bundles_keep_synthesized_dice_and_page(self):
        missing = self.root / "no-bundle"
        self.recording("dice-roll", folder=missing)
        with patch.object(sounds, "BUNDLED", missing):
            self.assertFalse(desk.sound_kit()["split_dice"])
            self.assertEqual(sounds.dice_parts(), {})
            for name in ("dice", "dice-short", "page"):
                self.assertNotEqual(sounds.path(name).parent, missing)
                with wave.open(str(sounds.path(name))) as w:
                    self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, sounds.RATE))

    def test_page_volume_is_quieter_for_recordings_and_other_sounds_are_unchanged(self):
        for binary, quieter in (("pw-play", ["pw-play", "--volume=0.75"]),
                                ("paplay", ["paplay", "--volume=49152"]),
                                ("aplay", ["aplay", "-q"])):
            with self.subTest(binary=binary), patch.object(sounds.shutil, "which", side_effect=lambda name: name == binary):
                self.assertEqual(sounds.player("page"), quieter)
                self.assertEqual(sounds.player("dice"), sounds.player())
                self.assertEqual(desk.sound_kit()["commands"]["page"], quieter)
                custom = self.recording("page")
                with patch.object(sounds.subprocess, "Popen") as play:
                    self.assertTrue(sounds.play("page"))
                    self.assertEqual(play.call_args.args[0], quieter + [str(custom)])
        with patch.object(sounds.shutil, "which", return_value=None):
            self.assertIsNone(sounds.player("page"))
            self.assertFalse(sounds.play("page"))
