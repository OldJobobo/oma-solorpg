"""A deck of cards as a book: no bookmarks, a card to a page (the front on an even page, a back with a word of art on the odd one before it), and on every face
the words of the frame (on a made-up deck, "LANTERN DECK" and "WORTH"), which sit among the card's own lines wherever the layout put them.

A card is its lines without the frame's: `faces(book)` gives (page, [lines]) for every page that has words of its own.
"""

import hashlib
from collections import Counter

from ..sections import join

_FRAME = 0.4


def faces(book):
    """[(page, [text of each line])] for the pages of a deck that have a card on them: the lines that aren't the frame's (words on much of the pages)."""
    pages = {number: [line["text"].replace("\t", " ").strip() for line in lines if line["text"].strip()] for number, lines in sorted(book.by_page.items())}
    seen = Counter(text for lines in pages.values() for text in set(lines))
    frame = {text for text, count in seen.items() if count >= _FRAME * sum(1 for lines in pages.values() if lines)}
    # A back has a word of art on it ("TAVERN", say) and nothing else; a face has a title and what the card says.
    return [(number, found) for number, found in ((number, [without(text, frame) for text in lines if without(text, frame)]) for number, lines in pages.items())
            if len(found) >= 2]


def without(text, frame):
    """A line without the frame's words in it: the longest first, and of two as long, the first in alphabetical order, so that
    the same card reads the same on every run (a set of words has no order of its own)."""
    for words in sorted(frame, key=lambda words: (-len(words), words)):
        text = text.replace(words, "")
    return " ".join(text.split())


def split(lines):
    """(title, the rest): a card's title is the lines in capitals it begins with ("RUSTY" "LANTERN", made up), joined; a card with none has only the rest."""
    at = 0
    while at < len(lines) and lines[at].isupper():
        at += 1
    return " ".join(lines[:at]), lines[at:]


def sentence(book, lines):
    """The lines of a card as one run of words: a hyphen at a line's end joined or kept as the book's words say, the frame's lines already gone."""
    return " ".join(join([line.strip() for line in lines], book.glue).split())


def title(words):
    """"JAR OF COLD SOUP" as a title: every word but the small ones a capital."""
    small = {"of", "the", "a", "an", "and", "in", "on", "to"}
    return " ".join(word.capitalize() if at == 0 or word.lower() not in small else word.lower() for at, word in enumerate(words.split()))


def fingerprint(book):
    """What tells one deck from another and one printing from the next, as a hash: how many pages it has and the first line of its first card."""
    cards = faces(book)
    return hashlib.sha256(f"{book.manifest.get('pages')}|{cards[0][1][0] if cards else ''}".encode()).hexdigest()[:16]
