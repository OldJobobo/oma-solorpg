"""The roll tables of the core rules, as tables/<id>.toml: fear, what a Demon brings, the journey's mishaps, hunting,
the quest, the site, who you meet. Tables that belong to something else are read there: a kin's names and a
profession's gear go to character creation, a monster's attacks to the bestiary, the skills' base chance to the numbers.
"""

from ... import packs
from ...sections import paragraphs
from ...tomlwrite import Inline
from .. import dice
from . import ids

# Tables read elsewhere (character creation, the numbers of every roll, the bestiary).
ELSEWHERE = {"Measuring Time", "Base Chance", "Damage Bonus", "Movement", "Effects of Age", "Kin", "First Name", "Profession", "Gear", "Typical NPCs"}
# The book's own name for a table, where it isn't the one to show.
LABELS = {"Mishaps": "Journey mishaps"}
# A table of several dice the book reads as a sentence: the id and name of the table of each die, left to right.
SENTENCES = {
    "The Quest": [("quest_when", "The quest: one day"), ("quest_hook", "The quest: the characters come across"),
                  ("quest_patron", "The quest: from/about/with"), ("quest_goal", "The quest: who wants to"),
                  ("quest_object", "The quest: a"), ("quest_name", "The quest: called")],
    "The Journey": [("journey_kind", "The journey: the journey is"), ("journey_end", "The journey: and ends"),
                    ("journey_site_look", "The journey: there is a/an"), ("journey_site", "The journey: the site"),
                    ("journey_surroundings", "The journey: surrounded by"), ("journey_place_name", "The journey: the place is called")],
    "The Adventure Site": [("site_way_in", "The adventure site: the way in is"), ("site_feature", "The adventure site: there is"),
                           ("site_guests", "The adventure site: unexpected guests"), ("site_monster", "The adventure site: and"),
                           ("site_challenge", "The adventure site: a deadly challenge"),
                           ("site_boss", "The adventure site: finally, the player characters must defeat")],
    "Creating NPCs": [("npc_attitude", "NPC attitude"), ("npc_kin", "NPC kin"), ("npc_motivation", "NPC motivation"),
                      ("npc_profession", "NPC profession"), ("npc_trait", "NPC trait"), ("npc_name", "NPC name (choose one)")],
}


def build(pack):
    book = pack.book
    gear = {id(section) for section in book.find("6. Gear").children}
    for section in book.sections:
        title = section.title.removeprefix("Table:").strip()
        if section.title.startswith("Table:") and id(section) not in gear and title not in ELSEWHERE:
            if title in SENTENCES:
                _sentence(pack, section, title)
            elif title == "Nickname":
                _table(pack, section, f"nicknames_{packs.slug(section.parent.title)}", f"Nicknames: {section.parent.title.lower()}")
            else:
                _table(pack, section, ids.table(title), LABELS.get(title) or ids.sentence(title.removesuffix(" Table")))
    # The box of the severe injuries has no table in its bookmark.
    _table(pack, book.find("Optional Rule: Severe Injuries"), "severe_injuries", "Severe injuries")


def _lines(book, section):
    """The lines of a table, whole. One set in two halves side by side has its header over each and its bookmark at the
    second, so the first is read before the bookmark and belongs to the section above: it is found under the header
    that says the same, in the column to its left."""
    own = section.lines(own=True)
    heads = [line for line in own if dice.is_marker(line)]
    page = book.by_page[section.page]
    twin = next((line for line in page if len(heads) == 1 and dice.is_marker(line) and line["text"] == heads[0]["text"] and line not in own), None)
    half = [line for line in page if twin and line["col"] == twin["col"] and line["y0"] >= twin["y0"] and line not in own]
    return own + half


def _table(pack, section, table_id, name, sides=None):
    """A roll table of a section. `sides` is the most it can roll, for a table whose header has no die (or two: "D6/D10"); its formula is then the highest roll it has a row for."""
    book = pack.book
    lines = _lines(book, section)
    notes = [line for line in lines if line["text"].startswith("* ")]
    found = dice.read([line for line in lines if line not in notes], book.glue, sides)
    top = found["rows"][-1]["high"] if found["rows"] else 0
    found["faces"] = top if sides else max(found["faces"], top)
    columns = [header for header in found["headers"][1:] if header]
    note = paragraphs(notes, book.glue)
    rows = []
    for row in found["rows"]:
        text = _text(row, columns)
        rows.append(Inline({"range": [row["low"], row["high"]], "text": f"{text} ({note})" if note and "*" in text else text}))
    pack.toml(f"tables/{table_id}.toml", {"name": name, "formula": dice.formula(found["faces"]), "source": f"p. {section.page}", "results": rows})
    pack.facts.setdefault("tables", {})[section.number] = (table_id, dice.formula(found["faces"]))
    pack.item(f"table_{table_id}", name, "table", section.pages, [f"tables/{table_id}"])


def _text(row, columns):
    """A row's words: its one column, or, in a table of named columns (an animal, what it takes, what it gives), the
    first and then "Name: cell" for each of the others."""
    if len(columns) >= 2 and len(row["cells"]) == len(columns):
        return "; ".join([row["cells"][0]] + [f"{column.capitalize()}: {cell}" for column, cell in zip(columns[1:], row["cells"][1:])])
    return row["text"]


def _sentence(pack, section, title):
    """A table of several dice, read as a sentence: a table for each column, and the first one rolls the others after it
    (`then`), so one roll gives the sentence."""
    made = SENTENCES[title]
    found = dice.columns(section.lines(own=True), pack.book.glue)
    if len(found) != len(made):
        pack.note(f"{title} (p. {section.page}): the book's table has {len(found)} columns of dice and the importer names {len(made)}: "
                  + (f"the last {len(found) - len(made)} aren't read" if len(found) > len(made) else f"no table is written for the last {len(made) - len(found)}"))
    for index, ((table_id, name), column) in enumerate(zip(made, found)):
        then = {"then": [table_id for table_id, _ in made[1:]]} if index == 0 else {}
        rows = [Inline({"range": [row["low"], row["high"]], "text": row["text"], **then}) for row in column["rows"] if row["text"] not in ("", "—")]
        comment = [f"{title.removeprefix('The ')}, read together, one roll for each column: this table rolls the others after it."] if index == 0 else ()
        pack.toml(f"tables/{table_id}.toml", {"name": name, "formula": dice.formula(column["faces"]), "source": f"p. {section.page}", "results": rows}, comment)
    pack.facts.setdefault("tables", {})[section.number] = (made[0][0], dice.formula(found[0]["faces"]))
    pack.item(f"table_{packs.slug(title)}", title, "table", section.pages, [f"tables/{table_id}" for table_id, _ in made])
