"""A roll table, read from where its rows sit: "D6 FIRST NAME" over numbers and what they give.

A book sets a roll table in whatever shape the page allows: a header with the die and what it gives, the
rows under it; the same table in two halves side by side, or a long one continued in the next column;
a number with its text in the same line ("1-2 Warhammer ...") or in a cell of its own; a column of
results that wrap. And a table of several dice, one column each, read together as a sentence
(the quest: "One day, <D4>, the characters come across <D6> ...").

A row is found by its number: the next one of the die, at the start of a line, in a column of numbers;
its words are the text in that column from there to the next number, with what wraps under it.
"""

import re

from .. import SoloError

_DIE = re.compile(r"^D(\d+|%)(?!\w)\s*(.*)$", re.I)
_NUMBER = re.compile(r"^(\d+)(?:(\+)|\s*[–-]\s*(\d+))?(?:\s+(.*))?$")
_CELL_SIZE = 9.3
# Numbers whose left edges are this close are one column of numbers.
_COLUMN = 8
# A cell this many points above a row's number still belongs to that row.
_SLACK = 3
# A line this many lines of its size below the last one is no longer the same cell.
_WRAP = 1.5
# Words this close are one cell.
_GAP = 5.0


def faces(label):
    """The highest roll of a die in a header: "D6" is 6, "D66" is 66 (two dice), "D%" is 100."""
    found = _DIE.match(label.strip())
    return 100 if found.group(1) == "%" else int(found.group(1))


def formula(sides):
    return "d66" if sides == 66 else f"1d{sides}"


def is_die(label):
    """Whether a header's words are a die ("D6", "D20 FIRST NAME")."""
    return _DIE.match(label.strip()) is not None


def is_marker(line):
    return line["size"] < 8.6 and line["font"].endswith("-Bold") and is_die(line["text"])


def read(lines, glue, sides=None):
    """One table from its lines: {faces, headers, rows: [{low, high, text, cells, page}]}, however many columns of numbers
    it is set in and whether the numbers stand in cells of their own. `sides` is the die when the lines have no
    header with it (the table goes on from another page)."""
    heads = [line for line in lines if is_marker(line)]
    if not heads and sides is None:
        raise SoloError("no roll table here: a header with the die (D6, D20 ...) was not found")
    given, sides = sides, sides or faces(heads[0]["text"])
    small = [line for line in lines if line["size"] < 8.6 and line["font"].endswith("-Bold")]
    body = [line for line in lines if line["size"] <= _CELL_SIZE and line not in small]
    rows = _rows(body, sides, glue)
    top = rows[-1]["high"] if rows else 0
    if given is None and top < sides:
        # The rows are read in order up to the first number missing: a table that stops short of its die has lost a row.
        raise SoloError(f"the table under {heads[0]['text'].strip()!r} on p. {heads[0]['page']} has rows for 1-{top} and none for {top + 1}, "
                        "short of its die; this may be another printing than the importer was written for")
    return {"faces": sides, "headers": [line["text"].strip() for line in sorted(small, key=lambda l: (l["page"], l["x0"]))], "rows": rows}


def _rows(pool, sides, glue):
    runs = []
    for column in _columns(_starts(pool, sides)):
        run = []
        for start in column:
            if run and start["range"][0] == run[-1]["range"][1] + 1:
                run.append(start)
            else:
                if run:
                    runs.append((run, column))
                run = [start]
        runs.append((run, column))
    chosen, expected = [], 1
    while expected <= sides:
        found = max((entry for entry in runs if entry[0][0]["range"][0] == expected and entry not in chosen), key=lambda entry: len(entry[0]), default=None)
        if found is None:
            break
        chosen.append(found)
        expected = found[0][-1]["range"][1] + 1
    edges = sorted({start["line"]["x0"] for _, column in chosen for start in column[:1]})
    rows = []
    for run, column in chosen:
        right = next((edge for edge in edges if edge > column[0]["line"]["x0"] + _COLUMN), float("inf")) - _COLUMN
        for start in run:
            after = next((other for other in column if other["line"]["page"] == start["line"]["page"] and other["line"]["y0"] > start["line"]["y0"] + _SLACK), None)
            bottom = after["line"]["y0"] - _SLACK if after else float("inf")
            under = [line for line in pool if line["page"] == start["line"]["page"] and start["line"]["y0"] - _SLACK <= line["y0"] < bottom
                     and column[0]["line"]["x0"] - _COLUMN <= line["x0"] < right and line is not start["line"]]
            cells = _cells(start, _wrapped(start["line"], under), glue)
            rows.append({"low": start["range"][0], "high": start["range"][1], "text": " ".join(" ".join(cells).split()), "cells": cells,
                         "page": start["line"]["page"]})
    return sorted(rows, key=lambda row: row["low"])


def _wrapped(first, lines):
    """The lines that belong to a row: from its number down, as long as each is a wrapped line below the last and not a gap
    away (the last row of a table has no number after it to end it, and what is set under the table isn't its own)."""
    kept, at, size = [], first["y0"], first["size"]
    for line in sorted(lines, key=lambda line: line["y0"]):
        if line["y0"] - at > _WRAP * max(line["size"], size):
            break
        kept.append(line)
        at, size = line["y0"], line["size"]
    return kept


def _starts(cells, sides):
    """The lines that begin with a number or a range ("5", "2-6", "18+": up to the die's highest): {range, rest (the text after it on the line), line}."""
    found = []
    for line in cells:
        match = _NUMBER.match(line["text"].strip().replace("\u00ad", ""))
        if match:
            # "00" on a D% is a hundred.
            low, high = (100 if number == "00" else int(number) for number in (match.group(1), match.group(3) or match.group(1)))
            found.append({"range": (low, sides if match.group(2) else high), "rest": (match.group(4) or "").strip(), "line": line})
    return found


def _columns(starts):
    """The numbers grouped into the columns they stand in (by left edge), each read down the page."""
    columns = []
    for start in sorted(starts, key=lambda s: (s["line"]["x0"], s["line"]["page"], s["line"]["y0"])):
        for column in columns:
            if abs(column[0]["line"]["x0"] - start["line"]["x0"]) <= _COLUMN:
                column.append(start)
                break
        else:
            columns.append([start])
    return [sorted(column, key=lambda s: (s["line"]["page"], s["line"]["y0"])) for column in columns]


def _cells(start, others, glue):
    """What a row holds, a cell to each column of words it stands in: the words of the number's line after the number, and
    the lines under or beside it, each column read down and joined (a name that wraps, "Teeth knocked" and "out")."""
    pieces = [(line["x0"], line["y0"], line["text"].strip()) for line in others]
    if start["rest"]:
        line = start["line"]
        skip = len(line["text"].split()) - len(start["rest"].split())
        pieces.append((line["words"][skip][0] if skip < len(line["words"]) else line["x0"], line["y0"], start["rest"]))
    columns = []
    for x, y, text in sorted(pieces):
        for column in columns:
            if abs(column[0][0] - x) <= _COLUMN:
                column.append((x, y, text))
                break
        else:
            columns.append([(x, y, text)])
    cells = []
    for column in sorted(columns, key=lambda column: min(piece[0] for piece in column)):
        text = ""
        for _, _, part in sorted(column, key=lambda piece: piece[1]):
            text = (glue(text, part) if text.endswith("-") and part[:1].isalpha() else f"{text} {part}") if text else part
        cells.append(" ".join(text.replace("\u00ad", "").split()))
    return cells


def columns(lines, glue):
    """[{faces, rows}] for a table of several dice, one column each, which the book reads together as a sentence: dice
    labels across the top ("D4", "D6" ...) and the row numbers in a column of their own to the left. A column of a
    smaller die has "—" in the rows it doesn't use. Cells the PDF set in one line ("a flooded chamber 2D8 goblins")
    are cut apart where the words have a gap."""
    marks = sorted((line for line in lines if is_marker(line) and not _DIE.match(line["text"].strip()).group(2)), key=lambda line: line["x0"])
    heads = [line for line in lines if line["size"] < 8.6 and line["font"].endswith("-Bold")]
    top = min(line["y0"] for line in marks)
    body = [cell for line in lines if line["size"] <= _CELL_SIZE and line not in heads and line["y0"] > top for cell in _split(line)]
    left = marks[0]["x0"] - _COLUMN
    numbers = sorted((cell for cell in body if cell["x0"] < left and re.fullmatch(r"\d+", cell["text"])), key=lambda cell: (cell["page"], cell["y0"]))
    body = [cell for cell in body if cell["x0"] >= left]
    edges = _edges(marks, numbers, body)
    found = []
    for mark, low, high in zip(marks, edges, edges[1:]):
        sides = faces(mark["text"])
        rows = []
        for number, after in zip(numbers, [*numbers[1:], None]):
            roll = int(number["text"])
            if roll > sides:
                break
            bottom = after["y0"] - _SLACK if after and after["page"] == number["page"] else float("inf")
            mine = [cell for cell in body if cell["page"] == number["page"] and number["y0"] - _SLACK <= cell["y0"] < bottom and low <= cell["x0"] < high]
            parts = [cell["text"] for cell in sorted(mine, key=lambda cell: (round(cell["y0"] / _SLACK), cell["x0"]))]
            text = parts[0] if parts else ""
            for part in parts[1:]:
                text = glue(text, part) if text.endswith("-") and part[:1].isalpha() else f"{text} {part}"
            rows.append({"low": roll, "high": roll, "text": " ".join(text.split()), "page": number["page"]})
        found.append({"faces": sides, "rows": rows})
    return found


def _split(line):
    """A line as cells: its words, a new cell wherever the gap between two is wide."""
    cells = []
    for word, (x0, x1) in zip(line["text"].split(), line["words"]):
        if cells and x0 - cells[-1]["x1"] <= _GAP:
            cells[-1].update(text=f"{cells[-1]['text']} {word}", x1=x1)
        else:
            cells.append({"text": word, "x0": x0, "x1": x1, "y0": line["y0"], "page": line["page"]})
    return [{**cell, "text": cell["text"].replace("\u00ad", "")} for cell in cells]


def _edges(marks, numbers, body):
    """Where each column of a many-dice table starts. The cells' own left edges say it: the first cell of each row, in the
    columns the page sets, one edge to a column; the dice labels are centred over theirs and don't."""
    first = [cell["x0"] for number in numbers for cell in body if cell["page"] == number["page"] and abs(cell["y0"] - number["y0"]) <= _SLACK]
    edges = []
    for x in sorted(first):
        if not edges or x - edges[-1][-1] > _COLUMN:
            edges.append([x])
        else:
            edges[-1].append(x)
    lefts = [min(group) - _COLUMN / 2 for group in edges]
    return lefts + [float("inf")] if len(lefts) == len(marks) else [mark["x0"] - _COLUMN for mark in marks] + [float("inf")]
