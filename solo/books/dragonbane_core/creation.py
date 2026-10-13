"""Chapter 2, how a hero is made, as creation.toml: the dice the attributes are rolled with, the ratings that follow from
them and, for each table of the chapter (kin, profession, age), what a roll on it gives the hero.

A profession's gear is a table of three sets, one rolled on a D6. A set that offers a choice of weapons is a kit for each
weapon, and a set with no choice is repeated so that every set still comes up one time in three; what every set holds is
`gear`. Weapons and armor are written as the pack's own entries name them, so the engine finds them on the sheet.
"""

import math
import re
from itertools import product

from ... import packs
from .. import dice, grid
from ..read import changed, count, find, says
from . import arms, ids


def build(pack):
    book = pack.book
    chapter = book.find("2. Your Player Character")
    scale = find(chapter.find("Attributes"), r"on a scale from (\d+) to (\d+)", "the scale of an attribute")
    creation = pack.creation
    creation.update(_numbers(chapter, [int(scale.group(1)), int(scale.group(2))]))
    movement, ratings = _ratings(book, chapter.find("Derived Ratings"), int(scale.group(2)))
    creation["ratings"] = ratings
    train = count(find(chapter.find("Skills", "Starting Skill Levels"), r"(\w+) of your trained skills must be selected",
                       "how many trained skills come from the profession").group(1))
    known = arms.known(pack.system)
    crafts, schools = {}, {}
    choose = {"kin": _kin(book, chapter.find("Kin"), movement), "profession": _professions(book, chapter.find("Profession"), train, known, crafts, schools)}
    for name, label, options in (("craft", "Craft", crafts), ("school", "School of magic", schools)):
        if options:
            choose[name] = {"label": label, "options": options}
    choose["age"] = _ages(book, chapter.find("Age"))
    creation["choose"] = choose
    pack.item("creation_numbers", "Attributes, ratings and skill levels", "mechanic",
              [page for title in ("Attributes", "Derived Ratings", "Skills") for page in chapter.find(title).pages],
              [f"creation.toml:{key}" for key in ("attributes", "attribute_range", "key_swap", "trained_multiplier", "tracks", *(f"ratings.{name}" for name in ratings))])
    # A kin's movement is read from the movement table, and how many trained skills a profession gives from the skills' section: the items cite those pages too.
    pack.item("creation_kin", "Kin", "mechanic", [*chapter.find("Kin").pages, *chapter.find("Derived Ratings", "Movement").pages], ["creation.toml:choose.kin"])
    pack.item("creation_professions", "Professions", "mechanic", [*chapter.find("Profession").pages, *chapter.find("Skills", "Starting Skill Levels").pages],
              ["creation.toml:choose.profession", "creation.toml:choose.craft", "creation.toml:choose.school"])
    pack.item("creation_age", "Age", "mechanic", chapter.find("Age").pages, ["creation.toml:choose.age"])


def _numbers(chapter, scale):
    scores = chapter.find("Attributes", "Starting Scores")
    roll = find(scores, r"Roll (\d)D(\d+) and remove the worst die", "how attributes are rolled")
    find(chapter.find("Skills", "Starting Skill Levels"), r"equal to twice the base chance", "what a trained skill starts at")
    tracks = {track: find(chapter.find("Derived Ratings", title), rf"{track.upper()} is equal to your (\w+)", f"what {track.upper()} is").group(1).lower()
              for track, title in (("hp", "Hit Points (HP)"), ("wp", "Willpower Points (WP)"))}
    return {"attributes": f"{roll.group(1)}d{roll.group(2)}kh{int(roll.group(1)) - 1}", "attribute_range": scale, "key_swap": says(scores, r"swap two scores"),
            "trained_multiplier": 2, "tracks": tracks}


def _ratings(book, section, top):
    """({kin: movement}, {rating: how an attribute changes it}): the movement table gives each kin's and a step for each range of
    AGL (what isn't there changes nothing), the damage bonus table a die for each range of STR and AGL."""
    _, rows = grid.read(section.find("Movement", "Table: Movement").lines(own=True), book.glue)
    kin, steps, attribute = {}, [], None
    for cells in (row["cells"] for row in rows):
        found = re.match(r"([A-Z]{3}) (\d+)\s*[–-]\s*(\d+)$", cells[0])
        if found:
            attribute = found.group(1).lower()
            steps.append((int(found.group(2)), int(found.group(3)), int(re.sub(r"[–−]", "-", cells[1]))))
        else:
            kin[packs.slug(cells[0])] = int(cells[1])
    table, last = [], 0
    for low, high, change in steps:
        table += [[low - 1, 0]] if low > last + 1 else []
        table.append([high, change])
        last = high
    ratings = {"movement": {"label": "Movement", "attribute": attribute, "table": table}}
    header, rows = grid.read(section.find("Damage Bonus", "Table: Damage Bonus").lines(own=True), book.glue)
    bonus = []
    for cells in (row["cells"] for row in rows):
        bonus.append([top if cells[0].endswith("+") else int(re.split(r"[–-]", cells[0].lstrip("≤"))[-1]), "none" if cells[1] in ("—", "") else cells[1]])
    for attribute in (part.strip() for part in header[0].split("/")):
        ratings[f"damage_bonus_{attribute.lower()}"] = {"label": f"Damage bonus ({attribute})", "attribute": attribute.lower(), "table": bonus}
    return kin, ratings


def _kin(book, section, movement):
    options = {}
    table = dice.read(section.find("Introduction", "Table: Kin").lines(own=True), book.glue)
    for row in table["rows"]:
        kin, kin_id = section.find(row["text"]), packs.slug(row["text"])
        names = dice.read(kin.span(), book.glue)["rows"]
        if len(names) != 6 or kin_id not in movement:
            raise changed(kin, "can't find its six first names and its movement")
        options[kin_id] = {"range": [row["low"], row["high"]], "abilities": [s.title.removeprefix("Ability:").strip() for s in kin.children if s.title.startswith("Ability:")],
                           "ratings": {"movement": movement[kin_id]}, "names": [name["text"] for name in names]}
    return {"label": "Kin", "roll": dice.formula(table["faces"]), "options": options}


def _professions(book, section, train, known, crafts, schools):
    """Each profession from its page: the key attribute, the skills to choose six of, the heroic ability, and the gear table."""
    options = {}
    table = dice.read(section.find("Introduction", "Table: Profession").lines(own=True), book.glue)
    for row in table["rows"]:
        page = section.find(row["text"])
        facts = dict(found.groups() for found in (re.match(r"✦\s*([^:]+):\s*(.*)$", para) for para in page.text(own=True).split("\n\n")) if found)
        option = {"range": [row["low"], row["high"]], "key": facts["Key Attribute"].lower()}
        if "Skills" in facts:
            option |= {"skills": _list(facts["Skills"]), "train": train}
        abilities = [] if re.search(r"don.t get a starting heroic ability", facts["Heroic Ability"]) else _list(facts["Heroic Ability"])
        if len(abilities) > 1:
            option["then"] = "craft"
            for ability in abilities:
                crafts[packs.slug(ability.removeprefix("Master "))] = {"label": ability.removeprefix("Master "), "abilities": [ability]}
        elif abilities:
            option["abilities"] = abilities
        for label, skills in facts.items():
            if label.endswith(" Skills"):
                listed = _list(skills)
                schools[packs.slug(label.removesuffix(" Skills"))] = {"label": listed[0], "always": [listed[0]], "skills": listed, "train": train}
                option["then"] = "school"
        magic = next((child for child in page.children if child.title.startswith("Sidebar:") and "newly created" in child.text(own=True)), None)
        start = re.search(r"newly created mage.*?choose (\w+) rank (\d+) spells and (\w+) magic tricks", " ".join(magic.text(own=True).split())) if magic else None
        if start:
            option["spells"] = {"count": count(start.group(1)), "rank": int(start.group(2)), "tricks": count(start.group(3))}
        kits, gear = _kits([row["text"] for row in dice.read(page.find("Table: Gear").lines(own=True), book.glue)["rows"]], known)
        options[packs.slug(row["text"])] = {**option, "kits": kits, "gear": gear}
    return {"label": "Profession", "roll": dice.formula(table["faces"]), "options": options}


def _list(text):
    """"A, B or C" as a list."""
    return [part.strip() for part in re.split(r",\s*|\s+or\s+", text) if part.strip()]


def _kits(texts, known):
    """(kits, gear) from the sentences of a gear table, one for each set. A slot is one part of a sentence, with an alternative
    for each thing it offers ("broadsword/battle axe" is two); what every set holds alone is `gear`, the rest is the kits."""
    sets = [[[_item(alternative, known) for alternative in part.split("/")] for part in text.split(",")] for text in texts]
    common = set.intersection(*({tuple(slot[0]) for slot in kit if len(slot) == 1} for kit in sets))
    shared = lambda slot: len(slot) == 1 and tuple(slot[0]) in common
    variants = [[[item for alternative in choice for item in alternative] for choice in product(*[slot for slot in kit if not shared(slot)])] for kit in sets]
    size = math.lcm(*(len(set_) for set_ in variants))
    return [kit for set_ in variants for _ in range(size // len(set_)) for kit in set_], [item for slot in sets[0] if shared(slot) for item in slot[0]]


def _item(text, known):
    """The things one alternative of a gear set names: a weapon or a piece of armor by the name of its entry, dice in braces
    (`D8 food rations` is `{1d8} food rations`), and what the book counts out ("two daggers")."""
    text = text.strip()
    counted = re.match(r"(two|three|four|five)\s+(.+?)s?$", text, re.I)
    if counted:
        return _item(counted.group(2), known) * count(counted.group(1))
    entry = arms.find(known, text)
    text = ids.label(entry) if entry else re.sub(r"\b(\d*)D(\d+)\b", lambda found: f"{{{found.group(1) or 1}d{found.group(2)}}}", text)
    return [text[:1].upper() + text[1:]]


def _ages(book, section):
    """Young, adult, old: a range of the D6, what each changes of the attributes ("STR, AGL, and CON -2, INT and WIL +1") and how
    many of the trained skills are the player's own (the six from the profession come first: "6+2")."""
    options = {}
    table = dice.read(section.find("Table: Effects of Age").lines(own=True), book.glue)
    for row in table["rows"]:
        name, skills, attributes = row["cells"]
        changes = {attribute.lower(): int(re.sub(r"[–−]", "-", change))
                   for names, change in re.findall(r"([A-Z]{3}(?:,? (?:and )?[A-Z]{3})*) ([+–−-]\d+)", attributes) for attribute in re.findall(r"[A-Z]{3}", names)}
        options[packs.slug(name)] = {"range": [row["low"], row["high"]], **({"attributes": changes} if changes else {}), "extra": int(skills.split("+")[1])}
    return {"label": "Age", "roll": dice.formula(table["faces"]), "options": options}
