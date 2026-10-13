"""A made-up book on disk, in the shape `solo extract` leaves it: layout/*.json, outline.json and
manifest.json. The importers (solo/sections.py, solo/books/) read these files, never the PDF, so
their tests build a book from lines of invented text, with the typefaces the real books use."""

import json
from pathlib import Path

# (font, size, color): the body text, a heading, light type on a dark box (a sidebar), a label
# set small and bold, a table's header, and a table's cells.
BODY = ("MinionPro-Regular", 10.0, 2301728)
HEADING = ("Hideout-Bold", 11.5, 2301728)
BOX = ("Hideout-SemiBold", 9.0, 14345954)
LABEL = ("Hideout-Bold", 9.0, 24653)
HEADER = ("Hideout-Bold", 7.6, 4926747)
CELL = ("Hideout-Regular", 9.0, 4926747)
BANNER = ("Hideout-Bold", 10.0, 14345954)


class FakeBook:
    def __init__(self, folder, source="Test Book.pdf"):
        self.folder, self.source = Path(folder), source
        self.pages, self.outline, self.last = {}, [], None

    def line(self, page, y, text, x=62, style=BODY, words=None):
        """One line of text at (x, y): in reading order, so a page's lines are added top to bottom,
        the left column before the right."""
        font, size, color = style
        if words is None:
            words, at = [], x
            for word in text.split():
                words.append([at, at + 5 * len(word)])
                at += 5 * (len(word) + 1)
        found = {"x0": x, "y0": y, "x1": x + 5 * len(text), "y1": y + 12, "text": text, "size": size, "font": font,
                 "color": color, "col": 1 if x >= 306 else 0, "words": words}
        self.pages.setdefault(page, []).append(found)
        self.last = (page, x, y)
        return found

    def lines(self, page, y, *texts, x=62, style=BODY, step=12):
        for number, text in enumerate(texts):
            self.line(page, y + step * number, text, x, style)

    def mark(self, level, title):
        """A bookmark that points at the line added last."""
        page, x, y = self.last
        self.outline.append({"level": level, "title": title, "page": page, "x": x, "y": y - 1})

    def table(self, page, y, names, rows, xs):
        """A table's header and rows, one cell to a line, each cell at its column's x."""
        for name, x in zip(names, xs):
            self.line(page, y, name, x, HEADER)
        for number, cells in enumerate(rows):
            for cell, x in zip(cells, xs):
                self.line(page, y + 16 + 17 * number, cell, x, CELL)

    def section(self, page, y, level, title, *text, x=62):
        """A heading with its bookmark and the body text under it: the y where the next thing goes."""
        self.line(page, y, title.upper(), x, HEADING)
        self.mark(level, title)
        self.lines(page, y + 20, *text, x=x)
        return y + 32 + 12 * len(text)

    def banner(self, page, y, level, title):
        """A table's title, light type on a dark banner, with the bookmark that points at it."""
        self.line(page, y, title.upper(), 250, BANNER)
        self.mark(level, title)

    def roll_table(self, page, y, headers, rows, xs):
        """A roll table: its header, with the die first, and a row for each (roll, cells...), each cell at its column."""
        for name, x in zip(headers, xs):
            self.line(page, y, name, x - 5, HEADER)
        for number, cells in enumerate(rows):
            for cell, x in zip(cells, xs):
                self.line(page, y + 17 + 17 * number, cell, x, CELL)

    def save(self, extras=None, pages=False):
        """Write the book. A page 0 of body text comes first, before any bookmark, so that the body
        typeface is the one most of the book is set in, as it is in a real one. With `pages`, each
        page's text too (pages/0003.txt, a line to each line), which is what the audit reads."""
        (self.folder / "layout").mkdir(parents=True, exist_ok=True)
        if 0 not in self.pages:
            self.line(0, 80, "The front matter of a made-up book, which says nothing and goes on at length so the body type wins. " * 4)
        for number, lines in self.pages.items():
            page = {"page": number, "width": 612.0, "height": 792.0, "lines": lines}
            (self.folder / "layout" / f"{number:04d}.json").write_text(json.dumps(page), encoding="utf-8")
            if pages:
                (self.folder / "pages").mkdir(exist_ok=True)
                (self.folder / "pages" / f"{number:04d}.txt").write_text("".join(f"{line['text']}\n" for line in lines), encoding="utf-8")
        (self.folder / "outline.json").write_text(json.dumps(self.outline), encoding="utf-8")
        manifest = {"source": self.source, "pages": max(self.pages, default=0), "layout": True, **(extras or {})}
        (self.folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return self.folder


class Flow:
    """Sections one after another down the pages of a made-up book."""

    def __init__(self, made):
        self.made, self.page, self.y = made, 1, 80

    def section(self, level, title, *text):
        if self.y + 32 + 12 * len(text) > 760:
            self.page, self.y = self.page + 1, 80
        self.y = self.made.section(self.page, self.y, level, title, *text)

    def table(self, names, rows, xs):
        """A table with a header and rows under the last section, on a page of its own."""
        self.page, self.y = self.page + 1, 100 + 17 * (len(rows) + 1) + 40
        self.made.table(self.page, 100, names, rows, xs)
