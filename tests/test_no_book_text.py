"""The repository holds no book: no run of a book's words and no stretch of a table's numbers is in any file of it (the importers hold where things
are and how to read them, never what they say).

The books are only on the machine of someone who owns them, so the test knows them two ways:

- tests/fixtures/book_fingerprints.txt, which the maintainer makes from their own extracts and commits: salted hashes of every run of words and
  every row of numbers of each book, and nothing a book says. Every pull request is checked against it, in CI too. To make it again (a new book,
  another printing), on the machine that has the extracts, then commit the file it writes:

      python3 tests/test_no_book_text.py --fingerprint            # the books extracted in SOLO_SOURCES, or SOLO_HOME/sources
      python3 tests/test_no_book_text.py --fingerprint <folder>   # or in another folder of extracts

- the extracts themselves (SOLO_SOURCES, or SOLO_HOME/sources, where `solo extract` leaves them), when they are on this machine.

With neither, the test is unarmed: it skips, and says so.

A book's text is read the way the audit reads a page (NFKC, so a ligature is its letters; a curly quote and a dash are plain ones). A run is
eight words that read like prose (three or more of the little words every sentence has): labels and table headers are the game's own terms, and
a pattern that has to name a phrase to find it (a regular expression) is kept short of eight words. A row is the numbers of one line of a table
(the words a page sets at one height), with the numbers of the rows above and below it: a stat block, a weapon's line, a price list. It counts
when the three hold six numbers or more and aren't only a table's ranges counting up (1-2, 3-4, 5-6). A file is read a line to a row.
Ironsworn's words are in packs/ironsworn under CC BY (NOTICE.md): a book whose name says Ironsworn isn't looked for there.
"""

import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run as a script, it reads this repository's solo

from solo import library  # noqa: E402
from solo.audit import _norm  # noqa: E402

RUN = 8
FINGERPRINTS = Path(__file__).resolve().parent / "fixtures" / "book_fingerprints.txt"
_WORDS = re.compile(r"[a-z0-9']+")
_LITTLE = frozenset("the a an and or of to in on with you your is are it its if that this each can may must will as by for at from they their which when then any all not".split())
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
# Three rows hold this many numbers or more to count: fewer are as likely anywhere.
_ROW_NUMBERS = 6
# Lines of a page whose tops are this close are one row of a table.
_LEVEL = 3.0
_PICTURES = (".png", ".jpg", ".svg", ".ico", ".woff", ".woff2", ".pdf")


def normalise(text):
    return _norm(text).translate(_QUOTES)


def runs(text):
    """The runs of RUN words in a text that read like prose."""
    words = _WORDS.findall(normalise(text))
    found = (words[at:at + RUN] for at in range(len(words) - RUN + 1))
    return {" ".join(run) for run in found if sum(word in _LITTLE for word in run) >= 3}


def rows(lines):
    """The rows of numbers among some lines: each line's numbers, with those of the lines with numbers above and below it."""
    numbers = [found for found in ([str(int(n)) for n in re.findall(r"\d+", normalise(line))] for line in lines) if found]
    found = set()
    for at in range(len(numbers)):
        three = numbers[max(0, at - 1):at + 2]
        flat = [int(n) for row in three for n in row]
        if len(flat) >= _ROW_NUMBERS and not all(0 <= b - a <= 1 for a, b in zip(flat, flat[1:])):
            found.add(" | ".join(" ".join(row) for row in three))
    return found


def marks(text, lines=None):
    """What a text is compared by: its runs of words and its rows of numbers (of `lines`, else of its own lines)."""
    return {f"w {run}" for run in runs(text)} | {f"n {row}" for row in rows(text.splitlines() if lines is None else lines)}


def _levels(path):
    """A page's rows from the extract's layout: the lines at one height, left to right (a table can run across both columns of a page). None without
    a layout."""
    if not path.exists():
        return None
    levels = []
    for line in sorted(json.loads(path.read_text(encoding="utf-8"))["lines"], key=lambda line: (line["y0"], line["x0"])):
        if levels and line["y0"] - levels[-1][0]["y0"] <= _LEVEL:
            levels[-1].append(line)
        else:
            levels.append([line])
    return [" ".join(line["text"] for line in sorted(level, key=lambda line: line["x0"])) for level in levels]


def book_marks(folder):
    """The runs and rows of a book `solo extract` left in `folder`: its pages' text, its tables' rows read from where their words sit."""
    found = set()
    for page in sorted(Path(folder).glob("pages/*.txt")):
        text = page.read_text(encoding="utf-8")
        found |= marks(text, _levels(Path(folder) / "layout" / f"{page.stem}.json"))
    return found


def extracts(folder):
    """{name: folder} of the books extracted in a folder."""
    return {path.parent.name: path.parent for path in sorted(Path(folder).glob("*/manifest.json")) if any(path.parent.glob("pages/*.txt"))}


def hashed(salt, found):
    return {hashlib.sha256(f"{salt}{mark}".encode()).hexdigest()[:16] for mark in found}


def fingerprint(folder, out=FINGERPRINTS):
    """Write the fingerprints of every book extracted in `folder` to `out`: a salt, and for each book its name and a hash to each run and row."""
    salt = secrets.token_hex(16)
    lines = ["# The books tests/test_no_book_text.py looks for in the repository: salted hashes of their runs of words and rows of numbers,",
             "# never the words or numbers themselves. Made by python3 tests/test_no_book_text.py --fingerprint (see that file).", f"salt {salt}"]
    for name, book in extracts(folder).items():
        lines += [f"book {name}", *sorted(hashed(salt, book_marks(book)))]
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Path(out)


def load(path):
    """(salt, {book: {hash}}) of a fingerprints file."""
    salt, books, book = "", {}, None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("salt "):
            salt = line[5:].strip()
        elif line.startswith("book "):
            book = books.setdefault(line[5:].strip(), set())
        elif line.strip() and not line.startswith("#") and book is not None:
            book.add(line.strip())
    return salt, books


def leaks(salt, books, files, root):
    """What each file holds of a book: a line for each file, with how many runs and rows of which book and one of them."""
    found = []
    for path in files:
        if path.suffix in _PICTURES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        name = Path(path).relative_to(root).as_posix()
        mine = {hashlib.sha256(f"{salt}{mark}".encode()).hexdigest()[:16]: mark for mark in marks(text)}
        for book, hashes in books.items():
            if name.startswith("packs/ironsworn/") and "ironsworn" in book.lower():
                continue
            same = sorted(mark for digest, mark in mine.items() if digest in hashes)
            if same:
                found.append(f"{name}: {len(same)} runs and rows of {book}, e.g. {same[0][2:]!r}")
    return found


def tracked():
    """Every file of the repository, committed or not (a new one is where a leak would be)."""
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=library.REPO, capture_output=True, text=True, check=True).stdout
    return [library.REPO / name for name in out.splitlines() if name and (library.REPO / name).is_file()]


def sources():
    return Path(os.environ.get("SOLO_SOURCES") or library.home() / "sources")


class NoBookTextTest(unittest.TestCase):
    def test_no_file_of_the_repository_has_a_run_of_words_or_a_row_of_numbers_from_a_book(self):
        salt, books = load(FINGERPRINTS) if FINGERPRINTS.exists() else (secrets.token_hex(16), {})
        for name, book in (extracts(sources()) if sources().is_dir() else {}).items():
            books.setdefault(name, set()).update(hashed(salt, book_marks(book)))
        if not books:
            self.skipTest("unarmed: there is no tests/fixtures/book_fingerprints.txt and no extracted book on this machine to look for; "
                          "the maintainer arms it with python3 tests/test_no_book_text.py --fingerprint (see its docstring)")
        found = leaks(salt, books, [path for path in tracked() if path != FINGERPRINTS], library.REPO)
        self.assertEqual(found, [], "words or numbers of a book in the repository:\n" + "\n".join(found))


class FingerprintTest(unittest.TestCase):
    """The fingerprints, on a made-up book: what they find, and that they hold nothing of it."""

    def setUp(self):
        from fake_book import CELL, HEADER, FakeBook
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        made = FakeBook(self.tmp / "sources" / "lantern-rules")
        made.line(1, 80, "The ﬁre of the lantern burns in the hall, and the heroes don’t leave it until the night is over.")
        for at, name in enumerate(("WEAPON", "GRIP", "STR", "DAMAGE", "COST")):
            made.line(1, 120, name, 68 + 70 * at, HEADER)
        for row, cells in enumerate([["Hook", "1H", "7", "2D4", "13 gold"], ["Pole", "2H", "11", "D10", "4 silver"], ["Whip", "1H", "8", "D6", "17 gold"]]):
            for at, cell in enumerate(cells):
                made.line(1, 140 + 17 * row, cell, 68 + 70 * at, CELL)
        made.save(pages=True)
        made = FakeBook(self.tmp / "sources" / "ironsworn-rulebook")
        made.line(0, 80, "When you swear upon iron to see a quest through to its end, roll with the heart you have left.")
        made.save(pages=True)
        self.prints = fingerprint(self.tmp / "sources", self.tmp / "prints.txt")

    def leaks(self, files):
        root = self.tmp / "repo"
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8")
        return leaks(*load(self.prints), [root / name for name in files], root)

    def test_the_fingerprints_hold_nothing_a_book_says(self):
        held = "\n".join(line for line in self.prints.read_text(encoding="utf-8").lower().splitlines() if not line.startswith(("#", "salt ", "book ")))
        for said in ("lantern", "hall", "heroes", "hook", "gold", "silver", "iron"):
            self.assertNotIn(said, held)
        self.assertEqual(sorted(load(self.prints)[1]), ["ironsworn-rulebook", "lantern-rules"])

    def test_a_sentence_and_a_table_copied_are_found_whatever_their_quotes_and_ligatures(self):
        found = self.leaks({
            "docs/notes.md": "As the book says: the fire of the lantern burns in the hall, and the heroes don't leave it.\n",
            "tests/fixtures/arms.md": "| Hook | 1H | 7 | 2D4 | 13 gold |\n| Pole | 2H | 11 | D10 | 4 silver |\n| Whip | 1H | 8 | D6 | 17 gold |\n",
            "packs/house/rules.md": "A lantern burns in the hall until the heroes put it out, for a stretch. Roll 1-2, 3-4, 5-6.\n",
        })
        self.assertEqual([line.partition(":")[0] for line in found], ["docs/notes.md", "tests/fixtures/arms.md"], found)
        self.assertIn("runs and rows of lantern-rules, e.g. ", found[1])

    def test_ironsworns_words_are_looked_for_everywhere_but_in_its_own_pack(self):
        sentence = "When you swear upon iron to see a quest through to its end, roll with the heart you have left.\n"
        found = self.leaks({"packs/ironsworn/moves/swear.md": sentence, "packs/dragonbane/rules/swear.md": sentence})
        self.assertEqual([line.partition(":")[0] for line in found], ["packs/dragonbane/rules/swear.md"])


if __name__ == "__main__":
    if sys.argv[1:2] == ["--fingerprint"]:
        folder = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else sources()
        if not extracts(folder):
            sys.exit(f"no book extracted in {folder}: run solo extract on your PDFs first, or name the folder that holds the extracts")
        print(f"wrote {fingerprint(folder)}: {', '.join(extracts(folder))}")
    else:
        unittest.main()
