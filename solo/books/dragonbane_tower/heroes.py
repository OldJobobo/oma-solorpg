"""The pre-generated heroes of the booklet: a character sheet each, filled in by hand-lettered values over the printed labels, as characters/<id>.toml.

What the sheet says is read by where it is: a value stands under or beside its label (an attribute under its three letters, a skill's number to the left of its
name), the abilities and spells in a list down the left, the weapons in rows under their header. A hero the adventure itself names as a person in one of its places is a replacement the story hands out: `replacement = true`, and the same id as their NPC.
"""

import re

from ... import SoloError, magic, packs
from ..dragonbane_core import ids
from ..read import changed
from ...tomlwrite import Inline

_ATTRIBUTES = ("STR", "CON", "AGL", "INT", "WIL", "CHA")
# Where a value stands from its label (dx, dy: the value's left edge and top from the label's), as (low, high) for each.
_UNDER = ((-15, 15), (-2, 14))
_BESIDE = ((20, 140), (-14, 6))
_BELOW = ((-5, 60), (-2, 24))
_ABOVE = ((-5, 70), (-14, 14))
_LABELS = {"STR": _UNDER, "CON": _UNDER, "AGL": _UNDER, "INT": _UNDER, "WIL": _UNDER, "CHA": _UNDER, "DAMAGE BON. STR": _BESIDE, "DAMAGE BON. AGL": _BESIDE, "MOVEMENT": _BESIDE,
           "ENCUMBRANCE LIMIT": _BELOW, "HIT POINTS": _BELOW, "WILLPOWER POINTS": _BELOW, "SILVER": ((20, 120), (-14, 6)), "GOLD": ((20, 120), (-14, 6)), "COPPER": ((20, 120), (-14, 6))}


def build(pack):
    book = pack.book
    section = book.find("Pre-Generated Characters")
    for child in section.children:
        _hero(pack, child, book.by_page[child.page] + book.by_page.get(child.page + 1, []))


def _near(fills, label, window):
    """The text of the hand-lettered value in a window (dx, dy) from a label, nearest first."""
    (xa, xb), (ya, yb) = window
    found = [fill for fill in fills if xa <= fill["x0"] - label["x0"] <= xb and ya <= fill["y0"] - label["y0"] <= yb]
    return min(found, key=lambda fill: abs(fill["x0"] - label["x0"]) + abs(fill["y0"] - label["y0"]))["text"].strip() if found else ""


def _hero(pack, section, lines):
    system = pack.system_pack
    fills = [line for line in lines if "aveat" in line["font"]]
    labels = {line["text"].strip(): line for line in lines if line["size"] < 8 and line["text"].strip() in (*_LABELS, "KIN", "AGE", "PROFESSION", "WEAKNESS")}
    found = {name: _near(fills, labels[name], window) for name, window in _LABELS.items() if name in labels}
    if len(labels) != len(_LABELS) + 4 or not all(found[name] for name in _ATTRIBUTES):
        raise changed(section, "can't read the character sheet")
    attributes = {name.lower(): int(found[name]) for name in _ATTRIBUTES}
    hero_id = packs.slug(section.title)
    info = {key.lower(): _near(fills, labels[key], ((-6, 6), (-2, 14))) for key in ("KIN", "PROFESSION", "AGE")}
    weakness = " ".join(fill["text"].strip() for fill in sorted(fills, key=lambda fill: fill["y0"]) if abs(fill["x0"] - labels["WEAKNESS"]["x0"]) <= 6 and 0 <= fill["y0"] - labels["WEAKNESS"]["y0"] <= 36)
    info = {**info, **({"weakness": weakness} if weakness else {})}
    skills = _skills(pack, lines, fills, attributes)
    listed = [fill["text"].strip() for fill in sorted(fills, key=lambda fill: fill["y0"]) if 28 <= fill["x0"] <= 40 and 270 <= fill["y0"] <= 500]
    spells = [name for name in listed if _spell(system, name)]
    abilities = [name for name in listed if name not in spells]
    carried = [fill["text"].strip() for fill in sorted(fills, key=lambda fill: (fill["y0"], fill["x0"])) if 458 <= fill["x0"] <= 470 and (270 <= fill["y0"] <= 430 or 496 <= fill["y0"] <= 600)]
    weapons = _weapons(lines, fills)
    armor = [fill for fill in fills if 85 <= fill["x0"] <= 100 and 618 <= fill["y0"] <= 630 and fill["size"] < 14.5]
    worn = [_armor(system, fill["text"]) for fill in armor]
    coins = [f"{found[name]} {name.lower()}" for name in ("GOLD", "SILVER", "COPPER") if found.get(name)]
    sheet = {"name": section.title, "conditions": [], "items": [*(name.lower() for name in weapons), *worn, *(name.lower() for name in carried), *coins], "abilities": abilities}
    if spells:
        sheet["spells"] = spells
        sheet["prepared"] = [name for name in spells if not _trick(system, name)]
    sheet["info"] = info
    sheet["attributes"] = attributes
    sheet["skills"] = skills
    sheet["tracks"] = {"hp": int(found["HIT POINTS"]), "wp": int(found["WILLPOWER POINTS"])}
    sheet["ratings"] = {"Movement": int(found["MOVEMENT"]), "Damage bonus (STR)": _bonus(found["DAMAGE BON. STR"]), "Damage bonus (AGL)": _bonus(found["DAMAGE BON. AGL"])}
    if hero_id in pack.facts.get("npc_ids", ()):
        sheet = {**sheet, "replacement": True}
    pack.toml(f"characters/{hero_id}.toml", sheet)
    pack.item(f"hero_{hero_id}", section.title, "npc", [section.page, section.page + 1], [f"characters/{hero_id}"])


def _skills(pack, lines, fills, attributes):
    """The skills the hero is trained in: each printed name has its number beside it on the left, and the skills the hero has besides are lettered in under
    SECONDARY SKILLS. A skill whose number is its base chance is untrained, and left out."""
    system = pack.system_pack
    out = {}
    names = [line for line in lines if line["size"] < 9 and (215 <= line["x0"] <= 225 or 340 <= line["x0"] <= 355)]
    secondary = [fill for fill in fills if 340 <= fill["x0"] <= 355 and fill["y0"] >= 460]
    for line in [*names, *secondary]:
        found = re.match(r"([A-Za-z][A-Za-z &]*?)\s*\((STR|CON|AGL|INT|WIL|CHA)\)", line["text"].strip())
        if not found:
            continue
        value = next((fill for fill in fills if 14 <= line["x0"] - fill["x0"] <= 34 and abs((fill["y0"] + fill["y1"]) / 2 - (line["y0"] + line["y1"]) / 2) <= 7 and re.fullmatch(r"\d+", fill["text"].strip())), None)
        skill = packs.slug(found.group(1))
        if value and skill in system["skills"] and int(value["text"]) != packs.base_chance(system, attributes[found.group(2).lower()]):
            out[skill] = int(value["text"])
    return out


def _weapons(lines, fills):
    """The weapons in the rows under the header: the name in the first column."""
    header = next((line for line in lines if line["text"].strip() == "WEAPON / SHIELD"), None)
    return [fill["text"].strip() for fill in sorted(fills, key=lambda fill: fill["y0"]) if header and fill["x0"] <= 40 and fill["y0"] > header["y0"] and fill["size"] < 14.5]


def _armor(system, name):
    key = next((key for key in system["armor"] if key.startswith(packs.slug(name))), packs.slug(name))
    return ids.label(key).lower()


def _spell(system, name):
    try:
        magic.find(system, name)
        return True
    except SoloError:
        return False


def _trick(system, name):
    return bool(magic.find(system, name)[1].get("trick"))


def _bonus(text):
    """A damage bonus as the sheet's other heroes have it: "+D4", or "none" for a dash."""
    return f"+{text.upper()}" if re.fullmatch(r"D\d+", text, re.I) else "none"
