"""`solo extract`: a book's PDF as text an agent can read a chapter at a time.

A rulebook PDF is tens of megabytes, almost all of it art. Its text is a megabyte or two,
and page by page it can be cited. This writes, into a folder outside the repository:

  manifest.json      the source file, page count, printed page labels, what needs OCR
  toc.json           chapters and sections with their page ranges and size in characters
  book.md            every page, with ===== PAGE n ===== markers, for grep
  pages/0042.txt     one page
  chapters/03-combat.md   one top-level chapter's pages, with the same markers
  tables/            tables found on a page: p0042-1.md as Markdown, p0042.png as a picture
  layout/0042.json   the page's lines with their place and style, and outline.json the bookmarks
                     with where each points (solo/layout.py): what the importers in solo/books/ read

Page numbers are the PDF's (1 is the first page of the file); the printed number is kept
in manifest.json when it differs, and in the page markers. The inventory cites PDF pages.

This is the only part of solo that needs a library outside the standard one (PyMuPDF), and
only here: play never reads a PDF.
"""

import hashlib
import json
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import SoloError, layout, library, packs

GENERATED = ("pages", "chapters", "tables", "layout")
# A page with less text than this and a picture on it is a scan: its text needs OCR.
SCANNED_BELOW = 30
# A roll table in an RPG is lines that start with a die result: "1", "2-5", "11–16".
_ROLL_LINE = re.compile(r"^\s*\d{1,3}(\s*[-–]\s*\d{1,3})?[.:)]?\s+\S")
ROLL_LINES = 4


def default_out(pdf):
    return library.home() / "sources" / packs.slug(Path(pdf).stem).replace("_", "-")


def extract(pdf, out=None, *, tables=True):
    """Write the folder described above and return its manifest."""
    pymupdf = _pymupdf()
    pdf = Path(pdf).expanduser().resolve()
    if not pdf.is_file():
        raise SoloError(f"no such file: {pdf}")
    out = Path(out).expanduser().resolve() if out else default_out(pdf)
    if out == library.REPO or library.REPO in out.parents:
        raise SoloError(f"{out} is inside the repository: a book's text stays out of it (the default is {default_out(pdf)})")
    try:
        doc = pymupdf.open(pdf)
    except Exception as error:  # PyMuPDF raises its own types for damaged files
        raise SoloError(f"can't open {pdf}: {error}") from None
    if doc.needs_pass:
        raise SoloError(f"{pdf.name} is password protected")

    out.mkdir(parents=True, exist_ok=True)
    for name in GENERATED:  # a re-run starts these over; anything else in the folder stays
        shutil.rmtree(out / name, ignore_errors=True)
        (out / name).mkdir()

    width = max(4, len(str(doc.page_count)))
    raw = {index + 1: page_text(page) for index, page in enumerate(doc)}
    texts, running, printed = strip_running(raw)
    labelled = {index + 1: _label(page) for index, page in enumerate(doc)}
    if not any(label and label != str(n) for n, label in labelled.items()):
        # No page labels in the PDF: the printed numbers read off the footers, when they agree.
        labelled = {n: str(printed[n]) for n in printed}
    pages, found = [], []
    for index, page in enumerate(doc):
        number = index + 1
        text = texts[number]
        label = labelled.get(number)
        entry = {"page": number, "chars": len(text)}
        if label and label != str(number):
            entry["label"] = label
        if len(text.strip()) < SCANNED_BELOW and page.get_images():
            entry["scanned"] = True
        pages.append(entry)
        (out / "pages" / f"{number:0{width}d}.txt").write_text(text, encoding="utf-8")
        _write_json(out / "layout" / f"{number:0{width}d}.json", layout.page_layout(page, number, set(running), running_form))
        if tables:
            found += _tables(page, number, text, out / "tables", width)

    markers = {p["page"]: _marker(p) for p in pages}
    (out / "book.md").write_text("".join(markers[n] + texts[n] for n in texts), encoding="utf-8")

    toc, toc_from = _toc(doc, pages)
    chapters = _chapters(toc, texts, markers, out / "chapters")
    (out / "toc.json").write_text(json.dumps(toc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_json(out / "outline.json", layout.outline(doc))
    if tables:
        (out / "tables" / "index.json").write_text(json.dumps(found, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "source": pdf.name,
        "sha256": _sha256(pdf),
        "extracted": datetime.now().isoformat(timespec="seconds"),
        "pages": doc.page_count,
        "chars": sum(p["chars"] for p in pages),
        "toc_from": toc_from,
        "chapters": chapters,
        "tables": len(found) if tables else None,
        "layout": True,
        "scanned": [p["page"] for p in pages if p.get("scanned")],
        "labels": {str(p["page"]): p["label"] for p in pages if "label" in p},
        # Where the printed numbers came from: the PDF's page labels, the footers, or nowhere.
        "labels_from": "pdf" if any(_label(page) not in ("", str(i + 1)) for i, page in enumerate(doc)) else "footers" if printed else "none",
        # Headers and footers repeated across pages, taken out of the text (digits as #).
        "running": running,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out, manifest


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def _pymupdf():
    try:
        import pymupdf
    except ImportError:
        raise SoloError("solo extract needs PyMuPDF: on Omarchy, sudo pacman -S python-pymupdf; on another system, see "
                        "Troubleshooting in the README (only extract uses it; play doesn't)") from None
    if hasattr(pymupdf, "no_recommend_layout"):  # it prints an advert for another package otherwise
        pymupdf.no_recommend_layout()
    return pymupdf


def _label(page):
    """The printed page number, from the PDF's page labels, if it has any for this page."""
    try:
        return page.get_label()
    except (IndexError, ValueError):  # labels that start after this page
        return ""


def _marker(page):
    printed = f" (printed {page['label']})" if "label" in page else ""
    return f"\n===== PAGE {page['page']}{printed} =====\n\n"


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Reading order --------------------------------------------------------------------------
#
# The PDF's own order of text blocks is whatever the layout program wrote, and a
# two-column page read top to bottom interleaves the columns line by line. A block that
# spans the page (a heading, a table, a full-width box) splits it into bands; inside a
# band the left column is read before the right.

def page_text(page):
    blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
    return "\n".join(_clean(block[4]) for block, _ in layout.reading_order(blocks, page.rect)) + "\n" if blocks else ""


def _clean(text):
    # Words split across a line end by a hyphen come back whole; other line breaks stay.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    return text.strip() + "\n"


# Running heads -------------------------------------------------------------------------
#
# A book repeats its title, the chapter's name and the page number at the top or bottom of
# every page. In the text they sit between the paragraphs of every chapter and break
# sentences apart. A line near the top or bottom that comes back on several pages (digits
# counted as one) is taken out; the number in it, where there is one, is the printed page.
# Only if it is at the edge nearly everywhere it appears, though: on a two-column page a
# spell's "Rank: 1" or a table's "D6" can come out first, and those are the book's text. And
# a line with a number in it is a heading only if the same line comes back, or the number is
# the page's: the cards of a deck that differ in the dice they show ("2D6 silver coins",
# "3D6 silver coins") are one card each, not a heading.

_EDGE = 2
_AT_EDGE = 0.9
_CARD_LINES = 8
_NUMBER = re.compile(r"^\D*?(\d{1,4})\D*$")


def running_form(line):
    return re.sub(r"\d+", "#", " ".join(line.lower().split()))


def strip_running(texts):
    """({page: text without running heads}, [the forms taken out], {page: printed number})."""
    form = running_form
    edges, anywhere = {}, Counter()
    for number, text in texts.items():
        lines = [line for line in text.splitlines() if line.strip()]
        edges[number] = lines[:_EDGE] + lines[-_EDGE:] if len(lines) > 2 * _EDGE else lines
        anywhere.update({form(line) for line in lines})
    seen = Counter(f for lines in edges.values() for f in {form(line) for line in lines})
    with_text = sum(1 for text in texts.values() if text.strip())
    often = max(3, with_text // 20)
    # A deck of cards has a few lines to a page, so every line is at an edge: only what is on half the pages is the frame's.
    lengths = sorted(len([line for line in text.splitlines() if line.strip()]) for text in texts.values() if text.strip())
    if lengths and lengths[len(lengths) // 2] <= _CARD_LINES:
        often = max(often, with_text // 2)
    running = {f for f, count in seen.items()
               if count >= often and count >= _AT_EDGE * anywhere[f] and len(f) <= 80 and _heading(f, edges, often)}
    cleaned, printed = {}, {}
    for number, text in texts.items():
        lines = text.splitlines()
        content = [i for i, line in enumerate(lines) if line.strip()]
        edge = set(content[:_EDGE] + content[-_EDGE:])
        keep = []
        for i, line in enumerate(lines):
            if i in edge and form(line) in running:
                found = _NUMBER.match(line.strip())
                if found:
                    printed.setdefault(number, int(found.group(1)))
            else:
                keep.append(line)
        cleaned[number] = "\n".join(keep).strip() + "\n" if any(line.strip() for line in keep) else ""
    return cleaned, sorted(running), _agreed(printed, max(texts, default=0))


def _heading(f, edges, often):
    """Whether the lines of this form are a heading: no number in them, or one line that comes back as it is on enough pages, or a number that is
    the page's (the same distance from the PDF's page number on most pages that have it)."""
    if "#" not in f:
        return True
    pages = {number: [line for line in lines if running_form(line) == f] for number, lines in edges.items()}
    exact = Counter(" ".join(line.lower().split()) for lines in pages.values() for line in set(lines))
    if exact and max(exact.values()) >= often:
        return True
    offsets = Counter(number - int(digits) for number, lines in pages.items() for line in lines[:1] for digits in re.findall(r"\d+", line))
    return bool(offsets) and offsets.most_common(1)[0][1] >= 0.6 * sum(1 for lines in pages.values() if lines)


def _agreed(numbers, total):
    """The printed page numbers, when most of them sit at the same distance from the PDF's
    (a cover and a contents page before page 1). Each page then gets its number."""
    offsets = Counter(page - number for page, number in numbers.items())
    if not offsets:
        return {}
    offset, count = offsets.most_common(1)[0]
    if count < 3 or count < len(numbers) / 2:
        return {}
    return {page: page - offset for page in range(1, total + 1) if page - offset >= 1}


# Tables ----------------------------------------------------------------------------------

def _tables(page, number, text, folder, width):
    """Ruled tables PyMuPDF finds, as Markdown, and any page that looks like a roll table,
    as a picture: text extraction scrambles columns, and the agent can look at the page."""
    found = []
    stem = f"p{number:0{width}d}"
    try:
        grids = page.find_tables().tables
    except Exception:  # table detection is best effort; the page's text is already out
        grids = []
    for k, grid in enumerate(grids, 1):
        markdown = grid.to_markdown().strip()
        if markdown.count("\n") < 2:  # a header and nothing under it: a box, not a table
            continue
        name = f"{stem}-{k}.md"
        (folder / name).write_text(markdown + "\n", encoding="utf-8")
        found.append({"page": number, "kind": "grid", "file": name})
    rolls = sum(1 for line in text.splitlines() if _ROLL_LINE.match(line))
    if rolls >= ROLL_LINES:
        found.append({"page": number, "kind": "roll", "lines": rolls})
    if found:
        image = f"{stem}.png"
        page.get_pixmap(dpi=110).save(folder / image)
        for entry in found:
            entry["image"] = image
    return found


# Table of contents -----------------------------------------------------------------------

def _toc(doc, pages):
    """The PDF's bookmarks if it has them, else headings guessed from font sizes."""
    last = doc.page_count
    # A bookmark can point nowhere (-1) or, in a damaged outline, past the last page.
    outline = [(level, title.strip(), page) for level, title, page, *_ in doc.get_toc(simple=False) if 1 <= page <= last]
    source = "outline"
    if not outline:
        outline, source = _headings(doc), "fonts"
    entries = []
    for i, (level, title, start) in enumerate(outline):
        later = [s for lv, _, s in outline[i + 1:] if lv <= level]
        end = max(start, (later[0] - 1) if later else last)
        entries.append({"level": level, "title": title, "start": start, "end": end,
                        "chars": sum(p["chars"] for p in pages[start - 1:end])})
    return entries, source if entries else "none"


def _headings(doc):
    """Lines set well above the body size, ranked into levels by size. A guess, which is
    why toc.json says where it came from."""
    lines, sizes = [], Counter()
    for index, page in enumerate(doc):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = " ".join(s["text"].strip() for s in spans)
                size = round(max(s["size"] for s in spans), 1)
                sizes[size] += len(text)
                lines.append((index + 1, size, text))
    if not sizes:
        return []
    body = sizes.most_common(1)[0][0]
    big = sorted({size for _, size, text in lines if size >= body * 1.3 and len(text) <= 80}, reverse=True)[:3]
    level = {size: i + 1 for i, size in enumerate(big)}
    found = []
    for page, size, text in lines:
        if size in level:
            if found and found[-1][2] == page and found[-1][0] == level[size]:
                found[-1] = (level[size], f"{found[-1][1]} {text}", page)  # a heading set on two lines
            else:
                found.append((level[size], text, page))
    return found


def chapter_level(toc):
    """The level whose entries are chapters: the top one, unless it holds a single entry
    over the others (a book's title set above its chapters)."""
    levels = sorted({e["level"] for e in toc})
    for level in levels:
        if sum(1 for e in toc if e["level"] == level) > 1:
            return level
    return levels[0] if levels else 1


def _chapters(toc, texts, markers, folder):
    """One file per top-level entry: the unit an agent reads in one go."""
    if not toc:
        return 0
    top = chapter_level(toc)
    chapters = [e for e in toc if e["level"] == top]
    for i, entry in enumerate(chapters, 1):
        name = f"{i:02d}-{packs.slug(entry['title'])[:40].replace('_', '-') or 'chapter'}.md"
        entry["file"] = f"chapters/{name}"
        body = "".join(markers[n] + texts[n] for n in range(entry["start"], entry["end"] + 1))
        (folder / name).write_text(f"# {entry['title']} (pages {entry['start']}-{entry['end']})\n" + body, encoding="utf-8")
    return len(chapters)
