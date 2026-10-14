"""What every recipe reads the same way: a value found in a section's text by a pattern made of the game's own terms
(a dice expression, a count, a unit). A section that doesn't say it any more fails by name: that is a printing the
recipe wasn't written for.
"""

import re

from .. import SoloError

_COUNTS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "twenty": 20}


def find(section, pattern, what, flags=re.I | re.S, own=False):
    """The match of `pattern` in a section's text, or an error saying which part of which book is not as the recipe expects."""
    found = re.search(pattern, section.text(own=own), flags)
    if found is None:
        raise changed(section, f"can't find {what}")
    return found


def changed(section, what):
    """The error for a section that isn't as the recipe expects: which part of which book, and what is wrong with it."""
    return SoloError(f"{section.book.manifest.get('source', 'the book')}, {section.title!r} (p. {section.page}): {what}; "
                     "this may be another printing than the importer was written for")


def says(section, pattern):
    return re.search(pattern, section.text(), re.I | re.S) is not None


def count(word, section=None):
    """A count as a book writes it ("6", "six"), found in `section`: one the importer doesn't know is an error that says which part of which
    book, as `changed` does."""
    if word.isdigit() or word.lower() in _COUNTS:
        return int(word) if word.isdigit() else _COUNTS[word.lower()]
    what = f"the importer reads {word!r} where it expects a number, and doesn't know it as one (it knows the digits and {', '.join(_COUNTS)})"
    if section is not None:
        raise changed(section, what)
    raise SoloError(f"{what}; this may be another printing than the importer was written for")


def roll(text):
    """Dice as the engine writes them: "D6" is 1d6, "2D6" 2d6."""
    return re.sub(r"^D", "1d", text.strip(), flags=re.I).lower()
