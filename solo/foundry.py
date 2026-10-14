"""Build packs from Foundry VTT exports.

Input is JSON: files written by Foundry's "Export Data" (one document each), folders of
them, or folders written by `fvtt package unpack`. Adventure documents are opened up
into the journals, actors, tables and items they carry.

Only generated JSON (and scene Markdown) is written. Hand-written TOML beside it is
never touched, and adventure.toml is created once as a stub.
"""

import json
import re
from html.parser import HTMLParser
from pathlib import Path

from . import SoloError, library
from .packs import FORMAT, slug, toml_string

_DOC_TYPES = ("JournalEntryPage", "JournalEntry", "Actor", "RollTable", "Item", "Scene")
_ENRICHER = re.compile(r"@(\w+)\[([^\]]*)\](?:\{([^}]*)\})?")
_INLINE_ROLL = re.compile(r"\[\[/?(?:r|roll|gmr|gmroll|br|blindroll|publicroll)?\s*([^\]]+?)\]\](?:\{([^}]*)\})?")
_LIST_ITEM = re.compile(r"\s*(?:-|\d+\.)\s")


def import_adventure(paths, out, journal=None):
    """Journal pages become scenes (links become exits, NPCs and tables), actors become
    NPC stat blocks, roll tables become tables."""
    out = library.outside_repository(out)
    documents = load_documents(paths)
    journals = [d for d in documents if kind(d) == "JournalEntry"]
    if journal:
        journals = [j for j in journals if journal in (j.get("name"), j.get("_id"))]
    actors = [d for d in documents if kind(d) == "Actor"]
    tables = [d for d in documents if kind(d) == "RollTable"]
    if not journals:
        raise SoloError("no journal entries in the export" + (f" named {journal!r}" if journal else ""))
    else:
        ids = _Ids(journals, actors, tables)
        (out / "scenes").mkdir(parents=True, exist_ok=True)
        scenes = {}
        for entry, page in ids.page_order:
            scene_id = ids.pages[page["_id"]]
            markdown, links = html_to_markdown(_page_html(page), ids.names)
            scene = {"title": page.get("name", scene_id), "exits": {}, "npcs": [], "tables": [], "source": f"{entry.get('name')} / {page.get('name')}"}
            for doc_type, doc_id, label in links:
                target_kind, target = ids.resolve(doc_type, doc_id, label)
                if target_kind == "scene" and target != scene_id:
                    scene["exits"].setdefault(target, label or ids.titles.get(target, target))
                elif target_kind == "npc" and target not in scene["npcs"]:
                    scene["npcs"].append(target)
                elif target_kind == "table" and target not in scene["tables"]:
                    scene["tables"].append(target)
            (out / "scenes" / f"{scene_id}.md").write_text(markdown + "\n", encoding="utf-8")
            scenes[scene_id] = scene
        _write_json(out / "scenes.json", scenes)
        for actor in actors:
            _write_json(out / "npcs" / f"{actor['_pack_id']}.json", _npc(actor, ids))
        for table in tables:
            _write_json(out / "tables" / f"{table['_pack_id']}.json", _table(table))
        stub = out / "adventure.toml"
        if not stub.exists():
            title = journals[0].get("name", out.name)
            stub.write_text(
                "# Created once by `solo import`; re-imports never touch it. Add factions, clocks,\n"
                "# NPC profiles and branches here (see the solo-import skill).\n"
                f"format = {FORMAT}\ntitle = {toml_string(title)}\nstart = {toml_string(next(iter(scenes), ''))}\n",
                encoding="utf-8",
            )
        return out


def import_rules(paths, out):
    """Rules journals and item descriptions become rules/*.md; skill items become
    skills.json (skill -> attribute); roll tables become tables/*.json."""
    out = library.outside_repository(out)
    documents = load_documents(paths)
    journals = [d for d in documents if kind(d) == "JournalEntry"]
    items = [d for d in documents if kind(d) == "Item"]
    tables = [d for d in documents if kind(d) == "RollTable"]
    ids = _Ids(journals, [], tables, items)
    (out / "rules").mkdir(parents=True, exist_ok=True)
    taken = set()
    for _, page in ids.page_order:
        markdown, _ = html_to_markdown(_page_html(page), ids.names)
        name = _unique(slug(page.get("name", "rule")) or "rule", taken)
        (out / "rules" / f"{name}.md").write_text(f"# {page.get('name', name)}\n\n{markdown}\n", encoding="utf-8")
    for item in items:
        system = item.get("system", {})
        text = _html(system.get("itemDescription") or system.get("description"))
        gm_text = _html(system.get("gmDescription"))
        if text or gm_text:
            body = html_to_markdown(text, ids.names)[0]
            if gm_text:
                body += "\n\n::: gm\n" + html_to_markdown(gm_text, ids.names)[0] + "\n:::"
            name = _unique(slug(item.get("name", "item")) or "item", taken)
            (out / "rules" / f"{name}.md").write_text(f"# {item.get('name', name)}\n\n{body.strip()}\n", encoding="utf-8")
    skills = {
        slug(item["name"]): {"attribute": item["system"]["attribute"], "name": item["name"]}
        for item in items
        if item.get("type") == "skill" and item.get("system", {}).get("attribute") not in (None, "", "none")
    }
    if skills:
        _write_json(out / "skills.json", skills)
    for table in tables:
        _write_json(out / "tables" / f"{table['_pack_id']}.json", _table(table))
    return out


def import_character(paths, out, system):
    """A character actor becomes a sheet `solo new --character` accepts. Where the values
    live comes from the system pack's [foundry] table."""
    out = library.outside_repository(out)
    actors = [d for d in load_documents(paths) if kind(d) == "Actor"]
    characters = [a for a in actors if a.get("type") == "character"] or actors
    if not characters:
        raise SoloError("no actor in the export")
    else:
        actor = characters[0]
        data = actor.get("system", {})
        where = system.get("foundry", {})
        attribute_path = where.get("attributes", "attributes.{key}.value")
        track_paths = where.get("tracks", {})
        condition_path = where.get("conditions")
        gear_types = where.get("gear_types")
        items = actor.get("items", [])
        info = {key: _get(data, key) for key in where.get("info", []) if _get(data, key)}
        for item_type in where.get("info_items", []):
            name = next((i["name"] for i in items if i.get("type") == item_type), None)
            if name:
                info[item_type] = name
        sheet = {
            "name": actor.get("name", "The hero"),
            "info": info,
            "attributes": {key: _number(_get(data, attribute_path.format(key=key))) for key in system["attributes"]},
            "skills": {
                slug(i["name"]): {
                    "value": _number(i["system"].get("value")),
                    # Foundry writes "none" for some skills; the system pack's mapping fills those in
                    "attribute": i["system"].get("attribute") if i["system"].get("attribute") in system["attributes"] else None,
                    "name": i["name"],
                }
                for i in items if i.get("type") == "skill"
            },
            "tracks": {},
            "conditions": [],
            "items": [i["name"] for i in items if i.get("type") != "skill" and (gear_types is None or i.get("type") in gear_types)],
        }
        for track in system["tracks"]:
            value = _get(data, track_paths.get(track, track))
            if isinstance(value, dict):
                sheet["tracks"][track] = {"value": _number(value.get("value")), "max": _number(value.get("max", value.get("value")))}
            else:
                sheet["tracks"][track] = {"value": _number(value), "max": _number(value)}
        if condition_path:
            sheet["conditions"] = [
                name for name, attribute in system["conditions"].items()
                if _get(data, condition_path.format(attribute=attribute, name=name))
            ]
        out.parent.mkdir(parents=True, exist_ok=True)
        _write_json(out, sheet)
        return out


# Reading exports --------------------------------------------------------------------------

def load_documents(paths):
    """Every document in the given files and folders, with Adventure documents opened up."""
    documents = []
    for path in map(Path, paths):
        if not path.exists():
            raise SoloError(f"no such file or folder: {path}")
        files = sorted(path.rglob("*.json")) if path.is_dir() else [path]
        for file in files:
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise SoloError(f"{file} isn't valid JSON: {error}") from None
            for document in data if isinstance(data, list) else [data]:
                documents += _expand(document)
    return documents


def kind(document):
    """The Foundry document type, read from its shape (exports don't always say)."""
    key = str(document.get("_key", ""))
    if key.startswith("!adventures!") or ("pages" not in document and any(isinstance(document.get(k), list) for k in ("journal", "actors", "tables"))):
        return "Adventure"
    elif "pages" in document:
        return "JournalEntry"
    elif "results" in document:
        return "RollTable"
    elif "system" in document and ("items" in document or "prototypeToken" in document):
        return "Actor"
    elif "system" in document and "type" in document:
        return "Item"
    else:
        return None


def _expand(document):
    if isinstance(document, dict) and kind(document) == "Adventure":
        return [part for key in ("journal", "actors", "tables", "items") for inner in document.get(key, []) for part in _expand(inner)]
    elif isinstance(document, dict):
        return [document]
    else:
        return []


def document_ids(document):
    """Its own id plus the ids it was copied from, so links still resolve in
    "Export Data" files, which drop the top-level _id."""
    ids = {document.get("_id")}
    for source in (document.get("_stats", {}).get("compendiumSource"), document.get("flags", {}).get("core", {}).get("sourceId")):
        if source:
            ids.add(parse_link("UUID", source)[1])
    return {i for i in ids if i}


def parse_link(enricher, target):
    """(document type, id) from @UUID[JournalEntry.a.JournalEntryPage.b#x], @UUID[.pageId],
    @Actor[id], or an enricher wrapping a UUID (@DisplaySkill[Item.x])."""
    target = target.split("#")[0].split("|")[0].strip()
    if enricher in _DOC_TYPES:
        return enricher, target
    elif target.startswith("."):
        return "JournalEntryPage", target[1:]
    else:
        parts = target.split(".")
        pairs = [(parts[i], parts[i + 1]) for i in range(len(parts) - 1) if parts[i] in _DOC_TYPES]
        return pairs[-1] if pairs else (None, None)


def html_to_markdown(content, names=None):
    """Journal HTML to Markdown, plus the links it contained as (type, id, label).
    Enrichers become their labels, inline rolls their formula, secret sections ::: gm."""
    names = names or {}
    links = []

    def enrich(match):
        enricher, target, label = match.groups()
        doc_type, doc_id = parse_link(enricher, target)
        if doc_type:
            links.append((doc_type, doc_id, label))
        return label or names.get(doc_id) or ""

    text = _ENRICHER.sub(enrich, content or "")
    text = _INLINE_ROLL.sub(lambda m: m.group(2) or m.group(1).strip(), text)
    parser = _Markdown()
    parser.feed(text)
    parser.close()
    return parser.result(), links


class _Markdown(HTMLParser):
    _VOID = {"br", "hr", "img", "input", "meta", "link", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.buffers = [[]]
        self.open = []
        self.lists = []
        self.row = None
        self.rows = 0
        self.skip = 0

    def write(self, text):
        self.buffers[-1].append(text)

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        wrapper = None
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.write("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in ("p", "div", "section", "aside"):
            self.write("\n\n")
        elif tag == "br":
            self.write("\n")
        elif tag == "hr":
            self.write("\n\n---\n\n")
        elif tag in ("strong", "b"):
            self.write("**")
        elif tag in ("em", "i"):
            self.write("*")
        elif tag in ("ul", "ol"):
            self.write("" if self.lists else "\n")
            self.lists.append([tag, 0])
        elif tag == "li":
            current = self.lists[-1] if self.lists else ["ul", 0]
            current[1] += 1
            bullet = f"{current[1]}." if current[0] == "ol" else "-"
            self.write("\n" + "  " * max(0, len(self.lists) - 1) + bullet + " ")
        elif tag == "table":
            self.rows = 0
            self.write("\n\n")
        elif tag == "tr":
            self.row = []
        if tag == "blockquote":
            wrapper = "quote"
        elif "secret" in classes:
            wrapper = "gm"
        elif tag in ("td", "th"):
            wrapper = "cell"
        if wrapper:
            self.buffers.append([])
        if tag not in self._VOID:
            self.open.append((tag, wrapper))

    def handle_endtag(self, tag):
        depth = next((i for i in range(len(self.open) - 1, -1, -1) if self.open[i][0] == tag), None)
        while depth is not None and len(self.open) > depth:
            closed, wrapper = self.open.pop()
            self._close(closed, wrapper)

    def _close(self, tag, wrapper):
        if wrapper:
            text = _tidy("".join(self.buffers.pop()))
            if wrapper == "quote":
                self.write("\n\n" + "\n".join("> " + line for line in text.splitlines()) + "\n\n")
            elif wrapper == "gm":
                self.write("\n\n::: gm\n" + text + "\n:::\n\n")
            elif self.row is not None:
                self.row.append(" ".join(text.split()))
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "section", "aside"):
            self.write("\n\n")
        elif tag in ("strong", "b"):
            self.write("**")
        elif tag in ("em", "i"):
            self.write("*")
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            self.write("" if self.lists else "\n")
        elif tag == "tr" and self.row is not None:
            self.write("| " + " | ".join(self.row) + " |\n")
            if self.rows == 0:
                self.write("|" + " --- |" * len(self.row) + "\n")
            self.rows += 1
            self.row = None

    def handle_data(self, data):
        if not self.skip:
            self.write(re.sub(r"\s+", " ", data))

    def result(self):
        while self.open:
            self._close(*self.open.pop())
        return _tidy("".join(self.buffers[0]))


def _tidy(text):
    """Drop the spaces HTML leaves at line starts (list indentation stays) and long blank runs."""
    lines = [line.rstrip() if _LIST_ITEM.match(line) else line.strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


class _Ids:
    """Pack ids for everything in an import, and the lookups links need."""

    def __init__(self, journals, actors, tables, items=()):
        self.pages, self.entries, self.actors, self.tables = {}, {}, {}, {}
        self.names, self.titles, self.by_name = {}, {}, {}
        self.page_order = []
        taken = set()
        for entry in journals:
            pages = sorted((p for p in entry.get("pages", []) if p.get("type", "text") == "text"), key=lambda p: p.get("sort", 0))
            for page in pages:
                scene_id = _unique(slug(page.get("name", "scene")) or "scene", taken)
                page.setdefault("_id", scene_id)
                self.pages[page["_id"]] = scene_id
                self.titles[scene_id] = page.get("name", scene_id)
                self.names[page["_id"]] = page.get("name", "")
                self.page_order.append((entry, page))
            for entry_id in document_ids(entry):
                self.names[entry_id] = entry.get("name", "")
                if pages:
                    self.entries[entry_id] = self.pages[pages[0]["_id"]]
        for mapping, documents, fallback in ((self.actors, actors, "npc"), (self.tables, tables, "table")):
            used = set()
            for document in documents:
                pack_id = _unique(slug(document.get("name", fallback)) or fallback, used)
                document["_pack_id"] = pack_id
                for doc_id in document_ids(document):
                    mapping[doc_id] = pack_id
                    self.names[doc_id] = document.get("name", "")
                self.by_name[(fallback, slug(document.get("name", "")))] = pack_id
        for item in items:
            for doc_id in document_ids(item):
                self.names[doc_id] = item.get("name", "")

    def resolve(self, doc_type, doc_id, label=None):
        if doc_type == "JournalEntryPage" and doc_id in self.pages:
            return "scene", self.pages[doc_id]
        elif doc_type == "JournalEntry" and doc_id in self.entries:
            return "scene", self.entries[doc_id]
        elif doc_type == "Actor":
            found = self.actors.get(doc_id) or self.by_name.get(("npc", slug(label or "")))
            return ("npc", found) if found else (None, None)
        elif doc_type == "RollTable":
            found = self.tables.get(doc_id) or self.by_name.get(("table", slug(label or "")))
            return ("table", found) if found else (None, None)
        else:
            return None, None


def _npc(actor, ids):
    """A stat block: numbers and short text from the actor's data, skills from its items."""
    data = actor.get("system", {})
    stats = {}
    for key, value in data.items():
        if isinstance(value, bool):
            continue
        elif isinstance(value, (int, float)):
            stats[key] = value
        elif isinstance(value, dict) and isinstance(value.get("value"), (int, float)) and not isinstance(value.get("value"), bool):
            stats[key] = value["value"]
        elif isinstance(value, str) and value and "<" not in value and len(value) < 200:
            doc_type, doc_id = parse_link("UUID", value) if "." in value else (None, None)
            table = ids.tables.get(doc_id) if doc_type == "RollTable" else None
            stats[key] = table or value
    description = next((_html(data.get(k)) for k in ("description", "biography", "notes") if _html(data.get(k))), "")
    npc = {
        "name": actor.get("name", ""),
        "kind": actor.get("type", ""),
        "stats": stats,
        "skills": {slug(i["name"]): i["system"].get("value") for i in actor.get("items", []) if i.get("type") == "skill"},
        "gear": [i["name"] for i in actor.get("items", []) if i.get("type") in ("weapon", "armor", "helmet", "item")],
    }
    if description:
        npc["description"] = html_to_markdown(description, ids.names)[0]
    return {k: v for k, v in npc.items() if v not in ({}, [], "")}


def _table(table):
    results = []
    for result in sorted(table.get("results", []), key=lambda r: r.get("range", [0])[0]):
        text = next((_html(result.get(k)) for k in ("description", "text", "name") if _html(result.get(k))), "")
        low, high = (result.get("range") or [0, 0])[:2]
        results.append({"range": [int(low), int(high)], "text": html_to_markdown(text)[0]})
    formula = (table.get("formula") or "").strip().lower()
    if not formula and results:
        formula = f"1d{max(r['range'][1] for r in results)}"
    return {"name": table.get("name", ""), "formula": formula, "results": results}


def _page_html(page):
    text = page.get("text")
    return text.get("content", "") if isinstance(text, dict) else (text or "")


def _html(value):
    if isinstance(value, dict):
        value = value.get("value", "")
    return value if isinstance(value, str) else ""


def _get(data, path):
    for part in path.split("."):
        data = data.get(part) if isinstance(data, dict) else None
    return data


def _number(value):
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _unique(base, taken):
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}_{n}", n + 1
    taken.add(candidate)
    return candidate


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
