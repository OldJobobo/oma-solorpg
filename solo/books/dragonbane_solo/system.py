"""The solo booklet's tools as the system pack's rules: the fortune chart, what a Dragon or a Demon adds outside a fight, the threat counter, what a
search and a scavenge take, the simple NPCs, the two heroic abilities of a lone hero and how a lone hero heals. Each number is read from the words that
give it; a section that doesn't say it any more fails by name.
"""

import re

from ... import packs
from .. import dice
from ..read import count, find, roll
from . import tables


def build(pack):
    book = pack.book
    root = book.find("Alone in Deepfall Breach")
    tools, surviving, missions, exploring = (root.find(title) for title in ("Core Solo Tools", "Surviving Solo Play", "Your Missions", "Exploration Tables"))
    system = pack.system
    system["oracle"] = _oracle(pack, tools.find("Fortune Chart"))
    system["effects"] = {"dragon": "dragon_effects", "demon": "demon_effects"}
    system["threats"] = _threats(missions.find("Mission Threats"))
    system["search"] = _search(exploring.find("Searching"))
    system["scavenge"] = _scavenge(exploring.find("Scavenging"))
    system["npcs"] = _npcs(pack, tools.find("Managing NPCs and Monsters"))
    system["abilities"], pack.creation["extra_abilities"] = _abilities(root)
    healing = surviving.find("Healing")
    system["rest"] = {"stretch": {"tend": _tend(healing)}}
    system["dying"] = _rescue(healing)
    pack.item("solo_tools", "The solo tools and rules", "mechanic",
              [page for section in (tools.find("Fortune Chart"), tools.find("Dragon and Demon Effects"), missions.find("Mission Threats"), exploring.find("Searching"), exploring.find("Scavenging"),
                                    tools.find("Managing NPCs and Monsters"), root.find("Your Solo Player Character"), healing) for page in section.pages],
              [f"system.toml:{key}" for key in ("oracle", "effects", "threats", "search", "scavenge", "npcs", *(f"abilities.{ability}" for ability in system["abilities"]), "rest.stretch", "dying")]
              + ["creation.toml:extra_abilities"])


def _oracle(pack, section):
    """The fortune chart: a die, the bands of it a row answers, and a column of answers for each kind of question."""
    found = tables.read(pack, section.find("Table: Fortune Chart"))
    kinds = [packs.slug(header) for header in found["headers"] if header and not dice.is_die(header)]
    chart = {"bands": [[row["low"], row["high"]] for row in found["rows"]]}
    for at, kind in enumerate(kinds):
        chart[kind] = [row["cells"][at] for row in found["rows"]]
    return {"chart": packs.slug(section.title.removesuffix(" Chart")), "scene_checks": False, "inspiration": pack.facts["inspiration"], packs.slug(section.title.removesuffix(" Chart")): chart}


def _threats(section):
    counter = find(section, r"D(\d+) as a counter, starting at (\w+)", "the die a threat is counted on")
    return {"segments": int(counter.group(1)), "start": count(counter.group(2)), "advance": ["activity"], "table": "threats"}


def _search(section):
    skill = find(section, r"roll ([A-Z][A-Z ]*[A-Z])\.", "the roll a search asks for").group(1)
    time = find(section, r"it requires a (stretch|shift|round)", "how long a search takes").group(1).lower()
    return {"skill": packs.slug(skill), "table": "search", "time": {time: 1}}


def _scavenge(section):
    again = find(section, r"in an area, it requires a (\w+)", "how long scavenging again takes").group(1).lower()
    return {"table": "scavenge", "again_time": {again: 1}}


def _npcs(pack, section):
    """The attack table's kinds of attacker, and the simple NPCs: a template each (attributes, movement, HP, armor, damage and skill levels)."""
    templates = {}
    sidebar = section.find("Sidebar: Simple NPC Templates")
    block = sidebar.text(own=True)
    for name, body in re.findall(r"\n\n([A-Z]+)\n\n(.*?)(?=\n\n[A-Z]+\n\n|\Z)", block, re.S):
        found = {key: re.search(pattern, body) for key, pattern in (("attributes", r"Attributes: (\d+)"), ("movement", r"Movement: (\d+)"), ("hp", r"HP: (\d+)"), ("armor", r"Armor: (\d+|—)"),
                                                                    ("damage", r"Damage: (\d*D\d+)"), ("skill", r"relevant skills (\d+)"), ("other", r"other (\d+)"))}
        templates[name.lower()] = {key: (roll(match.group(1)) if key == "damage" else 0 if match.group(1) == "—" else int(match.group(1))) for key, match in found.items() if match}
    if not templates:
        pack.note(f"{sidebar.title!r} (p. {sidebar.page}): no template the importer can read, so the pack has no simple NPCs")
    return {"attacks": "npc_attacks", "attackers": pack.facts["attackers"], "templates": templates}


def _abilities(root):
    """The two heroic abilities of a lone hero (a lone fighter draws two cards and keeps both; a lone adventurer pushes for willpower), and how many more a
    lone hero starts with, of which."""
    section = root.find("Your Solo Player Character")
    found, names = {}, []
    for ability in section.children:
        name = ability.title.partition(":")[2].strip()
        text = ability.text(own=True)
        spec = {"name": name}
        cards = re.search(r"draw (\w+) initiative cards and keep both", text)
        cost = re.search(r"Willpower Points: (\d+)", text)
        if cards:
            spec["initiative"] = count(cards.group(1))
        elif cost and re.search(r"push a roll without suffering a condition", text):
            spec["push"] = {"wp": int(cost.group(1))}
        found[packs.slug(name)] = spec
        names.append(name)
    more = find(root.find("Introduction"), r"you gain (\w+) additional heroic ability", "how many more heroic abilities a lone hero has")
    return found, {"count": count(more.group(1)), "from": names}


def _tend(section):
    """Tending your own wounds: a skill roll on a stretch rest that heals so much."""
    tend = find(section, r"([A-Z]+) roll to tend your own wounds.*?On a success, heal (\d*D\d+) HP", "how a lone hero tends their wounds")
    return {"skill": packs.slug(tend.group(1)), "recover": {"hp": roll(tend.group(2))}}


def _rescue(section):
    rally = find(section, r"rally yourself.*?without a bane to the ([A-Z]+) roll", "how a lone hero rallies")
    save = find(section, r"your own life with a ([A-Z]+) roll", "how a lone hero saves their life")
    return {"self_rally": {"skill": packs.slug(rally.group(1))}, "self_save": {"skill": packs.slug(save.group(1))}}
