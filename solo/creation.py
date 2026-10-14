"""Characters: from a file, a pre-made hero, or the system's creation tables.

creation.toml (beside system.toml) holds a rulebook's creation tables as data. Attributes
are rolled first (or, for a game with a stat array like Ironsworn's, dealt out at random),
then each [choose.<table>] is picked by the player or rolled, and the chosen options change
attributes, train skills, grant abilities, ratings, gear and a name, and may lead to a
follow-up table (then = "school"). Rolling attributes first means a choice made after seeing
the numbers keeps them, and a seed rebuilds the same hero.
"""

import random
import re
from pathlib import Path

from . import SoloError, dice, packs
from .packs import slug

_ROLL_IN_TEXT = re.compile(r"\{([^}]+)\}")


def character(system, spec=None, name=None, seed=None, adventure=None):
    """The raw sheet for `spec`: a .toml/.json file, a pre-made hero's id (the adventure's
    own first, then the system's), or words naming creation options ("dwarf fighter",
    "random"). `name` renames whichever it is."""
    text = str(spec or "random").strip()
    premade = {**system["characters"], **((adventure or {}).get("characters") or {})}
    if Path(text).suffix in (".toml", ".json"):
        data = packs.load_data(Path(text).expanduser())
    elif slug(text) in premade:
        data = dict(premade[slug(text)])
    else:
        picks = [word for word in re.split(r"[\s,]+", text) if word and word.lower() != "random"]
        data = build(system, picks, random.Random(seed) if seed is not None else None)
    if name:
        data["name"] = name
    return data


def tables(system):
    """The creation tables as the panel offers them. `after` lists the options that lead
    to a follow-up table, so it is shown only once one of them is picked."""
    choose = system["creation"].get("choose", {})
    leads = {}
    for table in choose.values():
        for option_id, option in table.get("options", {}).items():
            if option.get("then"):
                leads.setdefault(option["then"], []).append(option_id)
    return [
        {
            "id": table_id,
            "label": table.get("label", table_id.capitalize()),
            "after": leads.get(table_id, []),
            "options": [{"id": oid, "label": _label(oid, option)} for oid, option in table.get("options", {}).items()],
        }
        for table_id, table in choose.items()
    ]


def build(system, picks=(), rng=None):
    """A new character from the creation tables. `picks` are option ids; every table
    without a pick is rolled."""
    recipe = system["creation"]
    choose = recipe.get("choose", {})
    if not choose and not recipe.get("attributes"):
        gaps = packs.missing(system)
        if gaps:
            # Only a game's names so far: a pre-made hero can't be played on them either, so the rules come first.
            raise SoloError(packs.missing_text(system, gaps) + ".")
        raise SoloError(f"{system['name']} has no creation tables: pick a pre-made hero or a character file.")
    rng = rng or random.SystemRandom()
    wanted = _match(choose, picks)
    rolled = _attributes(system, recipe, rng)
    chosen = _choose(choose, wanted, rng)
    options = [option for _, _, option in chosen]
    key = next((o["key"] for o in options if o.get("key")), None)
    if recipe.get("key_swap") and key in rolled:
        best = max(rolled, key=rolled.get)
        rolled[key], rolled[best] = rolled[best], rolled[key]
    bounds = recipe.get("attribute_range")
    attributes = {}
    for attribute, value in rolled.items():
        value += sum(o.get("attributes", {}).get(attribute, 0) for o in options)
        attributes[attribute] = max(bounds[0], min(bounds[1], value)) if bounds else value
    items = []
    for option in options:
        kits = option.get("kits", [])
        kit = kits[rng.randint(0, len(kits) - 1)] if kits else []
        items += [_ROLL_IN_TEXT.sub(lambda m: str(dice.roll(m.group(1), rng)["total"]), text) for text in kit + option.get("gear", [])]
    skills = _skills(system, attributes, options, rng)
    abilities = [ability for o in options for ability in o.get("abilities", [])] + _extra_abilities(system, recipe, options, rng)
    # An option's own names, else the pack's list for it ([names] in creation.toml, by option id).
    lists = [o.get("names") or recipe.get("names", {}).get(oid) for _, oid, o in chosen]
    names = next((n for n in lists if n), None) or recipe.get("names", {}).get("any") or ["The hero"]
    sheet = {
        "name": names[rng.randint(0, len(names) - 1)],
        "info": {table_id: _label(option_id, option) for table_id, option_id, option in chosen},
        "attributes": attributes,
        "skills": skills,
        # A track starts at an attribute's value (Dragonbane's HP is CON) or at a number (Ironsworn's health is 5),
        # and a heroic ability the hero starts with may raise it (Robust).
        "tracks": _raised(system, {track: attributes[start] if isinstance(start, str) else start for track, start in recipe.get("tracks", {}).items()}, abilities),
        "abilities": abilities,
        "ratings": _ratings(recipe, attributes, options),
        "items": items,
    }
    known, ready = _spells(system, options, attributes, rng)
    return {**sheet, **({"spells": known, "prepared": ready} if known else {})}


def _spells(system, options, attributes, rng):
    """(the spells a new mage knows, the ones held ready): a mage chooses so many spells of a rank and so many magic tricks (`spells = { count, rank, tricks }` on
    the profession), from their school and general magic. Picked last, so a seed never changes the rest of the hero; the spells are held ready as far as the
    hero can."""
    pick = next((o["spells"] for o in options if o.get("spells")), None)
    school = next((slug(o["always"][0]) for o in options if o.get("always")), None)
    if not (pick and school and system.get("spells")):
        return [], []
    own = {school, "general"}
    pool = lambda trick: [spell.get("name", sid) for sid, spell in system["spells"].items()
                          if spell.get("school") in own and bool(spell.get("trick")) == trick and (trick or spell.get("rank") == pick.get("rank", 1))]
    learned = _sample(pool(False), int(pick.get("count", 0)), rng)
    tricks = _sample(pool(True), int(pick.get("tricks", 0)), rng)
    limit = packs.base_chance(system, attributes.get(system.get("magic", {}).get("prepared", "int"), 0))
    return learned + tricks, learned[:limit]


def _raised(system, tracks, abilities):
    """The tracks with what the abilities the hero starts with add to them (an ability that can be taken
    again counts each time)."""
    for name in abilities:
        spec = next((spec for aid, spec in system.get("abilities", {}).items() if slug(name) in (aid, slug(spec.get("name", aid)))), {})
        for track, more in (spec.get("max") or {}).items():
            tracks[track] = tracks.get(track, 0) + int(more)
    return tracks


def _attributes(system, recipe, rng):
    """Each attribute's starting value: the recipe's dice rolled for each, or, given a list
    (Ironsworn's 3, 2, 2, 1, 1), those numbers dealt across the attributes in a random order."""
    spec = recipe.get("attributes", "3d6")
    if isinstance(spec, list):
        return dict(zip(system["attributes"], _sample(spec, len(spec), rng)))
    else:
        return {a: dice.roll(spec, rng)["total"] for a in system["attributes"]}


def _extra_abilities(system, recipe, options, rng):
    """More heroic abilities than the tables give: the solo hero starts with one more (the
    Dragonbane solo rules), picked from the ones that make a lone hero self-sufficient; a
    game that starts a hero with assets (Ironsworn: three) picks from all of them. Picked
    last, so it never changes the rest of a seeded hero."""
    extra = recipe.get("extra_abilities", {})
    held = {a for o in options for a in o.get("abilities", [])}
    every = extra.get("from") or [asset["name"] for asset in system.get("assets", {}).values()]
    choices = [a for a in every if a not in held]
    picked = []
    for _ in range(int(extra.get("count", 0))):
        if choices:
            picked.append(choices.pop(rng.randint(0, len(choices) - 1)))
    return picked


def _match(choose, picks):
    """Words to {table: option id}. Picking a follow-up option (animist) also picks the
    option that leads to its table (mage)."""
    wanted = {}
    for word in picks:
        key = slug(word)
        found = [table_id for table_id, table in choose.items() if key in table.get("options", {})]
        if len(found) == 1:
            wanted[found[0]] = key
        else:
            known = ", ".join(oid for table in choose.values() for oid in table.get("options", {}))
            raise SoloError(f"{word!r} isn't a creation choice; choose from: {known}")
    for table_id, table in choose.items():
        leading = [oid for oid, option in table.get("options", {}).items() if option.get("then") in wanted]
        if leading and table_id not in wanted:
            wanted[table_id] = leading[0]
    return wanted


def _choose(choose, wanted, rng):
    """[(table, option id, option)] in play order: each top-level table in file order,
    with a follow-up table right after the option that leads to it."""
    followups = {o["then"] for table in choose.values() for o in table.get("options", {}).values() if o.get("then")}
    queue = [table_id for table_id in choose if table_id not in followups]
    chosen = []
    while queue:
        table_id = queue.pop(0)
        table = choose[table_id]
        option_id = wanted.get(table_id) or _roll_option(table_id, table, rng)
        option = table["options"][option_id]
        chosen.append((table_id, option_id, option))
        if option.get("then"):
            queue.insert(0, option["then"])
    unused = [wanted[t] for t in wanted if t not in {table_id for table_id, _, _ in chosen}]
    if unused:
        raise SoloError(f"{', '.join(unused)} doesn't go with the other choices")
    else:
        return chosen


def _roll_option(table_id, table, rng):
    options = table.get("options", {})
    if table.get("roll"):
        total = dice.roll(table["roll"], rng)["total"]
        hit = next((oid for oid, o in options.items() if o["range"][0] <= total <= o["range"][1]), None)
        if hit is None:
            raise SoloError(f"creation table {table_id} has nothing for a roll of {total}")
        else:
            return hit
    else:
        ids = list(options)
        return ids[rng.randint(0, len(ids) - 1)]


def _skills(system, attributes, options, rng):
    """Every skill at its base chance; trained ones at base x trained_multiplier. Each
    option trains its `always` skills plus `train` in all from its `skills`; `extra`
    free picks prefer the option skills left over, then any skill that can be learned."""
    trained = []
    for option in options:
        always = [slug(s) for s in option.get("always", []) if slug(s) not in trained]
        pool = [slug(s) for s in option.get("skills", []) if slug(s) not in trained + always]
        trained += always + _sample(pool, option.get("train", 0) - len(always), rng)
    extra = sum(o.get("extra", 0) for o in options)
    leftovers = list(dict.fromkeys(slug(s) for o in options for s in o.get("skills", []) if slug(s) not in trained))
    picked = _sample(leftovers, extra, rng)
    others = [k for k, s in system["skills"].items() if s["untrained"] and k not in trained + picked]
    trained += picked + _sample(others, extra - len(picked), rng)
    multiplier = system["creation"].get("trained_multiplier", 1)
    skills = {}
    for key, skill in system["skills"].items():
        base = packs.base_chance(system, attributes.get(skill["attribute"], 0))
        if key in trained:
            skills[key] = {"value": base * multiplier, "trained": True}
        elif skill["untrained"]:
            skills[key] = {"value": base, "trained": False}
    return skills


def _ratings(recipe, attributes, options):
    """Values read off an attribute ([highest value, result] rows), added to any base an
    option gives under the same name (a kin's movement)."""
    ratings = {}
    for rating_id, spec in recipe.get("ratings", {}).items():
        value = attributes.get(spec["attribute"], 0)
        found = next((result for top, result in spec["table"] if value <= top), spec["table"][-1][1])
        base = sum(o.get("ratings", {}).get(rating_id, 0) for o in options)
        ratings[spec.get("label", rating_id)] = base + found if isinstance(found, int) else found
    return ratings


def _sample(items, count, rng):
    pool, picked = list(items), []
    while pool and len(picked) < count:
        picked.append(pool.pop(rng.randint(0, len(pool) - 1)))
    return picked


def _label(option_id, option):
    return option.get("label") or option_id.replace("_", " ").capitalize()
