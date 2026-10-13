"""Chapter 7, the bestiary, as bestiary/<id>.toml and the roll table each monster's attacks are; and the people of chapter 8's table of
typical NPCs. Four kinds of entry: a monster (ferocity, a stat block and a table of attacks), the folk who aren't monsters (goblins, orcs,
skeletons: a stat block each and an attack of their own), a common animal (a row) and a typical NPC (a row).

What the engine can run of a monster's special rules is read from the words the book uses for them (it mends so many HP a turn, takes half
damage, is immune to all but some kinds); everything the book says stays in `description` for the GM.
"""

import re

from ... import packs
from ...sections import paragraphs
from ...tomlwrite import Inline
from .. import dice, grid
from ..read import changed, roll
from . import arms, ids

_STAT = re.compile(r"^(?:Ferocity|Movement|Mov\.|Armor|HP)\b")
_NUMBERS = {"ferocity": r"Ferocity: (\d+)", "size": r"Size: (\w+)", "movement": r"Mov(?:ement|\.): (\d+)", "armor": r"Armor: (—|\d+|Same as armor)", "hp": r"HP: (\d+)"}
_FIELDS = re.compile(r"(Movement|Mov\.|Damage Bonus(?: [A-Z]{3})?|HP|WP|Typical Armor|Skills|Spells|Abilities|Typical Weapons?):\s*")
_WEAPON = re.compile(r"([A-Za-z][A-Za-z ]*?)\s*\(skill level (\d+), damage (\d*D\d+)\)")
_DAMAGE = re.compile(r"(\d*D\d+)\s+(?:points of\s+)?(?:(slashing|piercing|bludgeoning)\s+)?damage(?:,?\s+plus\s+(\d*D\d+))?", re.I)
_THROWN = re.compile(r"(\d*D\d+) meters.{0,200}?(?:same|equal)(?: amount of)?\s+(?:(slashing|piercing|bludgeoning)\s+)?damage", re.I | re.S)


def build(pack):
    book = pack.book
    known = arms.known(pack.system)
    for section in book.find("7. Bestiary").children:
        blocks = [child for child in section.children if child.title.startswith("Statblock")]
        if section.title == "Common Animals":
            _animals(pack, section)
        elif any(child.title == "Statblock" for child in blocks):
            _monster(pack, section, known)
        elif blocks:
            _folk(pack, section, blocks)
    _typical(pack, book.find("8. Adventures", "Non-Player Characters", "Table: Typical NPCs"), known)


def _monster(pack, section, known):
    """A monster: the numbers of its stat block, what the book says below them, and its table of attacks."""
    book, system = pack.book, pack.system
    lines = section.find("Statblock").lines(own=True)
    flat = re.sub(r"\s+", " ", re.sub("\u00ad", "", " ".join(line["text"] for line in lines)))
    found = {key: re.search(pattern, flat) for key, pattern in _NUMBERS.items()}
    if not (found["hp"] and found["ferocity"] and found["movement"] and found["armor"] and found["size"]):
        raise changed(section, "can't read its stat block")
    entries = _entries(book, [line for line in lines if not _STAT.match(line["text"].strip())])
    gear = [arms.find(known, item) for entry in entries if entry.startswith("Typical Gear:") for item in entry.partition(":")[2].split(",")]
    weapon = next((system["weapons"][name]["damage"] for name in gear if name in system["weapons"]), None)
    armor = found["armor"].group(1)
    stats = {"hp": int(found["hp"].group(1)), "armor": sum(system["armor"].get(name, 0) for name in gear) if armor == "Same as armor" else int(armor) if armor.isdigit() else 0,
             "ferocity": int(found["ferocity"].group(1)), "movement": int(found["movement"].group(1)), **_rules(entries)}
    attacks = section.find("Monster Attacks")
    monster_id, name = packs.slug(section.title), ids.sentence(section.title)
    table_id = f"{monster_id}_attacks"
    blows, tables = _attacks(pack, attacks, table_id, f"{name} attacks", weapon)
    damaging = [blow["text"] for blow in blows if "damage" in blow]
    if damaging and all(re.search(r"heals the same amount of HP", text) for text in damaging):
        stats["drain"] = True
    size = found["size"].group(1)
    per = re.findall(r"(?:Ferocity|HP): \d+/(\w+)", flat)
    description = " ".join([f"Size: {size}.", *([f"Ferocity and HP are for each {per[0]}."] if per else []), *entries])
    carries = any(entry.startswith("Weapons:") for entry in entries) or weapon is not None
    entry = {"name": name, "role": f"A {size.lower()} monster", "description": description, "attacks": table_id, **({"parries": True} if carries else {}),
             "source": f"p. {section.page}", "stats": stats}
    pack.toml(f"bestiary/{monster_id}.toml", entry)
    pages = [*section.pages, *(pack.book.find("6. Gear", "Table: Armor & Helmets").pages if armor == "Same as armor" else []),
             *(pack.book.find("6. Gear", "Table: Melee Weapons").pages if weapon else [])]
    pack.item(f"bestiary_{monster_id}", name, "creature", pages, [f"bestiary/{monster_id}", *(f"tables/{table}" for table in tables)])


def _entries(book, lines):
    """What a stat block says below its numbers: an entry to a paragraph, each beginning at the margin and set in after that."""
    return [entry for entry in paragraphs(lines, book.glue, hanging=True).split("\n\n") if entry]


def _rules(entries):
    """What the engine runs of a monster's special rules, by the book's own words for them."""
    stats = {}
    for label, _, text in (entry.partition(":") for entry in entries):
        regeneration = re.search(r"(\d*D\d+) HP on each of its turns", text)
        if label == "Regeneration" and regeneration:
            stats["regenerate"] = roll(regeneration.group(1))
        elif label == "Resistance" and re.search(r"hal(?:f|ved)", text):
            stats["resist"] = list(dict.fromkeys(re.findall(r"slashing|piercing|bludgeoning", text))) or ["physical"]
        elif label == "Immunity" and re.search(r"immune to all damage except", text):
            stats["immune_to"] = ["physical"]
    return stats


def _attacks(pack, section, table_id, name, weapon):
    """The table of a monster's attacks, and the tables its attacks roll on after them: ([blows], [table ids])."""
    book = pack.book
    lines = section.lines(own=True)
    table = dice.read(lines, book.glue)
    made, blows = [table_id], []
    for row in table["rows"]:
        blow = _blow(row["text"], weapon)
        roll_on = re.search(r"Roll (D\d+):$", row["text"])
        if roll_on:
            sub_id = f"{table_id.removesuffix('_attacks')}_{packs.slug(row['text'].split('!')[0])}s"
            mark = min(line["x0"] for line in lines if re.fullmatch(r"\d+", line["text"].strip()))
            nested = dice.read([line for line in lines if line["x0"] > mark + 15 and line["size"] <= 9.3], book.glue, sides=dice.faces(roll_on.group(1)))
            pack.toml(f"tables/{sub_id}.toml", {"name": ids.label(sub_id), "formula": dice.formula(nested["faces"]), "source": f"p. {section.page}",
                                                "results": [Inline({"range": [found["low"], found["high"]], "text": found["text"]}) for found in nested["rows"]]})
            blow["then"] = sub_id
            made.append(sub_id)
        blows.append({"range": [row["low"], row["high"]], "text": row["text"], **blow})
    pack.toml(f"tables/{table_id}.toml", {"name": name, "formula": dice.formula(table["faces"]), "source": f"p. {section.page}", "results": [Inline(blow) for blow in blows]})
    return blows, made


def _blow(text, weapon):
    """What the engine runs of one monster attack: the damage it does and of what kind, whether it can be parried or dodged, and whether armor counts."""
    blow = {}
    damage = _damage(text, weapon)
    if damage:
        blow["damage"], kind = damage
        blow.update({"kind": kind.lower()} if kind else {})
        blow.update({"parry": True} if re.search(r"can be (?:dodged or )?parried", text) else {})
    blow.update({"defend": False} if re.search(r"cannot be dodged", text) else {})
    blow.update({"armor": False} if re.search(r"armor has no effect", text, re.I) else {})
    return blow


def _damage(text, weapon):
    """(dice, kind) of an attack's damage: stated (made up: "3D4 slashing damage", "2D6, plus D4"), the distance a victim is thrown when the attack does the
    same amount of damage, or the monster's weapon's, more than it or twice its dice. None for an attack that does none."""
    found = _DAMAGE.search(text)
    if found:
        return roll(found.group(1)) + (f"+{roll(found.group(3))}" if found.group(3) else ""), found.group(2)
    found = _THROWN.search(text)
    if found:
        return roll(found.group(1)), found.group(2)
    extra = re.search(r"weapon damage plus an extra (\d*D\d+)", text, re.I)
    if weapon and extra:
        return f"{weapon}+{roll(extra.group(1))}", None
    elif weapon and re.search(r"weapon damage", text, re.I):
        return weapon, None
    elif weapon and re.search(r"twice the weapon.s normal number of dice", text, re.I):
        return f"{weapon}+{weapon}", None
    return None


def _folk(pack, section, blocks):
    """The folk who aren't monsters: a stat block each (a scout, a warrior), with what the book says about all of them after."""
    book = pack.book
    shared = next((child for child in section.children if child.title == "Abilities"), None)
    rules = _entries(book, shared.lines(own=True)) if shared else []
    made = []
    for block in blocks:
        variant = block.title.removeprefix("Statblock:").strip()
        fields = _fields(block.lines(own=True))
        name = ids.sentence(f"{section.title} {variant}")
        weapons = [(label.strip().capitalize(), int(skill), roll(damage)) for label, skill, damage in _WEAPON.findall(fields.get("Typical Weapon", fields.get("Typical Weapons", "")))]
        bonus = re.search(r"\+(\d*D\d+)", fields.get("Damage Bonus STR", fields.get("Damage Bonus", "")))
        armor = re.search(r"\((\d+)\)", fields.get("Typical Armor", ""))
        stats = {"hp": int(fields["HP"]), "armor": int(armor.group(1)) if armor else 0, "movement": int(fields.get("Movement", fields.get("Mov.", 0))), **_rules(rules)}
        said = [*rules, *(f"{label}: {fields[label]}." for label in ("Typical Weapon", "Typical Weapons", "Abilities", "Spells") if label in fields),
                *([f"WP {fields['WP']}."] if "WP" in fields else []), *([f"Damage bonus {bonus.group(0)}."] if bonus else [])]
        entry = {"name": name, "role": f"A {section.title.lower()} {variant.lower()}", "description": " ".join(said), "source": f"p. {block.page}"}
        if weapons:
            label, skill, damage = weapons[0]
            entry["attack"] = Inline({"label": label, "value": skill, "damage": damage, **({"bonus": roll(bonus.group(1))} if bonus else {})})
        entry["stats"] = stats
        entry["skills"] = _skills(fields.get("Skills", ""))
        pack.toml(f"bestiary/{packs.slug(name)}.toml", entry)
        made.append(f"bestiary/{packs.slug(name)}")
    pack.item(f"bestiary_{packs.slug(section.title)}", section.title, "creature", section.pages, made)


def _fields(lines):
    """{label: value} of a stat block set as "Movement: 10  HP: 9  Skills: Awareness 10 ...", on a line each or several to a line."""
    flat = re.sub(r"\s+", " ", re.sub("\u00ad", "", " ".join(line["text"] for line in lines)))
    found = list(_FIELDS.finditer(flat))
    return {match.group(1): flat[match.end():next.start() if next else len(flat)].strip()
            for match, next in zip(found, [*found[1:], None])}


def _skills(text):
    return {packs.slug(name): int(level) for name, level in re.findall(r"([A-Za-z][A-Za-z &]*?) (\d+)", text)}


def _animals(pack, section):
    """The common animals: a row each, with its attack and skills in words (a made-up one: "Bite (skill level 9, damage D8)")."""
    book = pack.book
    _, rows = grid.read(section.lines(), book.glue)
    made = []
    for row in rows:
        name, movement, hp, attack, skills = grid.cells(section, row, 5)
        weapon = _WEAPON.match(attack)
        if weapon is None:
            raise changed(section, f"can't read the attack of {name} on p. {row['page']} ({attack!r})")
        label, skill, damage = weapon.groups()
        animal = packs.slug(name)
        pack.toml(f"bestiary/{animal}.toml", {"name": ids.sentence(name), "role": "A common animal", "description": "Common animal.",
                                              "attack": Inline({"label": label, "value": int(skill), "damage": roll(damage)}), "source": f"p. {row['page']}",
                                              "stats": {"hp": int(hp), "armor": 0, "movement": int(movement)}, "skills": _skills(skills)})
        made.append(f"bestiary/{animal}")
    pack.item("bestiary_common_animals", "Common Animals", "creature", section.pages, made)


def _typical(pack, section, known):
    """The typical NPCs: a row each. Their gear says their attack and armor, by the gear tables."""
    book, system = pack.book, pack.system
    _, rows = grid.read(section.lines(own=True), book.glue)
    made = []
    for row in rows:
        kind, skills, abilities, bonus, hp, wp, gear = grid.cells(section, row, 7)
        boss = "(Boss)" in kind
        name = re.sub(r"\s*\(Boss\)", "", kind).strip()
        skills = {packs.slug(found.group(1)): int(found.group(2)) for part in row["parts"][1] for found in [re.match(r"(.+?)\s+(\d+)$", part.strip())] if found}
        phrases = [phrase.strip() for phrase in gear.split(",")]
        found = [arms.find(known, phrase) for phrase in phrases]
        for phrase in phrases:
            if phrase.lower() in arms.SAME:
                pack.note(f"{name}: the book says {phrase!r}, the gear tables have {arms.SAME[phrase.lower()]!r}: used")
        weapon = next((system["weapons"][item] | {"id": item} for item in found if item in system["weapons"]), None)
        bonus_dice = re.search(r"\+(\d*D\d+)", bonus)
        said = [f"Gear: {gear}.", *([f"Damage bonus: {bonus}."] if bonus_dice else []), *([f"Heroic abilities: {', '.join(row['parts'][2])}."] if abilities != "—" else []),
                *([f"WP {wp}."] if wp.isdigit() else [])]
        entry = {"name": name, "role": f"A boss: {name.lower()}" if boss else f"A typical {name.lower()}", "description": " ".join(said), "source": f"p. {row['page']}"}
        if weapon:
            skill = weapon["skill"] if weapon["skill"] in skills else max(skills, key=skills.get)
            entry["attack"] = Inline({"label": ids.label(weapon["id"]), "skill": skill, "damage": weapon["damage"], **({"bonus": roll(bonus_dice.group(1))} if bonus_dice else {})})
        entry["stats"] = {"hp": int(hp), "armor": sum(system["armor"].get(item, 0) for item in found)}
        entry["skills"] = skills
        pack.toml(f"bestiary/{packs.slug(name)}.toml", entry)
        made.append(f"bestiary/{packs.slug(name)}")
    pack.item("bestiary_typical_npcs", "Typical NPCs", "creature", [*section.pages, *book.find("6. Gear", "Table: Armor & Helmets").pages, *book.find("6. Gear", "Table: Melee Weapons").pages,
                                                                                  *book.find("6. Gear", "Table: Ranged Weapons").pages], made)
