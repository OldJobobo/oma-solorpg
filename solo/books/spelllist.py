"""A spell, a magic trick or an alchemical recipe as spells/<id>.toml, read from its page: its rank, what it asks for, how long it takes to cast, how far it
reaches and how long it lasts (the lines under its title), and, for the ones the engine can cast, what they do: the damage or healing, the foes it goes on to,
what a power level adds, how it can be avoided and what kind of damage it is.

A page names only what it has: an enchanting has a rank and a prerequisite, an alchemical recipe ingredients and a price. "Any school of magic" or "Any rank 5
spell" is no prerequisite the engine can check, and the page keeps the words.
"""

import re

from .. import packs
from .read import changed, roll

_DICE = r"(\d*D\d+)"


def facts(section):
    """({label: value} of the bullet lines of a section, the words under them)."""
    paragraphs = section.text(own=True).split("\n\n")
    found = dict(match.groups() for match in (re.match(r"✦\s*([^:]+):\s*(.*)$", para) for para in paragraphs) if match)
    return found, " ".join(para for para in paragraphs[1:] if not para.startswith("✦"))


def spell(book, school, section, skill=None):
    """The spell on a section's page. `school` is the skill it is cast with (or "general"); `skill` the one the prerequisite names, when that isn't the school's own."""
    found, text = facts(section)
    if "Rank" not in found:
        raise changed(section, "can't read its rank")
    entry = {"name": section.title, "school": school, "rank": int(found["Rank"])}
    prerequisite = _prerequisite(found.get("Prerequisite", ""))
    if prerequisite:
        entry["prerequisite"] = prerequisite
    if "Requirement" in found:
        entry["requirement"] = list(dict.fromkeys(re.findall(r"word|gesture|focus|ingredient|melody", found["Requirement"].lower())))
    if "Casting Time" in found:
        entry["casting_time"] = found["Casting Time"].lower()
    if "Range" in found:
        entry.update(_reach(found["Range"]))
    if "Duration" in found:
        entry["duration"] = found["Duration"].lower()
    for label in ("Ingredients", "Cost"):
        if label in found:
            entry[label.lower()] = found[label]
    entry["source"] = f"p. {section.page}"
    return {**entry, **_effects(section.title, text)}


def trick(school, name, page):
    return {"name": name, "school": school, "trick": True, "rank": 0, "source": f"p. {page}"}


def _prerequisite(text):
    """What a spell asks for first: nothing the engine checks for "Any school ..." or "Any rank 5 spell", else the school or the spells, one entry each ("A and B");
    "A or B" is one entry that is a list of either."""
    if not text or re.match(r"any\b", text, re.I):
        return []
    entries = [[packs.slug(option) for option in re.split(r"\s+or\s+", need)] for need in re.split(r"\s+and\s+", text)]
    return [entry[0] if len(entry) == 1 else entry for entry in entries]


def _reach(text):
    """{range, area}: meters ("30 meters", a kilometer is 1000), or touch or personal; "(sphere)" or "(cone)" is the area."""
    found = re.match(r"(\d+)\s+(meters?|kilometers?)(?:\s+\((sphere|cone)\))?$", text.strip(), re.I)
    if found:
        meters = int(found.group(1)) * (1000 if found.group(2).lower().startswith("kilo") else 1)
        return {"range": meters, **({"area": found.group(3).lower()} if found.group(3) else {})}
    return {"range": text.strip().lower()}


def _effects(title, text):
    """What the engine casts of a spell, by the words the book uses: damage or healing, the foes it goes on to, what a power level adds, how a foe can avoid it and
    what kind of damage it is."""
    effects = {}
    # Damage that is rolled: not a spell for objects, and not one that pushes (the push is the damage; against a swarm it rolls).
    damage = None if re.search(r"inanimate|pushed", text) else re.search(rf"(?:inflicts?|inflicting|suffers?|takes|deals) {_DICE} damage", text)
    heal = re.search(rf"heals? (?:a living creature )?for {_DICE} HP", text)
    if damage:
        effects["damage"] = roll(damage.group(1))
    elif heal:
        effects["heal"] = roll(heal.group(1))
    if damage and "continues to" in text and "Each power level" in text:
        effects["chain"] = [roll(dice) for dice in re.findall(_DICE, text[text.index("continues to"):text.index("Each power level")])]
    if effects:
        added = re.search(rf"(?:increases the damage by|heals an additional) {_DICE}", text)
        if re.search(r"dice rolled for damage by one", text):
            effects["per_level"] = {"dice": 1}
        elif added:
            effects["per_level"] = {"add": roll(added.group(1))}
    if damage:
        dodged = re.search(r"can be dodged or parried|can be dodged", text)
        effects["avoid"] = ["dodge", "parry"] if dodged and "parried" in dodged.group(0) else ["dodge"] if dodged else []
        effects["kind"] = "fire" if re.search(r"\bfire", f"{title} {text}", re.I) else "magic"
        if re.search(r"Armor and natural armor have no effect", text):
            effects["armor"] = False
    return effects
