"""The inventory of a book, and `solo audit`: what a pack holds against what the book has.

A pack compiled from a book by an agent goes wrong in two quiet ways: something in the
book never makes it into the pack, or something appears in the pack that the book never
said. The inventory (inventory.toml in the pack) lists what the book holds, item by item,
with its pages, and where each item went. The audit reads it the other way too: every
section, table, scene, NPC and rules page the pack has must be claimed by an item, and
every page of the book with text on it must be cited by one.

    source  = "Dragonbane Core Rules"
    extract = "~/Games/solo/sources/dragonbane-core-rules"   # solo extract's folder

    [items.boons_and_banes]
    kind   = "mechanic"
    pages  = [30, "31-32"]
    status = "mapped"
    to     = ["system.toml:untrained", "rules/boons_and_banes.md"]

The format is in docs/PACK_FORMAT.md.
"""

import json
import re
import unicodedata
from pathlib import Path

from . import SoloError, dice, library, packs
from .extract import SCANNED_BELOW, chapter_level
from .library import REPO

KINDS = ("mechanic", "table", "creature", "npc", "spell", "ability", "gear", "place",
         "event", "component", "advice", "other")
# mapped: in the pack, where `to` says. house: in the pack, but not from the book (a stand-in).
# engine: the engine can't run it yet (the note says what it needs). skipped: left out on
# purpose (the note says why). todo: not decided yet.
STATUSES = ("mapped", "house", "engine", "skipped", "todo")
# system.toml keys that describe the pack or an import, not the game.
_SYSTEM_META = ("name", "family", "source", "foundry", "extends", "format")
_RANGE = re.compile(r"^(\d+)\s*-\s*(\d+)$")
# The folders of a pack that hold an entry a file (tables/fear.toml), as the engine loads them.
_FOLDERS = ("tables", "characters", "bestiary", "spells", "moves", "assets")


def load_inventory(pack):
    """inventory.toml, and every inventory/*.toml beside it: a long book is inventoried a
    chapter to a file, so agents working on different chapters never write the same file.
    An id in two files is a problem, not a merge."""
    path = Path(pack) / "inventory.toml"
    if not path.exists():
        raise SoloError(f"{Path(pack).name} has no inventory.toml: the audit compares the pack against it (docs/PACK_FORMAT.md)")
    data = packs.load_data(path)
    items, problems, origin = {}, [], {}
    files = [(path, data), *((f, packs.load_data(f)) for f in sorted((Path(pack) / "inventory").glob("*.toml")))]
    listed = []
    for file, content in files:
        name = file.name if file == path else f"inventory/{file.name}"
        for item_id, item in content.get("items", {}).items():
            if item_id in origin:
                problems.append(f"item {item_id}: in both {origin[item_id]} and {name} (ids are shared by the whole inventory)")
                continue
            origin[item_id] = name
            listed.append((item_id, item, name))
    for item_id, item, name in listed:
        label = f"item {item_id}"
        if not isinstance(item, dict):
            problems.append(f"{label}: expected a table")
            continue
        status, kind = item.get("status", "todo"), item.get("kind")
        if status not in STATUSES:
            problems.append(f"{label}: status {status!r}, expected one of {', '.join(STATUSES)}")
        if kind not in KINDS:
            problems.append(f"{label}: kind {kind!r}, expected one of {', '.join(KINDS)}")
        try:
            pages = parse_pages(item.get("pages", []))
        except ValueError as error:
            problems.append(f"{label}: {error}")
            pages = []
        to = item.get("to", [])
        to = [to] if isinstance(to, str) else list(to)
        items[item_id] = {**item, "id": item_id, "name": item.get("name") or item_id.replace("_", " ").capitalize(),
                          "status": status, "pages": pages, "to": to, "note": item.get("note", "").strip(), "file": name}
    extract = data.get("extract")
    # A relative extract is under SOLO_HOME (sources/<book>): the inventory reads the same on every machine.
    return {"source": data.get("source", ""), "extract": library.home() / Path(extract).expanduser() if extract else None,
            "items": items, "problems": problems}


def kept(folder):
    """An extract's folder as an inventory keeps it: under SOLO_HOME, relative to it (sources/<book>), so the pack is the same file on
    every machine; anywhere else, the whole path."""
    folder, home = Path(folder).expanduser().resolve(), library.home().expanduser().resolve()
    return folder.relative_to(home).as_posix() if home in folder.parents else str(folder)


def parse_pages(value):
    """[12, "14-16"] -> [12, 14, 15, 16]."""
    pages = []
    for entry in [value] if isinstance(value, (int, str)) else value:
        if isinstance(entry, int) and not isinstance(entry, bool) and entry > 0:
            pages.append(entry)
        elif isinstance(entry, str) and entry.strip().isdigit():
            pages.append(int(entry))
        elif isinstance(entry, str) and _RANGE.match(entry.strip()):
            low, high = map(int, _RANGE.match(entry.strip()).groups())
            if low > high:
                raise ValueError(f"page range {entry!r} runs backwards")
            pages += range(low, high + 1)
        else:
            raise ValueError(f"page {entry!r}: expected a number or a range like \"12-14\"")
    return sorted(set(pages))


def audit(pack, kind, extract=None):
    """kind is "system" or "adventure". Returns a report dict; `problems` makes it fail."""
    pack = Path(pack)
    inventory = load_inventory(pack)
    loaded = packs.load_system(pack) if kind == "system" else packs.load_adventure(pack)
    items = inventory["items"]
    problems = list(inventory["problems"])
    for item in items.values():
        problems += _item_problems(item, pack, loaded)

    units = pack_units(pack, kind, loaded)
    claimed = [ref for item in items.values() if item["status"] in ("mapped", "house") for ref in item["to"]]
    unclaimed = [unit for unit in units if not any(_covers(ref, unit) for ref in claimed)]

    report = {
        "pack": pack.name,
        "source": inventory["source"],
        "counts": {s: sum(1 for i in items.values() if i["status"] == s) for s in STATUSES},
        "todo": [i for i in items.values() if i["status"] == "todo"],
        "problems": problems,
        "unclaimed": unclaimed,
        "engine": [i for i in items.values() if i["status"] == "engine"],
        "prose_only": [i for i in items.values() if i["status"] == "mapped" and i["kind"] == "mechanic"
                       and i["to"] and all(ref.startswith("rules/") for ref in i["to"])],
        "units": len(units),
    }
    folder = Path(extract).expanduser() if extract else inventory["extract"]
    report["pages"] = _page_coverage(folder, items) if folder else None
    book = _book_pages(folder) if folder else {}
    lines = _book_lines(folder) if book else {}
    report["unverified"] = [line for item in items.values() for line in _checked(item, pack, loaded, book, lines)] if book else []
    report["files"] = _progress(items)
    return report


def failed(report):
    pages = report["pages"]
    return bool(report["todo"] or report["problems"] or report["unclaimed"] or report.get("unverified")
                or (pages and (pages["missing"] or pages["uncited"] or pages["beyond"])))


# Items -----------------------------------------------------------------------------------

def _item_problems(item, pack, loaded):
    label, status = f"item {item['id']}", item["status"]
    problems = []
    if status in ("mapped", "house") and not item["to"]:
        problems.append(f"{label}: {status} but `to` names nothing in the pack")
    if status in ("house", "engine", "skipped") and not item["note"]:
        why = {"house": "where it comes from, since the book doesn't give it", "engine": "what the engine needs to run it",
               "skipped": "why it's left out"}[status]
        problems.append(f"{label}: {status} needs a note saying {why}")
    if status != "house" and not item["pages"]:
        problems.append(f"{label}: no pages (every item from the book cites where it is)")
    for ref in item["to"]:
        error = resolve(ref, pack, loaded)
        if error:
            problems.append(f"{label}: to {ref!r}: {error}")
    return problems


def resolve(ref, pack, loaded):
    """None if the reference names something in the pack, else what's wrong.

    tables/fear, npcs/priest, characters/ragna     a file by its stem
    rules/fear.md                                  a file by its name
    scenes/cellar                                  a scene, in scenes.json, adventure.toml or scenes/
    system.toml:combat.damage_bonus                a key inside a TOML or JSON file
    skill:solo-gm                                  one of the repository's skills (GM advice)
    """
    if ref.startswith("skill:"):
        return None if (REPO / "skills" / ref[6:] / "SKILL.md").exists() else f"no skill called {ref[6:]!r}"
    # A pack laid over another (extends) can map an item to what the base already holds:
    # the book's check on its numbers is what shows whether the base had them right.
    errors = [_resolve_in(ref, Path(root), loaded) for root in loaded.get("dirs") or [pack]]
    return None if None in errors else errors[0]


def _resolve_in(ref, pack, loaded):
    path, _, key = ref.partition(":")
    if path.startswith("scenes/") and not key and "scenes" in loaded:
        return None if Path(path).stem in loaded["scenes"] else "no such scene"
    target = pack / path
    if not target.suffix and not key:
        matches = list(target.parent.glob(f"{target.name}.*")) if target.parent.is_dir() else []
        return None if matches else "no such file"
    if not target.exists():
        return "no such file"
    if key:
        if target.suffix not in (".toml", ".json"):
            return "only TOML and JSON files have keys"
        node = packs.load_data(target)
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return f"no key {key!r} in {path}"
            node = node[part]
    return None


# What the pack holds -------------------------------------------------------------------

def pack_units(pack, kind, loaded):
    """Everything in the pack an item must claim, as references."""
    units = []
    if kind == "system":
        for name in ("system.toml", "creation.toml", "gear.toml"):
            path = pack / name
            if path.exists():
                data = packs.load_data(path)
                skip = _SYSTEM_META if name == "system.toml" else ()
                units += [f"{name}:{key}" for key in _keys(data) if key.split(".")[0] not in skip]
    else:
        units += [f"scenes/{sid}" for sid in loaded["scenes"]]
        units += [f"npcs/{nid}" for nid in loaded["npcs"]]
        files = [pack / "adventure.toml", *sorted((pack / "chapters").glob("*.toml"))]
        for spec in (f for f in files if f.exists()):
            data, name = packs.load_data(spec), spec.relative_to(pack).as_posix()
            for section in ("factions", "clocks", "weapons"):
                units += [f"{name}:{section}.{key}" for key in data.get(section, {})]
    # This pack's own files: a pack laid over another claims only what it adds.
    for folder in _FOLDERS:
        units += [f"{folder}/{stem}" for stem in packs._load_folder(pack / folder)]
    units += [f"rules/{p.name}" for p in sorted((pack / "rules").glob("*.md"))]
    return units


def _keys(data):
    """A section whose values are all tables is claimed one entry at a time (each weapon,
    each rest, each creation choice); any other section as a whole."""
    keys = []
    for key, value in data.items():
        if isinstance(value, dict) and value and all(isinstance(v, dict) for v in value.values()):
            keys += [f"{key}.{sub}" for sub in value]
        else:
            keys.append(key)
    return keys


def _covers(ref, unit):
    """A reference claims what it names and anything under it: system.toml:weapons claims
    every weapon (the book's weapons table), system.toml:weapons.dagger only the dagger, and
    a reference deeper than a unit (weapons.dagger.damage) still claims its unit.
    tables/fear.toml claims tables/fear."""
    ref = re.sub(r"^(tables|npcs|characters|scenes|bestiary|spells|moves|assets)/([^:/]+)\.(toml|json|md)$", r"\1/\2", ref)
    return ref == unit or ref.startswith(unit + ".") or unit.startswith(ref + ".")


# What the book holds -------------------------------------------------------------------

def _page_coverage(folder, items):
    manifest_path = folder / "manifest.json"
    if not manifest_path.exists():
        return {"folder": str(folder), "missing": True, "uncited": [], "chapters": [], "beyond": []}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    toc_path = folder / "toc.json"
    toc = json.loads(toc_path.read_text(encoding="utf-8")) if toc_path.exists() else []
    with_text = {n for n, text in _page_texts(folder).items() if len(text.strip()) >= SCANNED_BELOW}
    cited = {page for item in items.values() for page in item["pages"]}
    uncited = sorted(with_text - cited)
    top = chapter_level(toc)
    chapters = []
    for entry in (e for e in toc if e["level"] == top):
        span = set(range(entry["start"], entry["end"] + 1))
        missing = sorted(span & set(uncited))
        if missing:
            chapters.append({"title": entry["title"], "start": entry["start"], "end": entry["end"], "uncited": missing})
    return {"folder": str(folder), "missing": False, "source": manifest.get("source"), "pages": manifest.get("pages"),
            "with_text": len(with_text), "cited": len(with_text & cited), "uncited": uncited, "chapters": chapters,
            "beyond": sorted(p for p in cited if p > manifest.get("pages", 0)),
            "pictures": sorted(int(p.stem) for p in folder.glob("picture/*.txt") if p.stem.isdigit())}


# Checked against the book ----------------------------------------------------------------
#
# Coverage says every item went somewhere; it can't say the pack copied the book right. An
# agent that half-remembers a rulebook writes plausible numbers. So what a mapped item
# points at is read back against the pages it cites: a table's results, word for word
# (order aside, since columns scramble) and, where the page sets the table as rows, each on
# the row its range starts; its dice against its results' ranges; and in any data (weapons,
# rests, monsters, gear) every dice expression, stat and price.

_CHECKS_SHOWN = 5


def _page_texts(folder):
    """{page: text}: what the PDF says on the page, then what an agent read off the page's
    picture (picture/0020.txt) where the PDF has no text there: a card whose value is art.
    Kept apart from pages/, which a new extract starts over."""
    texts = {}
    for part in ("pages", "picture"):
        for path in sorted(Path(folder).glob(f"{part}/*.txt")):
            if path.stem.isdigit():
                texts[int(path.stem)] = texts.get(int(path.stem), "") + "\n" + path.read_text(encoding="utf-8")
    return texts


def _book_pages(folder):
    return {number: _norm(text) for number, text in _page_texts(folder).items()}


def _book_lines(folder):
    """{page: [each line of its text, normalised]}: where a table's rows start."""
    return {number: [line for line in map(_norm, re.sub(r"\u00ad\s*", "", text).splitlines()) if line]
            for number, text in _page_texts(folder).items()}


def _norm(text):
    # A soft hyphen marks where a word may break ("market\u00adplace"), at a line's end too.
    text = unicodedata.normalize("NFKC", re.sub(r"\u00ad\s*", "", str(text))).lower()
    return " ".join(re.sub(r"[\u2010-\u2015\u2212]", "-", text).replace("\u00d7", "x").split())


def _checked(item, pack, loaded, book, lines):
    # A page the extract doesn't have is past the book's last, which the page check says: it is no scan to run OCR on.
    pages = [page for page in item["pages"] if page in book]
    if item["status"] != "mapped" or not pages:
        return []
    text = " ".join(book[page] for page in pages)
    where = f"p. {spans(item['pages'])}"
    if not re.search(r"[a-z]", text):
        # A scanned page has no words, and nothing the pack says can be read back against it.
        return [f"{item['id']}: p. {spans(pages)} has no text to read the pack against (a scanned page has none): run ocrmypdf on the PDF and "
                f"extract it again, or write what the page's picture says in picture/{pages[0]:04d}.txt in the extract"]
    words = set(re.findall(r"[a-z0-9]+", text))
    # A number with its unit set close after it ("2H", "10m") is the number too.
    words |= {found.group(1) for found in map(re.compile(r"(\d+)[a-z]+").fullmatch, list(words)) if found}
    cited = [line for page in pages for line in lines.get(page, [])]
    found = []
    for ref in item["to"]:
        data = _data_for(ref, loaded)
        if data is None:
            continue
        # A table's own dice are often never printed (the book just lists 1-6); its results' dice are.
        # A result can name the page it is on (`page`, a PDF page): a deck of cards is a page each, and
        # a value found on another card is no proof of this one, so that result is read against its page alone.
        parts = [(data, text, where)]
        if ref.startswith("tables/"):
            parts = [({k: v for k, v in data.items() if k not in ("formula", "results")}, text, where)]
            rows = _rows(cited, data.get("results", []))
            for at, result in enumerate(data.get("results", [])):
                page = result.get("page")
                own = book.get(page, "") if isinstance(page, int) else text
                own_where = f"p. {page}" if isinstance(page, int) else where
                own_words = _words(own)
                label = _label(result)
                for said in _said(result):
                    missing = _missing_words(said, own_words) or _missing_numbers(said, own_words)
                    if missing:
                        found.append(f"{item['id']}: {ref} result {label} \"{_short(said)}\" isn't on {own_where} "
                                     f"(no {', '.join(missing[:4])})")
                        break
                else:
                    found += [f"{item['id']}: {ref} result {label} \"{_short(_said(result)[0])}\" {line}"
                              for line in _row_problems(at, rows, own_words, own_where)]
                parts.append(({k: v for k, v in result.items() if k not in ("range", "page")}, own, own_where))
            found += [f"{item['id']}: {ref} {line}" for line in _formula_problems(data, where)]
        for part, part_text, part_where in parts:
            for dice in sorted(set(_dice_in(part))):
                if not _dice_on(dice, part_text):
                    found.append(f"{item['id']}: {ref} has {dice}, and {part_where} never says it")
        own = _own(ref, pack)
        if own is None:
            # The pack maps what only a pack under it holds: the book's pages show whether that one had its numbers right.
            found += [f"{item['id']}: {ref} gives {label} {number}, and {where} never says it"
                      for label, number in _numbers_in(ref, data) if not _says_number(number, text, words)]
        else:
            found += [f"{item['id']}: {ref} {line}" for line in _entry_problems(ref, own, text, words, where, loaded.get("tracks") or {}, cited, _names(loaded))]

    money = loaded.get("money") or {}
    entries = [(ref, _data_for(ref, loaded)) for ref in item["to"] if ref.startswith("gear.toml:gear.")]
    for ref in _prices_apart([(r, d) for r, d in entries if isinstance(d, dict)], text, {*money.get("coins", {}), *money.get("aliases", {})}):
        entry = dict(entries)[ref]
        found.append(f"{item['id']}: {ref} prices {entry['name']} at {entry['price']}, and {where} never puts that price beside its name")
    return found[:_CHECKS_SHOWN] + ([f"{item['id']}: and {len(found) - _CHECKS_SHOWN} more like these"] if len(found) > _CHECKS_SHOWN else [])


def _data_for(ref, loaded):
    """What a reference points at, as the engine loaded it (every layer of a pack)."""
    path, _, key = ref.partition(":")
    stem = Path(path).stem
    folder = path.partition("/")[0]
    if "/" in path and folder in (*_FOLDERS, "npcs"):
        return loaded.get(folder, {}).get(stem)
    roots = {"system.toml": loaded, "adventure.toml": loaded, "creation.toml": loaded.get("creation"),
             "gear.toml": {"gear": loaded.get("gear"), "money": loaded.get("money")}}
    if not key or path not in roots:
        return None
    node = roots[path]
    for part in key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


_DICE = re.compile(r"\b(\d*)d(\d+)(?:\s*x\s*(\d+))?\b")


def _dice_in(data):
    if isinstance(data, dict):
        for value in data.values():
            yield from _dice_in(value)
    elif isinstance(data, list):
        for value in data:
            yield from _dice_in(value)
    elif isinstance(data, str):
        for count, sides, times in _DICE.findall(data.lower()):
            yield f"{count if count not in ('', '1') else ''}d{sides}" + (f"x{times}" if times else "")


def _dice_on(dice, text):
    """A dice expression on the pages; a multiplier (2d6x10) has to be there too: it is the number
    a card deck's coins turn on, and the one most easily remembered wrong."""
    count, _, rest = dice.partition("d")
    sides, _, times = rest.partition("x")
    head = rf"\b{count}d{sides}" if count else rf"(?<![0-9])(1)?d{sides}"
    return re.search(head + (rf"\s*x\s*{times}" if times else "") + r"\b", text) is not None


def _numbers_in(ref, data):
    """The numbers a stat block or a price stands on: hit points, armor, ferocity; what a
    thing costs."""
    numbers = []
    if isinstance(data, dict) and ref.startswith(("bestiary/", "npcs/")):
        stats = data.get("stats", {})
        numbers += [(k, stats[k]) for k in ("hp", "armor", "ferocity") if isinstance(stats.get(k), int) and stats[k] > 0]
    if isinstance(data, dict) and "price" in data:
        numbers += [("price", int(n)) for n in re.findall(r"\d+", str(data["price"]))]
    return numbers


# The numbers of an entry ------------------------------------------------------------------
#
# Every number of an entry the book gives (a weapon, a rest, a piece of gear, a monster, a spell,
# a creation choice, a hero) is on the pages its item cites. Where a page labels a value ("HP: 18",
# "Rank: 2", "D6 HP"), the value has to be one the label carries: a monster's HP of 12 doesn't
# pass because its page has a 12 somewhere else. And a number the page has only as another
# label's value (the 18 of "HP: 18", for the skill of the monster's attack) isn't the entry's. A
# monster's, an NPC's or a hero's label is read on its own stat block, from the line its name starts
# to the next entry's (or, with no line of its own, on what isn't another entry's): a sidebar or
# another creature on the page has values of its own.
# What a recipe or an agent works out rather than copies is not read: 0 and 1 (a book says
# "none", "a", "once"), time (counted in seconds, or in rests), a list (a table the recipe may have
# completed: a row between two the book prints, a top for "17+"), and what each coin is worth.

_UNREAD = ("time",)
_NUMBER_WORDS = {2: ("two", "twice", "double", "half"), 3: ("three", "thrice", "third"), 4: ("four", "quarter"), 5: ("five",), 6: ("six",),
                 7: ("seven",), 8: ("eight",), 9: ("nine",), 10: ("ten",), 11: ("eleven",), 12: ("twelve",), 20: ("twenty",)}
# The labels a book sets before a stat's value ("HP: 18"), by the key a pack holds the stat under.
_STAT_LABELS = {"hp": ("hp",), "wp": ("wp",), "armor": ("armor",), "ferocity": ("ferocity",), "movement": ("movement", "mov."), "rank": ("rank",)}


def _own(ref, pack):
    """What a reference points at in the pack's own files, without the packs it is laid over: None
    when only those hold it."""
    path, _, key = ref.partition(":")
    folder = path.partition("/")[0]
    if "/" in path and folder in (*_FOLDERS, "npcs"):
        found = {}
        for suffix in (".json", ".toml"):
            file = Path(pack) / folder / f"{Path(path).stem}{suffix}"
            found.update(packs.load_data(file) if file.exists() else {})
        return found or None
    if path not in ("system.toml", "creation.toml", "gear.toml") or not key or not (Path(pack) / path).exists():
        return None
    node = packs.load_data(Path(pack) / path)
    for part in key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def _entries(ref, data):
    """[(name, entry)] whose numbers are read back, of what a reference points at: a file of its own
    (a monster, an NPC, a spell, a hero), a key of system.toml, creation.toml or gear.toml that names
    one entry, or each entry of a section that is a table of them (system.toml:weapons: each weapon;
    system.toml:armor: each armor's rating). Not a section of other things (combat, magic)."""
    path, _, key = ref.partition(":")
    if "/" in path:
        return [("", data)] if path.partition("/")[0] in ("bestiary", "npcs", "spells", "characters") and isinstance(data, dict) else []
    if path not in ("system.toml", "creation.toml", "gear.toml") or not key or not isinstance(data, dict) or key.split(".")[0] in ("money", *_UNREAD):
        return []
    if "." in key:
        return [("", data)]
    if data and all(isinstance(value, dict) for value in data.values()):
        return [(f"{name}.", value) for name, value in data.items()]
    if data and all(_whole(value) for value in data.values()):
        return [("", data)]
    return []


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _numbers(entry, prefix=""):
    """[(path, key, number)]: an entry's numbers that are read back (see above), and its prices'."""
    found = []
    for key, value in entry.items():
        if key in _UNREAD:
            continue
        elif isinstance(value, dict):
            found += _numbers(value, f"{prefix}{key}.")
        elif _whole(value) and abs(value) > 1:
            found.append((f"{prefix}{key}", key, abs(value)))
        elif key == "price":
            found += [(f"{prefix}{key}", key, int(n)) for n in re.findall(r"\d+", str(value))]
    return found


def _track_dice(entry, tracks, prefix=""):
    """[(path, track, dice)]: the dice an entry gives a track ("1d6" HP a rest recovers)."""
    found = []
    for key, value in entry.items():
        if isinstance(value, dict):
            found += _track_dice(value, tracks, f"{prefix}{key}.")
        elif key in tracks and isinstance(value, str):
            found += [(f"{prefix}{key}", key, dice) for dice in _dice_in(value)]
    return found


def _says_number(number, text, words):
    """Whether the pages have a number: as digits (with a unit after them, "2H", too: see _checked), in
    words ("two", "twice"), or (meters) in kilometers."""
    return (str(number) in words or any(word in words for word in _NUMBER_WORDS.get(number, ()))
            or (number % 1000 == 0 and re.search(rf"\b{number // 1000}\s*kilomet", text) is not None))


def _labelled(text, labels):
    """[(value, start, end)] of each number the pages set after one of these labels and a colon ("hp: 18")."""
    found = []
    for label in labels:
        for at in re.finditer(rf"(?<![a-z]){re.escape(label)}\s*:\s*(\d+)(\s*kilomet)?", text):
            found.append((int(at.group(1)) * (1000 if at.group(2) else 1), at.start(1), at.end(1)))
    return found


def _paired(text, labels, blocks=()):
    """The values the pages give a stat by one of its labels: after it and a colon ("hp: 18"), or just
    before it where nothing follows it ("with 20 hp."). None when the label is set without its value
    beside it: followed by something other than a number ("armor: same as armor", "willpower points:
    -"), where a recipe works the stat out and the page's other values of it are no measure of this
    one, or in a column of labels whose values come after them all ("armor: hp: 4 18"). Empty when no
    label has a colon and a number after it: a number just before a label is as likely the value of
    the one above it (a sheet read top to bottom, "willpower points 13 hit points 15"), so it only adds
    to what a colon gives. On an entry's own stat blocks (`blocks`), the value is the first after the
    label in each, with a colon or without ("hp 18")."""
    if any(_unvalued(part, label) for part in (blocks or [text]) for label in labels):
        return None
    if blocks:
        first = {int(at.group(1)) * (1000 if at.group(2) else 1) for block in blocks for label in labels
                 for at in [re.search(rf"(?<![a-z]){re.escape(label)}\s*:?\s*(\d+)(\s*kilomet)?", block)] if at}
        return first | _before(" ".join(blocks), labels)
    labelled = {value for value, _, _ in _labelled(text, labels)}
    return labelled | _before(text, labels) if labelled else set()


def _unvalued(text, label):
    """Whether the pages set a label without its value beside it (see _paired)."""
    return re.search(rf"(?<![a-z]){re.escape(label)}\s*:(?!\s*\d)|[a-z.]\s*:\s*{re.escape(label)}\s*:", text) is not None


def _before(text, labels):
    """The numbers set just before a label that has no value after it ("with 20 hp.")."""
    return {int(at.group(1)) for label in labels for at in re.finditer(rf"(?<![\w.])(\d+)\s+{re.escape(label)}(?![a-z]|\s*:|\s*\d)", text)}


def _names(loaded):
    """The names of the pack's monsters, NPCs, heroes and spells, as a page's text has them."""
    return {_norm(entry["name"]) for folder in ("bestiary", "npcs", "characters", "spells") for entry in (loaded.get(folder) or {}).values()
            if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"].strip()}


def _blocks(lines, name, names):
    """An entry's own stat blocks among its pages' lines, from each line that starts it to the next that starts another entry of the pack (see
    _entry_at), and the text of the lines in no other entry's block: ([block], text)."""
    blocks, rest, at = [], [], None
    for line in lines:
        starts = _entry_at(line, names | {name})
        if starts is not None:
            at = starts
            if at == name:
                blocks.append([])
        if at == name:
            blocks[-1].append(line)
        if at in (None, name):
            rest.append(line)
    return [" ".join(block) for block in blocks], " ".join(rest)


def _entry_at(line, names):
    """The name of the entry a line starts: the longest of `names` it starts with, or the one whose last words the line is, alone (the
    heading "scout" of the gobs' scout); None for a line that starts none, or could start several."""
    starts = [name for name in names if re.match(rf"{re.escape(name)}(?![a-z])", line)]
    if starts:
        return max(starts, key=len)
    words = line.strip(" .:").split()
    tails = [name for name in names if words and len(name.split()) > len(words) and name.split()[-len(words):] == words]
    return tails[0] if len(tails) == 1 else None


def _entry_problems(ref, data, text, words, where, tracks, lines=(), named=frozenset()):
    """What an entry's numbers say that its pages don't (see above). `lines` are its pages' lines and `named` the names of the pack's
    entries, which say where a monster's, an NPC's or a hero's stat block is."""
    problems = []
    for name, entry in _entries(ref, data):
        numbers = _numbers(entry)
        own = _norm(entry["name"]) if "/" in ref.partition(":")[0] and isinstance(entry.get("name"), str) and entry["name"].strip() else None
        blocks, outside = _blocks(lines, own, set(named)) if own else ([], text)
        labels = {key: (*_STAT_LABELS.get(key, ()), *((key, tracks[key].lower()) if key in tracks else ())) for _, key, _ in numbers}
        labels = {key: names for key, names in labels.items() if names}
        claims = {key: _labelled(text, names) for key, names in labels.items()}
        for path, key, number in numbers:
            said = f"gives {name}{path} {number}, and {where}"
            printed = _paired(outside, labels[key], blocks) if key in labels else set()
            if not _says_number(number, text, words):
                problems.append(f"{said} never says it")
            elif printed and number not in printed:
                problems.append(f"{said} says {labels[key][0]}: {', '.join(map(str, sorted(printed)))}")
            elif str(number) in words and printed is not None and not printed:
                spots = [(at.start(), at.end()) for at in re.finditer(rf"(?<![\w]){number}(?![\w])", text)]
                theirs = {(start, end): other for other, found in claims.items() if other != key for _, start, end in found}
                if spots and all(spot in theirs for spot in spots) and not any(word in words for word in _NUMBER_WORDS.get(number, ())):
                    problems.append(f"{said} has {number} only as {labels[theirs[spots[0]]][0]}: {number}")
        for path, track, rolled in _track_dice(entry, tracks):
            names = "|".join(re.escape(label) for label in (track, tracks[track].lower()))
            printed = {f"{count if count not in ('', '1') else ''}d{sides}" for count, sides in re.findall(rf"\b(\d*)d(\d+)\s+(?:{names})\b", text)}
            if printed and rolled not in printed:
                problems.append(f"gives {name}{path} {rolled}, and {where} says {', '.join(sorted(printed))} {track}")
    return problems


# A price is read back beside its item's name: the plausible price of the wrong row passes a
# check that only asks whether the number is somewhere on the page. A table puts the price
# after the name or before it; whichever way explains most of a table's entries is its way,
# and every entry is judged by that one. A table neither way explains is scrambled (columns
# read down, not across): it isn't judged, and its picture is the truth.
_NEAR = 450


def _prices_apart(entries, text, coins):
    """The refs, of [(ref, gear entry)], whose price isn't the amount of money beside their name
    on the pages. A name the pages don't hold isn't asked (the pack may word it its own way), nor
    a price with no number ("varies"), nor a pack that names no coins."""
    if not coins:
        return []
    amount = re.compile(r"\d+\s*(?:" + "|".join(re.escape(c) for c in sorted(coins, key=len, reverse=True)) + r")\b")
    sides = {}
    for ref, entry in entries:
        name, price = _norm(entry.get("name", "")), re.sub(r"\s+", "", _norm(entry.get("price", "")))
        spots = [m.start() for m in re.finditer(re.escape(name), text)] if name else []
        if spots and re.search(r"\d", price):
            def beside(found):
                return price.startswith(re.sub(r"\s+", "", found.group(0))) if found else False
            after = any(beside(amount.search(text[at + len(name):at + len(name) + _NEAR])) for at in spots)
            before = any(beside(next(iter(reversed(list(amount.finditer(text[max(0, at - _NEAR):at])))), None)) for at in spots)
            sides[ref] = (after, before)
    after, before = sum(a for a, _ in sides.values()), sum(b for _, b in sides.values())
    way = 0 if after >= before else 1
    if max(after, before) * 2 < len(sides):
        return []
    return [ref for ref, found in sides.items() if not found[way]]


_STOP = {"with", "that", "this", "from", "your", "they", "their", "them", "have", "into", "when", "which", "will", "were", "been"}


def _words(text):
    """The words and numbers of normalised text, with a word that a hyphen breaks at a line's end
    also joined whole ("one-" "handed" is "onehanded" too), as solo extract joins one in a block."""
    return {*re.findall(r"[a-z0-9]+", text), *("".join(pair) for pair in re.findall(r"([a-z]+)-\s*([a-z]+)", text))}


def _tokens(text):
    """The words of a result that say something: four letters or more, a dice placeholder ({value}) left out."""
    return [w for w in re.findall(r"[a-z]+", _norm(re.sub(r"\{[^}]*\}", "", str(text)))) if len(w) >= 4 and w not in _STOP]


def _has(words, word):
    return word in words or word.rstrip("s") in words or f"{word}s" in words


def _joined(text):
    """{word: the whole it is part of}, for the words of a text that have a hyphen of their own ("two-handed": "handed" is
    "twohanded"). solo extract joins a word whose line breaks at its hyphen, and a page then has it whole where the recipe kept it."""
    return {part: "".join(parts) for parts in (word.split("-") for word in re.findall(r"[a-z]+(?:-[a-z]+)+", _norm(text))) for part in parts}


def _missing_words(text, words):
    tokens = _tokens(text)
    missing = [w for w in tokens if not _has(words, w)]
    return missing if tokens and len(missing) * 3 > len(tokens) else []


def _missing_numbers(text, words):
    """The numbers a result names (Potency 12, worth 25 gold) that the page doesn't."""
    numbers = re.findall(r"\b\d+\b", _norm(re.sub(r"\{[^}]*\}", "", text)))
    return [n for n in numbers if n not in words]


def _label(result):
    """A result's range as the report names it: "3", or "3-6"."""
    return "-".join(dict.fromkeys(str(n) for n in (result.get("range") or ["?", "?"])[:2]))


def _said(result):
    """The words of a result: its text, its choices, and an NPC attack table's text for each kind of attacker."""
    roles = [v["text"] for v in result.values() if isinstance(v, dict) and isinstance(v.get("text"), str)]
    return [str(result.get("text", "")), *map(str, result.get("choices", [])), *roles]


# A table's rows -------------------------------------------------------------------------
#
# A roll table set as rows has each row on the line its range starts ("3-6", "3–6", "3 to 6",
# a lone "3", "6+" for the last): its words follow the range, and run on over the lines under
# it when the row wraps. Read that way, each result is checked on its own row, so two results
# swapped, a range moved, or a word put into a row ("Never runs away" for "Runs away") show. A
# page's text doesn't always come out as rows: when a table's numbers come out in a column of
# their own and its words after them, there are no rows to read, and a result's words are only
# looked for on the page, as before. Where the PDF wrote each row's words before its number, a
# number on a line of its own has its row above it. And a row that wraps before a number
# ("...shaken and" / "2 WP are lost") goes on over it: a line starts a row only where its range
# isn't started again on the next one, and goes on from the row before rather than back.

_ROW_LINES = 6
# A range at the start of a line: "3", "3-6", "3 to 6", "6+", and "00" for a hundred.
_LEAD = re.compile(r"^(\d{1,3})(?:\s*(?:-|to)\s*(\d{1,3}))?(\+)?(?=$|[\s.:)])")


def _printed(found, top):
    """(low, high) of the range a line starts with: "00" is a hundred, and "6+" runs to the table's top."""
    low, high = (100 if number == "00" else int(number) for number in (found.group(1), found.group(2) or found.group(1)))
    return low, top if found.group(3) else high


def _anywhere(low, high):
    """A range after a space: the second half of a table set in two halves side by side starts its rows in the middle of a line."""
    pattern = rf"0*{low}(?!\s*(?:-|to)\s*\d)" if low == high else rf"0*{low}\s*(?:-|to)\s*0*{high}"
    return re.compile(rf"(?<=\s){pattern}(?=$|[\s.:)])")


def _ranged(result):
    found = result.get("range")
    return isinstance(found, list) and len(found) == 2 and all(isinstance(n, int) and not isinstance(n, bool) for n in found)


def _rows(lines, results):
    """For each result of a table, the rows of its pages that bear on it: {"label", "said" (its text,
    choices and roles), "words" (its own words: a column's name before a colon and a note in brackets
    are the table's), "own" [(text, words) of each row its range starts], "other" [(range, text, words)
    of each row of the table's span that another range starts]}. A row runs on over the lines under it
    as far as the result's words would, short of the next row: the last row has no next row to end it,
    and what is set under the table isn't its own. A result of a deck (`page`) is a card, with no rows."""
    top = max((result["range"][1] for result in results if _ranged(result)), default=0)
    leads = [(number, _printed(found, top), found.end()) for number, line in enumerate(lines) for found in [_LEAD.match(line)] if found]
    leads = [(number, span, end) for number, span, end in leads if 1 <= span[0] <= span[1] <= top]
    starts = _starts(leads)

    def row(number, end, size, back):
        if back and not lines[number][end:].strip(" .:)"):
            # A number on a line of its own, after its words: the row is the lines above it.
            window = []
            for more in range(number - 1, max(number - _ROW_LINES, -1), -1):
                if len(" ".join(window)) >= size or more in starts:
                    break
                window.insert(0, lines[more])
        else:
            window = [lines[number][end:]]
            for more in range(number + 1, min(number + _ROW_LINES, len(lines))):
                if len(" ".join(window)) >= size or more in starts:
                    break
                window.append(lines[more])
        text = " ".join(window).strip(" .:)")
        return text, _words(text)

    def read(back):
        rows = []
        for result in results:
            said = _said(result)
            found = {"label": _label(result), "said": said, "own": [], "other": [],
                     "words": [w for text in said for w in _tokens(re.sub(r"\([^)]*\)|[a-z]+:", " ", _norm(text)))]}
            if _ranged(result) and "page" not in result:
                span, size = tuple(result["range"]), len(_norm(" ".join(said)))
                found["own"] = [row(number, end, size, back) for number, printed, end in leads if printed == span]
                if not found["own"]:
                    anywhere = _anywhere(*span)
                    found["own"] = [(text, _words(text)) for line in lines for at in [anywhere.search(line)] if at
                                    for text in [line[at.end():].strip(" .:)")] if re.search(r"[a-z]", text)]
                found["other"] = [(printed, *row(number, end, size, back)) for number, printed, end in leads if printed != span]
            rows.append(found)
        return rows

    # A number on a line of its own has its words above it where that reads most of the table as rows, and more of it than below does.
    forward, backward = read(False), read(True)
    return backward if _as_rows(backward) and _fitting(backward) > _fitting(forward) else forward


def _starts(leads):
    """The lines, of [(line, range, end)] that begin with a range, that start a row and so end the row above. A line whose range the next one
    starts again ("2 WP are lost" over "2 Runs away") is a wrap of the row above, and so is one that goes back to a range already passed ("1
    round passes" under "3-6 Freezes ... for"), unless the range after it is the next (a second table, from 1 again)."""
    found, passed = set(), 0
    for at, (number, (low, high), _) in enumerate(leads):
        after = leads[at + 1][1] if at + 1 < len(leads) else None
        if after == (low, high) or (low <= passed and (after is None or after[0] != high + 1)):
            continue
        found.add(number)
        passed = high
    return found


def _fits(row, words):
    """Whether a row holds at least half of a result's words."""
    return bool(words) and sum(_has(row, word) for word in words) * 2 >= len(words)


def _fitting(rows):
    """How many results of a table have a row of their own that holds them."""
    return sum(1 for found in rows if any(_fits(words, found["words"]) for _, words in found["own"]))


def _as_rows(rows):
    """Whether most of a table reads as rows: most of its results, and two at least, each on a row of its own."""
    fitting = _fitting(rows)
    return fitting >= 2 and fitting * 2 > sum(1 for found in rows if found["words"])


def _row_problems(at, rows, page_words, where):
    """What is wrong with result `at` on the rows of its table: a word on its row that the page doesn't
    print at all, another range's row, a row of its own that says something else, or no row. Nothing
    when the table's numbers came out in a column of their own, and nothing a row's neighbours don't
    back: a row is only judged where most of the table reads as rows."""
    row = rows[at]
    if not row["words"] or any(found["own"] and not any(re.search(r"[a-z]", text) for text, _ in found["own"]) for found in rows):
        return []
    if any(_fits(words, row["words"]) for _, words in row["own"]):
        missing = list(dict.fromkeys(w for said in row["said"] for joined in [_joined(said)] for w in _tokens(said)
                                     if not _has(page_words, w) and not _has(page_words, joined.get(w, w))))
        return [f"isn't on {where} (no {', '.join(missing[:4])})"] if missing else []
    # Another range's row is this result's when it fits this result alone: a row that fits other results of the table as
    # well (results that share their words, or a row run on into the title of the table below it) proves nothing.
    theirs = [span for span, _, words in row["other"] if _fits(words, row["words"])
              and not any(_fits(words, found["words"]) for other, found in enumerate(rows) if other != at)]
    if theirs:
        return [f"is row {'-'.join(dict.fromkeys(map(str, theirs[0])))} on {where}, not row {row['label']}"]
    if not _as_rows(rows):
        return []
    if row["own"]:
        # A row of short words only ("you run from the", the rest wrapped elsewhere) says too little to say it says something else.
        said = [text for text, _ in row["own"] if _tokens(text)]
        return [f"isn't what row {row['label']} on {where} says (\"{_short(said[0], 40)}\")"] if said else []
    return [f"has no row {row['label']} on {where}: the page doesn't print that range"]


def _formula_problems(table, where):
    """A table's dice against its results' ranges, which are read against the book's rows: a d20 on
    a table of six rows is the wrong die."""
    formula = str(table.get("formula", ""))
    ranges = [result["range"] for result in table.get("results", []) if _ranged(result)]
    if not ranges or "@" in formula:
        return []
    try:
        possible = dice.outcomes(formula)
    except SoloError:
        return []
    low, high = min(r[0] for r in ranges), max(r[1] for r in ranges)
    if (min(possible), max(possible)) != (low, high):
        return [f"rolls {formula} ({min(possible)}-{max(possible)}), and its results, the rows of {where}, run {low}-{high}"]
    return []


def _short(text, size=60):
    text = " ".join(str(text).split())
    return text if len(text) <= size else text[:size - 3].rsplit(" ", 1)[0] + "..."


def _progress(items):
    files = {}
    for item in items.values():
        entry = files.setdefault(item["file"], {"total": 0, "todo": 0})
        entry["total"] += 1
        entry["todo"] += item["status"] == "todo"
    return files


# Starting an inventory ------------------------------------------------------------------

_KIND_WORDS = [
    ("spell", ("spell", "spells", "magic", "school", "trick", "tricks", "rituals")),
    ("creature", ("monster", "monsters", "creature", "creatures", "bestiary", "beast", "beasts", "animals")),
    ("gear", ("gear", "equipment", "weapons", "weapon", "armor", "armour", "prices", "price", "goods", "services", "shields")),
    ("ability", ("ability", "abilities", "talent", "talents", "heroic")),
    ("table", ("table", "tables", "mishap", "mishaps", "random", "encounters")),
    ("npc", ("npcs", "characters", "people")),
    ("place", ("places", "map", "maps", "region", "world", "gazetteer")),
    ("advice", ("advice", "tips", "running", "gamemaster", "game master")),
]


def scaffold(pack, folder, source=None):
    """A first inventory from a book's extract: inventory.toml with the source and the
    extract, and a file per chapter under inventory/ with an item per section (the chapter
    itself when it has none) and one per table found, each `todo` with its pages and a
    guessed kind. Every page with text is cited from the start, so the audit's page check
    only has to hold; an agent per chapter file refines, merges, renames and maps them."""
    pack, folder = library.outside_repository(pack), Path(folder).expanduser().resolve()
    manifest_path, toc_path = folder / "manifest.json", folder / "toc.json"
    if not manifest_path.exists():
        raise SoloError(f"{folder} isn't solo extract's folder (no manifest.json): run solo extract on the book first")
    if pack.resolve() == folder or folder in pack.resolve().parents:
        raise SoloError(f"{pack} is the book's extract: the inventory goes in the pack the book becomes, like ~/Games/solo/systems/<system>")
    if (pack / "inventory.toml").exists() or (pack / "inventory").exists():
        raise SoloError(f"{pack} already has an inventory: the scaffold only starts one")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    toc = json.loads(toc_path.read_text(encoding="utf-8")) if toc_path.exists() else []
    index_path = folder / "tables" / "index.json"
    tables = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
    top = chapter_level(toc) if toc else 1
    chapters = [e for e in toc if e["level"] == top] or [{"title": source or manifest.get("source", "Book"), "start": 1, "end": manifest["pages"]}]
    taken, written = set(), []
    (pack / "inventory").mkdir(parents=True)
    for number, chapter in enumerate(chapters, 1):
        sections = [e for e in toc if e["level"] == top + 1 and chapter["start"] <= e["start"] <= chapter["end"]]
        items = []
        lead_end = (sections[0]["start"] - 1) if sections else chapter["end"]
        if lead_end >= chapter["start"]:
            items.append((chapter["title"], chapter["start"], lead_end, None))
        items += [(s["title"], s["start"], s["end"], None) for s in sections]
        items += [(f"Table on page {t['page']}", t["page"], t["page"], t) for t in tables if chapter["start"] <= t["page"] <= chapter["end"]]
        lines = [f"# {chapter['title']}, pages {chapter['start']}-{chapter['end']}" + (f" ({chapter['file']})" if chapter.get("file") else ""),
                 "# A first cut from the extract: rename, merge, split and map every item, then set its status.", ""]
        for title, start, end, table in items:
            item_id = _unique(packs.slug(title) or "item", taken)
            kind = "table" if table else _guess_kind(title)
            lines += [f"[items.{item_id}]", f"name = {packs.toml_string(title)}", f'kind = "{kind}"',
                      f"pages = [{start}]" if start == end else f'pages = ["{start}-{end}"]', 'status = "todo"']
            if table:
                found = f"tables/{table['file']}" if table.get("file") else f"{table.get('lines', '?')} roll lines"
                picture = table.get("image", "")
                lines.append(f"note = {packs.toml_string(f'solo extract found it: {found}, picture tables/{picture}')}")
            lines.append("")
        name = f"inventory/{number:02d}-{packs.slug(chapter['title'])[:40].replace('_', '-') or 'chapter'}.toml"
        (pack / name).write_text("\n".join(lines), encoding="utf-8")
        written.append(name)
    header = [f"source  = {packs.toml_string(source or Path(manifest.get('source', 'book')).stem)}",
              f"extract = {packs.toml_string(kept(folder))}", "",
              "# The items are in inventory/, a file per chapter. See docs/PACK_FORMAT.md.", ""]
    (pack / "inventory.toml").write_text("\n".join(header), encoding="utf-8")
    return ["inventory.toml", *written]


def _guess_kind(title):
    words = set(re.findall(r"[a-z]+", title.lower()))
    return next((kind for kind, keys in _KIND_WORDS if words & set(keys)), "mechanic")


def _unique(base, taken):
    name, number = base, 2
    while name in taken:
        name, number = f"{base}_{number}", number + 1
    taken.add(name)
    return name


def spans(pages):
    """[1, 2, 3, 7, 9, 10] -> "1-3, 7, 9-10"."""
    runs = []
    for page in pages:
        if runs and page == runs[-1][1] + 1:
            runs[-1][1] = page
        else:
            runs.append([page, page])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


# The report --------------------------------------------------------------------------------

def render(report):
    counts = report["counts"]
    total = sum(counts.values())
    source = f" against {report['source']}" if report["source"] else ""
    lines = [f"# Audit of {report['pack']}{source}", "",
             f"{total} items: " + ", ".join(f"{n} {s}" for s, n in counts.items() if n) + ".",
             f"The pack holds {report['units']} thing{'' if report['units'] == 1 else 's'} an item must claim.", ""]
    verdict = "Something is unaccounted for." if failed(report) else "Everything is accounted for."
    lines += [verdict, ""]
    if report["problems"]:
        lines += [f"## Wrong in the inventory ({len(report['problems'])})", *[f"- {p}" for p in report["problems"]], ""]
    if report["todo"]:
        lines += [f"## Not decided yet ({len(report['todo'])})", *[f"- {_item_line(i)}" for i in report["todo"]], ""]
    if report["unclaimed"]:
        lines += [f"## In the pack, but no item says where it comes from ({len(report['unclaimed'])})",
                  "Cite the book for each, or mark it house with a note if the book doesn't give it.",
                  *[f"- {u}" for u in report["unclaimed"]], ""]
    pages = report["pages"]
    if pages is None:
        lines += ["## The book's pages", "Not checked: set `extract` in inventory.toml or pass --extract (solo extract's folder).", ""]
    elif pages["missing"]:
        lines += ["## The book's pages", f"No manifest.json in {pages['folder']}: run solo extract into it.", ""]
    else:
        lines += ["## The book's pages",
                  f"{pages['cited']} of {pages['with_text']} pages with text are cited ({pages['source']}, {pages['pages']} pages)."]
        if pages["uncited"]:
            lines += ["No item cites these. Read them: each becomes an item, joins one, or is skipped with a note (credits, index, fiction).",
                      *[f"- {c['title']} (p. {spans(range(c['start'], c['end'] + 1))}): {spans(c['uncited'])}" for c in pages["chapters"]]]
            outside = sorted(set(pages["uncited"]) - {p for c in pages["chapters"] for p in c["uncited"]})
            if outside:
                lines.append(f"- outside any chapter: {spans(outside)}")
        if pages["beyond"]:
            lines.append(f"Cited, but past the book's last page: {spans(pages['beyond'])}.")
        if pages["pictures"]:
            lines.append(f"Read from the pictures, not the PDF's text (picture/): p. {spans(pages['pictures'])}. "
                         "The audit checks the pack against that reading, so look at those pages yourself.")
        lines.append("")
    if report.get("unverified"):
        lines += [f"## Not on the cited pages ({len(report['unverified'])})",
                  "The pack says something its pages don't. Copy it from the book (a scrambled table reads right in its picture, "
                  "tables/pNNNN.png), or cite the right pages. A difference on purpose is a house item, with a note.",
                  *[f"- {line}" for line in report["unverified"]], ""]
    if len(report.get("files", {})) > 1:
        lines += ["## By file", *[f"- {name}: {c['todo']} of {c['total']} still todo" if c["todo"] else f"- {name}: all {c['total']} decided"
                                  for name, c in report["files"].items()], ""]
    if report["engine"]:
        lines += [f"## Needs engine work ({len(report['engine'])})", *[f"- {_item_line(i)}" + (f": {i['note']}" if i["note"] else "") for i in report["engine"]], ""]
    if report["prose_only"]:
        lines += [f"## Mechanics only in rules pages ({len(report['prose_only'])})",
                  "The GM reads these; the engine doesn't run them. Fine for now, but each is a candidate for data.",
                  *[f"- {_item_line(i)}" for i in report["prose_only"]], ""]
    return "\n".join(lines)


def _item_line(item):
    where = f" (p. {spans(item['pages'])})" if item["pages"] else ""
    return f"{item['id']}: {item['name']}{where}"
