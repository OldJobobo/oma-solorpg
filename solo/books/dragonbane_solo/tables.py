"""The tables of the solo booklet as tables/<id>.toml: what the booklet prints (the inspiration prompts, the areas, the traps) and what it only says in
words (how many details a location has). A result carries the engine's wiring where the booklet's own words say it: "two treasure cards, and roll
again" is a draw of two from the treasure deck and a roll on this table again; "Roll D4. 1: creature, 2: trap" is a choice of four.
"""

import re

from ... import packs
from ...tomlwrite import Inline
from .. import dice
from ..dragonbane_core import ids
from ..read import changed, count, roll

# The tables whose rows are what the booklet prints: (where, id, name).
_SIMPLE = [(("Your Missions", "Mission Threats", "Table: Threats"), "threats", "Threats"),
           (("Exploration Tables", "Locations", "Table: Area Table"), "areas", "Area"),
           (("Exploration Tables", "Inhabitants", "Table: Inhabitants"), "inhabitants", "Inhabitants"),
           (("Exploration Tables", "Scavenging", "Table: Scavenge"), "scavenge", "Scavenge"),
           (("Exploration Tables", "Searching", "Table: Search Table"), "search", "Search"),
           (("Exploration Tables", "Traps", "Table: Traps"), "traps", "Traps")]
# The table a draw of treasure is rolled on, which is the treasure deck's (its own pack).
_TREASURE = "treasure"
_NUMBERS = {"once": 1, "twice": 2, "twice,": 2}


def build(pack):
    root = pack.book.find("Alone in Deepfall Breach")
    for path, table_id, name in _SIMPLE:
        _simple(pack, root.find(*path), table_id, name)
    pack.facts["inspiration"] = _columns(pack, root.find("Core Solo Tools", "Inspiration Table", "Table: Inspiration Table"), lambda header: f"inspiration_{packs.slug(header)}",
                                         lambda header: f"Inspiration: {header.lower()}")
    _columns(pack, root.find("Core Solo Tools", "Dragon and Demon Effects", "Table: Dragon and Demon Effects"), lambda header: f"{packs.slug(header)}s", lambda header: header.capitalize())
    _damage(pack, root.find("Surviving Solo Play", "Suffering Damage", "Table: Damage Table"))
    _locations(pack, root.find("Exploration Tables", "Locations"))
    _attackers(pack, root.find("Core Solo Tools", "Managing NPCs and Monsters", "Table: NPC Attack Table"))


def read(pack, section):
    return dice.read(section.lines(own=True), pack.book.glue)


def _write(pack, section, table_id, name, found, rows):
    pack.toml(f"tables/{table_id}.toml", {"name": name, "formula": dice.formula(found["faces"]), "source": f"p. {section.page}", "results": rows})
    pack.facts.setdefault("tables", {})[section.number] = (table_id, dice.formula(found["faces"]))
    pack.item(f"table_{table_id}", name, "table", section.pages, [f"tables/{table_id}"])


def _simple(pack, section, table_id, name):
    found = read(pack, section)
    _write(pack, section, table_id, name, found, [Inline({"range": [row["low"], row["high"]], **_result(row["text"], table_id)}) for row in found["rows"]])


def _result(text, table_id):
    """{text, then, again, roll, choices} for a result, from the words the booklet uses for them: a choice of things ("Roll D4. 1: a, 2: b"), a draw of
    treasure cards, a roll again, a roll twice on this table, a roll for the details of a location, a number of the die ("D4 new waypoints")."""
    result = {"text": text}
    choice = re.match(r"(.*?)\.?\s*Roll (D\d+)\.\s*(1:.*?)\.?$", text)
    if choice:
        result = {"text": choice.group(1), "choices": [item.strip(" ,.") for item in re.split(r"\s*\d+:\s*", choice.group(3)) if item.strip(" ,.")]}
    cards = re.search(r"\b(one|two|three) treasure cards?", text, re.I)
    if cards:
        result["then"] = [_TREASURE] * count(cards.group(1)) if count(cards.group(1)) > 1 else _TREASURE
    elif re.search(r"roll twice", text, re.I):
        result["then"] = [table_id, table_id]
    elif re.search(r"roll for location details", text, re.I):
        result["then"] = "location_detail_rolls"
    if re.search(r"roll again", text, re.I):
        result["again"] = True
    dice_in_words = None if choice else re.search(r"\b(?:to|by) (\d*D\d+)\b", text)
    if dice_in_words:
        result.update({"text": text.replace(dice_in_words.group(1), "{value}"), "roll": roll(dice_in_words.group(1))})
    return result


def _columns(pack, section, table_id, name):
    """A table with a column for each of several things (the actions, the attributes, the things): a table to each, on the same die. The ids, in order."""
    found = read(pack, section)
    made = []
    for at, header in enumerate(dict.fromkeys(header for header in found["headers"] if header and not dice.is_die(header))):
        made.append(table_id(header))
        _write(pack, section, made[-1], name(header), found, [Inline({"range": [row["low"], row["high"]], "text": row["cells"][at]}) for row in found["rows"]])
    return made


def _damage(pack, section):
    """How much harm: a category and its dice, as a table that rolls them (the result's value is the harm)."""
    found = read(pack, section)
    _write(pack, section, "harm", "Suffering damage", found, [Inline({"range": [row["low"], row["high"]], "text": f"{row['cells'][0]}: {{value}} damage", "roll": roll(row["cells"][1])})
                                                                 for row in found["rows"]])


def _locations(pack, section):
    """What the booklet says in words and prints in two tables: a D4 for how many details, a table of which details (contents, environment, oddity, danger)
    and a table of twenty for each."""
    steps = re.search(r"Roll a (D\d+), then roll a D\d+", section.text(own=True).replace("\n", " "))
    if not steps:
        raise changed(section, "can't find how many details a location has")
    details = section.find("Table: Location Details")
    kinds = read(pack, section.find("Table: Subtables"))
    many = {"faces": dice.faces(steps.group(1)), "rows": [{"low": n, "high": n} for n in range(1, dice.faces(steps.group(1)) + 1)]}
    _write(pack, details, "location_detail_rolls", "Location details: how many", many,
           [Inline({"range": [row["low"], row["high"]], "text": f"Roll on the location details table {row['low']} time{'s' * (row['low'] != 1)}", "then": ["location_details"] * row["low"]}) for row in many["rows"]])
    listed = read(pack, details)
    _write(pack, details, "location_details", "Location details", listed,
           [Inline({"range": [row["low"], row["high"]], "text": row["text"], "then": f"location_{packs.slug(row['text'])}"}) for row in listed["rows"]])
    for at, header in enumerate(header for header in kinds["headers"] if header and not dice.is_die(header)):
        _write(pack, section.find("Table: Subtables"), f"location_{packs.slug(header)}", f"Location: {header.lower()}", kinds,
               [Inline({"range": [row["low"], row["high"]], "text": row["cells"][at]}) for row in kinds["rows"]])


def _attackers(pack, section):
    """The NPC attack table: for each roll an entry for each kind of attacker, and what each does as the engine runs it, by the words: it attacks (with a
    boon or a bane, twice, for extra damage, a spell's damage), or it only does something."""
    book = pack.book
    own = section.lines(own=True)
    top = min(line["y0"] for line in own if dice.is_marker(line))
    found = dice.read(own + [line for line in book.by_page[section.page] if line["y0"] >= top and line not in own and line["size"] <= 9.3], book.glue)
    roles = [header for header in found["headers"] if header and not dice.is_die(header)]
    pack.facts["attackers"] = [packs.slug(role.split()[0]) for role in roles]
    rows = [Inline({"range": [row["low"], row["high"]], **{packs.slug(role.split()[0]): Inline(_attacker(row["cells"][at])) for at, role in enumerate(roles)}}) for row in found["rows"]]
    _write(pack, section, "npc_attacks", "NPC attacks", found, rows)


def _attacker(text):
    """One attacker's result: its words, and whether it is an attack (by its first sentence) and with what."""
    action = re.match(r"[^!]*!\s*([^.]*\.)", text)
    entry = {"text": text}
    if action and re.search(r"\b(?:makes an? \w+ attack|attacks|casts an attack spell)\b", action.group(1)):
        entry["attack"] = True
        entry.update({"damage": roll(damage.group(1))} if (damage := re.search(r"inflicts (\d*D\d+) damage", text)) else {})
        entry.update({"boons": 1} if re.search(r"attacks with a boon", text) else {})
        entry.update({"banes": 1} if re.search(r"attacks with a bane|are with a bane", text) else {})
        entry.update({"extra": roll(extra.group(1))} if (extra := re.search(r"extra (\d*D\d+) damage", text)) else {})
        entry.update({"times": 2} if re.search(r"attacks twice", text) else {})
    else:
        entry["effect"] = True
    return entry
