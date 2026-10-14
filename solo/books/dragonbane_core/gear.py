"""Chapter 6, Gear: every price table as gear.toml, and the weapon and armor rows as the
system's [weapons] and [armor].

The weapon tables give each weapon's grip, STR requirement, range, damage, durability and
features; the book says which skill each weapon is used with in prose (the skills' own
entries), and the skill says which attribute adds its damage bonus.
"""

import re

from ... import packs
from .. import grid

# The skill a weapon uses, by the words in its name, first match wins. The book says in each
# skill's entry which weapons it covers, and gives a shield and a halberd none: a shield parries
# with any STR-based melee skill and this uses BRAWLING; a halberd is a long piercing weapon and
# goes with the spears.
WEAPON_SKILLS = [
    ("crossbow", "crossbows"), ("bow", "bows"), ("sling", "slings"), ("shield", "brawling"),
    ("sword|scimitar", "swords"), ("axe", "axes"), ("hammer|mace|club|flail|morningstar|blunt object", "hammers"),
    ("knife|dagger", "knives"), ("spear|lance|trident|halberd", "spears"), ("staff", "staves"),
]
# How the engine names what the book's Features column says.
_FEATURES = {"can_be_thrown": "thrown"}
# A grip as a table may write it: "1H", "2H", "1-handed", "Two-handed", "1 H".
_GRIP = re.compile(r"^(1|2|one|two)[\s-]*h(?:and(?:ed)?)?$", re.I)
_COINS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twenty": 20, "fifty": 50, "hundred": 100}


def build(pack):
    book = pack.book
    skills = _weapon_skills(book)
    pack.gear = {"money": {"coins": _coins(book)}, "gear": {}}
    weapons = pack.system.setdefault("weapons", {})
    armor = pack.system.setdefault("armor", {})
    for section in (s for s in book.find("6. Gear").children if s.title.startswith("Table:")):
        title = section.title.removeprefix("Table:").strip()
        header, rows = grid.read(section.lines(own=True), book.glue)
        columns = {name.lower(): at for at, name in enumerate(header)}
        worn = "armor rating" in columns
        refs = ["system.toml:armor"] if worn else []
        for row in rows:
            cells = grid.Cells(section, header, row)
            name = row["cells"][0]
            weapon = "grip" in columns and _grip(cells["grip"]) is not None
            if name == "Unarmed":
                pack.facts["unarmed"] = {"damage": _dice(cells["damage"])}
                continue
            item_id = _id(_adjective_first(name) if weapon else _armor_name(name) if worn else re.sub(r"\s*\([^)]*\)", "", name))
            entry = _entry(name, title.capitalize(), cells, row["page"])
            if weapon:
                weapons[item_id] = _weapon(name, cells, skills)
                refs.append(f"system.toml:weapons.{item_id}")
            elif worn:
                armor[item_id] = cells.number("armor rating")
                if _banes(cells["effect"]):
                    entry["banes"] = _banes(cells["effect"])
            pack.gear["gear"][item_id] = entry
            refs.append(f"gear.toml:gear.{item_id}")
        pack.item(f"gear_{_id(title)}", title, "gear", section.pages, refs)
    pack.item("gear_coins", "Coins", "mechanic", book.find("2. Your Player Character", "Gear", "Sidebar: Coins").pages, ["gear.toml:money"])


def _id(text):
    return packs.slug(text.replace("&", "and"))


def _adjective_first(name):
    """"Crossbow, Light" is the light crossbow, as a profession's kit names it."""
    noun, _, adjective = name.partition(", ")
    return f"{adjective} {noun}" if adjective else noun


def _armor_name(name):
    """Leather and studded leather are armor as a kit says it ("Leather armor"); a chainmail, a
    plate armor, a helmet already is."""
    return name if re.search(r"armor|mail|helm", name, re.I) else f"{name} armor"


def _entry(name, category, cells, page):
    entry = {"name": name, "category": category}
    price, note = _price(cells.get("cost", "—"))
    entry["price"] = price
    if cells.get("supply", "—") != "—" and cells.get("supply"):
        entry["supply"] = cells["supply"].lower()
    weight = cells.get("weight")
    if weight:
        entry["weight"] = 0 if weight == "—" else _number(weight)
    said = cells.get("effect") or cells.get("features") or cells.get("comment") or ""
    said = "" if said == "—" else said
    entry["note"] = " ".join(part for part in (note, said) if part)
    entry["source"] = f"p. {page}"
    return {key: value for key, value in entry.items() if value not in ("", None)}


def _price(cost):
    """(price, note): "5 silver" as it is; "2 gold/day" is 2 gold per day; a price with more to it
    ("3 gold × dose", made up) or none ("—") is "varies", and the note says what the book gave."""
    amount = re.match(r"^((?:\d+ (?:gold|silver|copper)\s*)+)(.*)$", cost)
    rest = amount.group(2).strip() if amount else cost
    if amount and not rest:
        return amount.group(1).strip(), ""
    elif amount and rest.startswith("/"):
        return amount.group(1).strip(), f"Per {rest[1:].strip()}."
    elif amount:
        return "varies", f"Price: {cost}."
    else:
        return "varies", "The book prints no price." if cost in ("—", "") else f"Price: {cost}."


def _number(text):
    if "/" in text:
        top, bottom = text.split("/")
        return int(top) / int(bottom)
    return int(text)


def _weapon(name, cells, skills):
    features = [_FEATURES.get(packs.slug(f), packs.slug(f)) for f in re.split(r",\s*", cells["features"]) if f and f != "—"]
    skill = next((skill for words, skill in WEAPON_SKILLS if re.search(words, name, re.I)), None)
    spec = {"skill": skill, "damage": _dice(cells["damage"])}
    if "no damage bonus" not in cells["features"].lower() and skills.get(skill):
        spec["bonus"] = skills[skill]
    spec["grip"] = _grip(cells["grip"])
    if cells["str"] != "—":
        spec["str"] = cells.number("str")
    spec["range"] = _range(cells["range"])
    if cells["durability"] != "—":
        spec["durability"] = cells.number("durability")
    if features:
        spec["features"] = features
    if "cannot be used for parrying" in cells["features"].lower() or "requires quiver" in cells["features"].lower() or name in ("Sling",):
        spec["parry"] = False
    if "requires quiver" in cells["features"].lower() or name == "Sling":
        spec["ranged"] = True
    return spec


def _grip(text):
    """How many hands a weapon takes, from its grip cell; None for a cell that gives no grip."""
    found = _GRIP.match(text.strip())
    return None if found is None else 1 if found.group(1).lower() in ("1", "one") else 2


def _dice(text):
    """"D8" is 1d8, as the engine and the rest of the pack write it."""
    return re.sub(r"^D", "1d", text.strip()).lower()


def _range(text):
    """A number of meters, or STR (a thrown weapon reaches as many meters as the hero's STR) or STR×2."""
    if text.isdigit():
        return int(text)
    return re.sub(r"\s", "", text.lower().replace("×", "*"))


def _banes(effect):
    """The skills an armor or a helmet puts a bane on (in a made-up cell, "Bane on ACROBATICS and SWIMMING rolls."), and
    "ranged_attack" for all ranged attacks."""
    found = re.match(r"Bane on (.+?)(?: rolls)?\.?$", effect)
    if not found:
        return []
    banes = [packs.slug(word) for word in re.split(r",\s*(?:and\s+)?|\s+and\s+", found.group(1)) if word.isupper()]
    return banes + (["ranged_attack"] if "ranged attacks" in effect else [])


def _weapon_skills(book):
    """{skill: attribute} for the weapon skills, from the entries the book gives them ("Axes (STR):")."""
    found = {}
    for child in book.find("3. Skills", "The Core Skills", "Weapon Skills").children:
        said = re.match(r"^[^:(]+\((STR|AGL)\)", child.text(own=True).split("\n\n", 1)[-1])
        if said:
            found[packs.slug(child.title)] = said.group(1).lower()
    return found


def _coins(book):
    """{coin: worth in the smallest}, from the coins sidebar (a made-up one: "Five tin coins equal one copper")."""
    text = book.find("2. Your Player Character", "Gear", "Sidebar: Coins").text(own=True).lower()
    ratios = {small: (_COINS[n], big) for n, small, big in re.findall(r"(\w+) (\w+) coins equal one (\w+)", text) if n in _COINS}
    coins = {small: 1 for small in ratios if small not in {big for _, big in ratios.values()}}
    while any(small in coins and big not in coins for small, (_, big) in ratios.items()):
        for small, (times, big) in ratios.items():
            if small in coins and big not in coins:
                coins[big] = coins[small] * times
    return dict(sorted(coins.items(), key=lambda coin: -coin[1]))
