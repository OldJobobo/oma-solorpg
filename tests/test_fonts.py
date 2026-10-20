"""Font discovery uses serif metadata, never a misleading family name."""

import json
import struct
import subprocess
from unittest.mock import patch

from test_cli import CliCase
from solo import SoloError, fonts, ui


class SerifFontsTest(CliCase):
    def font(self, name="Reading.ttf", family_class=0, kind=2, serif=2, proportion=3):
        os2 = bytearray(42)
        os2[30] = family_class
        os2[32] = kind
        os2[33] = serif
        os2[35] = proportion
        path = self.tmp / name
        path.write_bytes(struct.pack(">4sHHHH", b"\0\1\0\0", 1, 0, 0, 0)
                         + struct.pack(">4sIII", b"OS/2", 0, 28, len(os2)) + os2)
        return path

    def test_metadata_classifies_serif_sans_mono_and_malformed_faces(self):
        self.assertTrue(fonts._serif(self.font()))
        self.assertFalse(fonts._serif(self.font(serif=11)))
        self.assertTrue(fonts._serif(self.font(kind=0, serif=0, family_class=5)))
        self.assertFalse(fonts._serif(self.font(proportion=9)))
        path = self.tmp / "broken.ttf"
        for data in (b"", b"not a font", b"ttcf", b"\0\1\0\0\0\1"):
            path.write_bytes(data)
            self.assertFalse(fonts._serif(path))
        self.assertFalse(fonts._serif(self.tmp / "missing.ttf"))

    def test_collection_face_offsets_are_supported(self):
        path = self.font()
        data = bytearray(path.read_bytes())
        # TTC table offsets are relative to the collection, not the face.
        struct.pack_into(">I", data, 20, 48)
        path.write_bytes(b"ttcf" + struct.pack(">IIII", 0x10000, 2, 20, 20) + data)
        self.assertTrue(fonts._serif(path, 1))
        self.assertFalse(fonts._serif(path, 2))

    def test_discovery_deduplicates_sorts_and_does_not_guess_by_name(self):
        serif = self.font()
        sans = self.font("Sans.ttf", serif=11)
        output = (f"{serif}\t0\tzeta Reading\t\n" * 2
                  + f"{serif}\t0\tAlpha\t0\n"
                  + f"{sans}\t0\tMisleading Serif\t\n"
                  + f"{serif}\t0\tMono\t100\n"
                  + "malformed\n")
        with patch.object(fonts.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output)) as run:
            self.assertEqual(fonts.serif_fonts(), ["Alpha", "zeta Reading"])
            self.assertIn(":lang=en", run.call_args.args[0])
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("fc-list", 15)):
            with patch.object(fonts.subprocess, "run", side_effect=error), self.assertRaises(SoloError):
                fonts.serif_fonts()

    def test_verified_reading_fallback_only_applies_to_unclassified_fonts(self):
        unclassified = self.font("Unknown.ttf", kind=0, serif=0)
        sans = self.font("Sans.ttf", serif=11)
        self.assertIsNone(fonts._serif(unclassified))
        output = (f"{unclassified}\t0\tLiterata\t\n"
                  + f"{unclassified}\t0\tNewsreader\t\n"
                  + f"{unclassified}\t0\tBitter\t\n"
                  + f"{unclassified}\t0\tLibron\t\n"
                  + f"{unclassified}\t0\tUnverified Reading Serif\t\n")
        with patch.object(fonts.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output)):
            self.assertEqual(fonts.serif_fonts(), ["Bitter", "Libron", "Literata", "Newsreader"])
        output = f"{sans}\t0\tLiterata\t\n"
        with patch.object(fonts.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output)):
            self.assertEqual(fonts.serif_fonts(), [])

    def test_curated_collection_fallback_does_not_admit_sans_or_arbitrary_nv_names(self):
        unclassified = self.font("Unknown.ttf", kind=0, serif=0)
        excluded = {"NV Jost", "NV Legible Next", "NV Ancizar Sans", "NV Lodestar", "NV Disleksio", "NV Unverified Serif"}
        families = fonts.UNCLASSIFIED_READING_FAMILIES | excluded
        output = "".join(f"{unclassified}\t0\t{family}\t\n" for family in families)
        with patch.object(fonts.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output)):
            self.assertEqual(fonts.serif_fonts(), sorted(fonts.UNCLASSIFIED_READING_FAMILIES, key=str.casefold))

    def test_saved_override_is_independent_and_resettable(self):
        ui.set_scales(book_scale=1.5, table_scale=2)
        with patch.object(fonts, "serif_fonts", return_value=["Reading Face"]):
            saved = ui.set_scales(book_serif_font="Reading Face")
        self.assertEqual(saved, {"book_scale": 1.5, "table_scale": 2, "book_serif_font": "Reading Face"})
        self.assertEqual(ui.set_scale(1.25)["book_serif_font"], "Reading Face")
        with patch.object(fonts, "serif_fonts", return_value=[]):
            with self.assertRaises(SoloError):
                ui.set_scales(book_serif_font="Not installed")
        self.assertEqual(ui.settings()["book_serif_font"], "Reading Face")
        self.assertEqual(ui.set_scales(book_serif_font="")["book_serif_font"], "")
        self.assertEqual(ui.settings()["book_scale"], 1.25)

    def test_font_cli_reads_and_resets_but_cannot_mix_discovery_and_writes(self):
        with patch.object(fonts, "serif_fonts", return_value=["Reading Face"]):
            code, out, err = self.solo("ui", "--serif-fonts")
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out), ["Reading Face"])
            code, out, err = self.solo("ui", "--book-serif-font=Reading Face")
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["book_serif_font"], "Reading Face")
        self.assertEqual(self.solo("ui", "--book-serif-font=")[0], 0)
        for flags in (("--serif-fonts", "--book-serif-font="), ("--serif-fonts", "--book-scale=2"),
                      ("--scale=2", "--book-serif-font=")):
            self.assertEqual(self.solo("ui", *flags)[0], 1)

    def test_invalid_stored_font_is_ignored_and_invalid_writes_are_rejected(self):
        path = self.tmp / "state/solo/ui.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        for value in (True, [], {}, 4, "bad\nfont", "x" * 257):
            path.write_text(json.dumps({"book_serif_font": value}))
            self.assertEqual(ui.settings()["book_serif_font"], "")
            with self.assertRaises(SoloError):
                ui.set_scales(book_serif_font=value)
