"""Installed Latin reading faces, classified by OpenType metadata, not names."""

import struct
import subprocess

from . import SoloError

# These reading families ship without usable OS/2 classification. The NV
# entries are verified serif faces from nicoverbruggen/ebook-fonts; its sans
# and accessibility faces are deliberately excluded. Exact names only, never
# a prefix or substring guess for arbitrary fonts.
UNCLASSIFIED_READING_FAMILIES = frozenset({
    "Literata", "Newsreader", "Bitter", "Libron", "Readerly", "Cartisse",
    "NV Adelph", "NV Alegreya", "NV Aleo", "NV Alizar", "NV Appleton",
    "NV Basker", "NV Bitter", "NV Castoro", "NV Charis", "NV Charis Literacy",
    "NV Clara", "NV Elstob", "NV Garamond", "NV Garamontio", "NV Gentium",
    "NV Georsio", "NV Halcyon", "NV Ibarra", "NV Junius", "NV Kierkegaard",
    "NV Literata", "NV Newsreader", "NV NinePoint", "NV Radley", "NV Sable",
    "NV Technical", "NV Wittgenstein", "NV Zilla Slab",
})


def _serif(path, index=0):
    """Read OS/2 family class and PANOSE from an sfnt face (including TTC)."""
    try:
        with open(path, "rb") as font:
            signature = font.read(4)
            if signature == b"ttcf":
                font.seek(8)
                count = struct.unpack(">I", font.read(4))[0]
                if not 0 <= index < min(count, 4096):
                    return False
                font.seek(12 + index * 4)
                offset = struct.unpack(">I", font.read(4))[0]
            else:
                offset = 0
            font.seek(offset)
            signature, count = struct.unpack(">4sH", font.read(6))
            if signature not in (b"\x00\x01\x00\x00", b"OTTO", b"true") or count > 4096:
                return False
            font.seek(offset + 12)
            records = font.read(count * 16)
            for tag, _, start, size in struct.iter_unpack(">4sIII", records):
                if tag != b"OS/2" or size < 42:
                    continue
                font.seek(start + 30)
                data = font.read(12)
                family_class = data[0]
                kind, serif, _, proportion = data[2:6]
                # PANOSE proportion 9 is monospaced. Classes 1–7 are serif;
                # Latin Text serif styles 2–10 include slab and humanist faces.
                if proportion == 9:
                    return False
                if 1 <= family_class <= 7 or (kind == 2 and 2 <= serif <= 10):
                    return True
                if family_class == 0 and kind in (0, 2) and serif in (0, 1):
                    return None  # The font does not declare a useful classification.
                return False
    except (OSError, ValueError, IndexError, struct.error):
        pass
    return False


def serif_fonts():
    """Fontconfig supplies installed families with English coverage; no Qt needed."""
    try:
        result = subprocess.run(
            ["fc-list", ":lang=en", "-f", "%{file}\t%{index}\t%{family[0]}\t%{spacing}\n"],
            capture_output=True, text=True, timeout=15, check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SoloError("Couldn't list installed serif fonts. Check that fontconfig is installed, then reopen Settings.") from exc
    families = set()
    checked = set()
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        path, index, family, spacing = parts
        if not family or family in checked or (spacing and spacing != "0"):
            continue
        try:
            # Fontconfig encodes a variable-font instance in the high bits.
            face = int(index) & 0xFFFF
        except ValueError:
            continue
        classification = _serif(path, face)
        if classification is True or (classification is None and family in UNCLASSIFIED_READING_FAMILIES):
            families.add(family)
        checked.add(family)
    return sorted(families, key=str.casefold)
