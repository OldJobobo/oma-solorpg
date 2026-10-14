"""A table as rows of cells, read from the lines of a page by where each word sits.

A book sets a table as a header of small bold words and cells under them. The PDF hands
them over as lines: sometimes one cell to a line, sometimes two cells fused ("5 silver
Common"), and a cell that wraps is a second line under the first. This cuts each line into
cells where the words have a gap, puts each cell under the header it belongs to, and starts
a new row where the gap to the line above is a row's height, so a line close under another
only carries the rest of a wrapped cell and is added to the row above.
"""

import re

from ..sections import paragraphs
from .read import changed

# Words this close are one cell; a gap wider than this starts the next.
_GAP = 5.0
# Header words are set smaller than this, bold; cells are set at this size or smaller.
_HEADER_SIZE = 8.6
_CELL_SIZE = 9.3
# Lines whose tops are this close are one row of the table.
_LEVEL = 3.0
# A line this far below the last, in lines of its size, starts a new row; nearer is a wrapped cell.
_ROW = 1.4


def read(lines, glue=None, header=None):
    """(header, rows) from a table's lines. `header` is the column names; each row is
    {"cells": [text per column], "parts": [the lines of each cell], "page": n, "y": top}. A row ends where the next line is a
    row's height below it: a line closer than that is a cell that wrapped, and its words are
    added to the cells above. `glue(text, part)` joins a cell that wrapped at a hyphen (Book.glue
    knows which hyphens are the word's own); `header(line)` says which lines are the header's."""
    is_header = header or _is_header
    heads = [line for line in lines if is_header(line)]
    columns = _columns(heads)
    # What stands above the header (a caption, the paragraph that introduces the table) is not a row.
    first = min((line["page"] for line in heads), default=None)
    floor = max((line["y1"] for line in heads if line["page"] == first), default=0)
    body = [line for line in lines if line["size"] <= _CELL_SIZE and not is_header(line) and (line["page"] != first or line["y0"] >= floor - 1)]
    rows, last = [], None
    for level in _levels(body):
        cells = [""] * len(columns)
        for line in level:
            for text, x0, x1 in _cells(line):
                at = _column(columns, x0, x1)
                cells[at] = f"{cells[at]} {text}".strip()
        top = level[0]
        if last is None or (last["page"], top["page"]) != (top["page"],) * 2 or top["y0"] - last["y0"] > _ROW * top["size"]:
            rows.append({"cells": cells, "parts": [[text] if text else [] for text in cells], "page": top["page"], "y": top["y0"]})
        else:
            for at, text in enumerate(cells):
                if text:
                    rows[-1]["cells"][at] = _more(rows[-1]["cells"][at], text, glue or (lambda text, part: text + part))
                    rows[-1]["parts"][at].append(text)
        last = top
    return [c["name"] for c in columns], rows


class Cells(dict):
    """A row's cells by the name of their column, in lower case. A column the table doesn't have is an error that says
    which table of which book (another printing than the recipe was written for), not a KeyError."""

    def __init__(self, section, header, row):
        super().__init__((name.lower(), text) for name, text in zip(header, row["cells"]))
        self.section, self.page = section, row["page"]

    def __missing__(self, name):
        raise changed(self.section, f"the table on p. {self.page} has no {name.upper()} column")

    def number(self, name):
        return number(self.section, self.page, self[name], name)


def cells(section, row, count):
    """A row's cells, for a recipe that reads them in order: an error that says which table of which book when it
    doesn't have the `count` columns the recipe reads."""
    if len(row["cells"]) != count:
        raise changed(section, f"the table on p. {row['page']} has {len(row['cells'])} columns, and the importer reads {count}")
    return row["cells"]


def number(section, page, text, column):
    """The whole number in a cell ("12", "+2", "–3"): a cell that holds anything more ("9*") is an error that says which table of
    which book, not a ValueError."""
    if re.fullmatch(r"[+\-–−]?\d+", text.strip()) is None:
        raise changed(section, f"the table on p. {page} has {text!r} in its {column.upper()} column, where the importer reads a number")
    return int(re.sub(r"[–−]", "-", text.strip()))


def top(section, page, text, column, open_top=None):
    """The top of the range in a cell ("13–16" is 16, "≤12" is 12, "8" is 8), and `open_top` for a range that runs on ("17+") when
    there is one: a cell that holds anything more ("17 or more") is an error that says which table of which book, not a ValueError."""
    found = re.fullmatch(r"≤?\s*(?:\d+\s*[–-]\s*)?(\d+)\s*(\+)?", text.strip())
    if found is None:
        raise changed(section, f"the table on p. {page} has {text!r} in its {column.upper()} column, where the importer reads a range")
    return open_top if found.group(2) and open_top is not None else int(found.group(1))


def _is_header(line):
    return line["size"] < _HEADER_SIZE and line["font"].endswith("-Bold")


def _levels(lines):
    """The lines grouped by where they sit down the page: a row's cells can come as a line each,
    and a cell set a little smaller sits a little lower, so lines within a few points are one."""
    levels = []
    for line in sorted(lines, key=lambda line: (line["page"], line["y0"], line["x0"])):
        if levels and levels[-1][0]["page"] == line["page"] and line["y0"] - levels[-1][0]["y0"] <= _LEVEL:
            levels[-1].append(line)
        else:
            levels.append([line])
    return levels


def _columns(header_lines):
    """The columns the header's words make: pieces that overlap in x (DURA- over BILITY, ARMOR
    over RATING) are one column, named by reading them top to bottom. A table that goes on
    to the next page repeats its header there; only the first is read."""
    first = min((line["page"] for line in header_lines), default=None)
    found = []
    for line in sorted((line for line in header_lines if line["page"] == first), key=lambda line: (line["x0"], line["y0"])):
        for column in found:
            if line["x0"] < column["x1"] and line["x1"] > column["x0"]:
                column["pieces"].append(line)
                column["x0"], column["x1"] = min(column["x0"], line["x0"]), max(column["x1"], line["x1"])
                break
        else:
            found.append({"pieces": [line], "x0": line["x0"], "x1": line["x1"]})
    for column in found:
        column["name"] = paragraphs(sorted(column["pieces"], key=lambda piece: piece["y0"])).replace("\n\n", " ")
        column["centre"] = (column["x0"] + column["x1"]) / 2
    return found


def _cells(line):
    """[(text, x0, x1)]: the line's words, a new cell wherever the gap between two is wide."""
    words = line["text"].split()
    spots = line["words"]
    cells = []
    for word, (x0, x1) in zip(words, spots):
        if cells and x0 - cells[-1][2] <= _GAP:
            cells[-1] = (f"{cells[-1][0]} {word}", cells[-1][1], x1)
        else:
            cells.append((word, x0, x1))
    return [(text.replace("\u00ad", ""), x0, x1) for text, x0, x1 in cells]


def _column(columns, x0, x1):
    """The first column holds what starts at the table's left edge; the last what starts at or
    right of its header; the rest go to the header whose middle is nearest the cell's (cells set
    in the middle of their column, as a small table's are, too)."""
    centre = (x0 + x1) / 2
    if len(columns) == 1 or x0 <= columns[0]["x0"] + 6 and x1 < columns[1]["x0"]:
        return 0
    elif x0 >= columns[-1]["x0"] - 4:
        return len(columns) - 1
    return min(range(len(columns)), key=lambda at: abs(columns[at]["centre"] - centre))


def _more(text, added, glue):
    """A wrapped cell's second line: joined to the first, with no space after a slash."""
    if text.endswith("/"):
        return text + added
    elif text.endswith("-") and added[:1].isalpha():
        return glue(text, added)
    else:
        return f"{text} {added}".strip()
