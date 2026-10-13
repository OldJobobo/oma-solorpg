"""The numbers of the core rules, read into system.toml: what each roll, rest and fight runs on.

Each value is found in the section of the book that states it, by a pattern made of the game's own
terms (a dice expression, a count, a unit), and a section that doesn't say it any more fails by name:
that is a printing the recipe wasn't written for.
"""

import re

from ... import packs
from .. import grid
from ..read import changed, count, find, roll, says
from . import ids

_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def build(pack):
    book = pack.book
    skills, hazards, gear = book.find("2. Your Player Character"), book.find("4. Combat & Damage"), book.find("6. Gear")
    system = pack.system
    system["untrained"] = _ranges(book, skills.find("Skills", "Base Chance", "Table: Base Chance"))
    system["skills"] = _schools(book)
    system["time"] = _time(book)
    system["push"] = {"cost": "condition" if says(book.find("3. Skills", "Boons & Banes", "Optional Rule: Pushing Your Roll"), r"you suffer a condition") else "varies"}
    system["rest"] = _rests(book, hazards.find("Healing & Resting"))
    system["light"] = {"torch": _torch(book, gear)}
    system["dying"] = _dying(book, hazards.find("Damage", "Death"))
    system["advancement"] = _advancement(book, skills.find("Experience"))
    system["combat"] = _combat(book, pack, hazards)
    system["combat"]["damage_bonus"] = _damage_bonus(book, skills.find("Derived Ratings", "Damage Bonus", "Table: Damage Bonus"))
    system["encumbrance"] = _encumbrance(book, skills.find("Encumbrance"))
    system["journey"] = _journey(book, book.find("8. Adventures", "Journeys"))
    system["magic"] = _magic(book, book.find("5. Magic"))
    pack.item("system_numbers", "The numbers every roll and fight runs on", "mechanic",
              [p for section in (skills.find("Skills", "Base Chance"), skills.find("Experience"), skills.find("Encumbrance"), hazards.find("Healing & Resting"),
                                 hazards.find("Damage", "Death"), book.find("1. In the Oldest Times", "Introduction", "Table: Measuring Time"),
                                 book.find("8. Adventures", "Journeys"), book.find("5. Magic", "Casting Spells")) for p in section.pages],
              [f"system.toml:{key}" for key in ("untrained", "skills", "time", "push", "rest", "light", "dying", "advancement", "combat", "encumbrance", "journey", "magic")],
              note="Each number is read from the section that states it, by the recipe.")


def _ranges(book, section):
    """[[top, value], ...] from a table of ranges ("1–5", "16–18"): what the score reaches, and what it gives."""
    _, rows = grid.read(section.lines(own=True), book.glue)
    return [[int(re.split(r"[–-]", cell[0])[-1].rstrip("+")), int(cell[1])] for cell in (row["cells"] for row in rows)]


def _damage_bonus(book, section):
    """The damage bonus by STR and AGL: up to 12 none, 13-16 a die, 17 and more a bigger one."""
    header, rows = grid.read(section.lines(own=True), book.glue)
    table = []
    for cells in (row["cells"] for row in rows):
        top = 99 if "+" in cells[0] else int(re.split(r"[–-]", cells[0].lstrip("≤"))[-1])
        table.append([top, "" if cells[1] in ("—", "") else roll(cells[1].lstrip("+"))])
    attributes = [packs.slug(part) for part in header[0].split("/")]
    return {attribute: table for attribute in attributes}


def _schools(book):
    """The schools of magic are skills the book bases on one attribute and nobody can try untrained (the skill list
    itself is the bundled names, which this corrects where the book says otherwise)."""
    schools = book.find("5. Magic", "Schools of Magic")
    attribute = find(schools.find("Introduction", "Skills"), r"trained skill \(based on (\w+)\)", "the attribute the schools of magic are based on").group(1).lower()
    return {packs.slug(s.title): {"attribute": attribute, "untrained": False} for s in schools.children if s.title not in ("Introduction", "General Magic")}


def _time(book):
    _, rows = grid.read(book.find("1. In the Oldest Times", "Introduction", "Table: Measuring Time").lines(own=True), book.glue)
    units = {}
    for cells in (row["cells"] for row in rows):
        found = re.match(r"(\d+)\s+(second|minute|hour|day)s?", cells[1])
        if found:
            units[packs.slug(cells[0])] = int(found.group(1)) * _SECONDS[found.group(2)]
    return units


def _rests(book, section):
    """The three rests: what each recovers (dice, or everything), how many conditions it heals, and once per what."""
    rests = {}
    for title in ("Round Rest", "Stretch Rest", "Shift Rest"):
        text, unit = section.find(title).text(own=True), title.split()[0].lower()
        if re.search(r"recover all your lost HP and WP", text, re.I):
            recover = {"hp": "max", "wp": "max"}
        else:
            recover = {track: roll(found.group(1)) for track, words in (("hp", r"HP"), ("wp", r"(?:WP|Willpower Points)"))
                       for found in [re.search(rf"(\d*D\d+)\s+{words}", text, re.I)] if found}
        rest = {"label": title.capitalize(), "recover": recover, "time": {unit: 1}}
        if re.search(r"heal all conditions", text, re.I):
            rest["heal"] = "all"
        elif re.search(r"heal a condition", text, re.I):
            rest["heal"] = 1
        if re.search(r"once per shift", text, re.I):
            rest["limit"] = "shift"
        rests[unit] = rest
    return rests


def _torch(book, gear):
    row = next((r["cells"] for r in grid.read(gear.find("Table: Light Sources").lines(own=True), book.glue)[1] if r["cells"][0] == "Torch"), None)
    found = re.search(r"burn(?:s)? for up to (?:a|one) (shift|stretch)", row[-1] if row else "", re.I)
    if not found:
        raise changed(gear.find("Table: Light Sources"), "can't find how long the torch burns")
    return {"label": "Torch", "item": "torch", "lasts": {found.group(1).lower(): 1}}


def _dying(book, section):
    death = section.find("Death Roll").text(own=True)
    found = find(section, r"roll against your (CON|STR|AGL|INT|WIL|CHA)", "the roll a dying hero makes", own=False)
    rally = re.search(r"(?:after )?(\w+) successful death rolls you recover (\d*D\d+) HP", death, re.I)
    fail = re.search(r"(?:after )?(\w+) failed death rolls", death, re.I)
    if not (rally and fail):
        raise changed(section.find("Death Roll"), "can't find the successes and failures a death roll counts")
    return {"track": "hp", "roll": found.group(1).lower(), "rally": count(rally.group(1)), "die": count(fail.group(1)), "recover": roll(rally.group(2))}


def _advancement(book, section):
    found = find(section, r"roll a (D\d+) for each of them.*?maximum of (\d+)", "the advancement roll and its cap")
    marks = find(section, r"rolled a (dragon) or (demon)", "what marks a skill for advancement")
    return {"mark_on": [marks.group(1).lower(), marks.group(2).lower()], "roll": roll(found.group(1)), "max": int(found.group(2))}


def _combat(book, pack, hazards):
    melee, parry = hazards.find("Melee Combat"), hazards.find("Melee Combat", "Parrying")
    initiative = find(hazards.find("Rounds & Initiative"), r"numbered 1 to (\d+)", "how many initiative cards there are")
    combat = {"initiative": int(initiative.group(1)), "evade": "evade", "track": "hp"}
    combat["dragon"] = "choice" if says(melee.find("Critical Hit"), r"choose one of the following") else "double"
    if says(parry.find("Rolling a Dragon when Parrying"), r"counterattack"):
        combat["parry_dragon"] = "counter"
    demon = {}
    for kind, title in (("melee", "Table: Demon Roll in Melee"), ("ranged", "Table: Demon Roll in Ranged Combat")):
        found = next((s for s in book.sections if s.title == title), None)
        if found:
            demon[kind] = ids.table(title)
    if demon:
        combat["demon"] = demon
    monsters = book.find("7. Bestiary", "Introduction")
    combat["monster_parry"] = not says(parry.find("Introduction", "Monsters"), r"monster attacks .{0,30}cannot be parried")
    if says(monsters.find("Monster Attacks", "Repeated Attacks"), r"never makes the same attack twice"):
        combat["monster_repeat"] = "next"
    combat["monster_defense"] = int(find(monsters.find("Fighting Monsters", "Dodging & Parrying"), r"default skill level of (\d+)", "the skill a monster dodges and parries at").group(1))
    combat["repair"] = "crafting" if says(parry.find("Introduction", "Durability"), r"repaired with a CRAFTING roll") else None
    combat = {key: value for key, value in combat.items() if value is not None}
    combat["unarmed"] = {"label": "Unarmed", "skill": "brawling", "damage": pack.facts["unarmed"]["damage"], "bonus": "str"}
    return combat


def _encumbrance(book, section):
    text = section.text()
    divisor = find(section, r"equal to (half|a third|a quarter) your (STR|CON|AGL)", "the carrying capacity")
    found = {"attribute": divisor.group(2).lower(), "divisor": {"half": 2, "a third": 3, "a quarter": 4}[divisor.group(1).lower()]}
    hand = re.search(r"up to (\w+) weapons at hand", text, re.I)
    coins = re.search(r"(\d+)\s*[–-]\s*\d+ coins count as one item", text, re.I)
    pack_size = re.search(r"A backpack increases your carrying capacity by (\d+)", text, re.I)
    if hand:
        found["at_hand"] = count(hand.group(1))
    if coins:
        found["coins"] = int(coins.group(1))
    if pack_size:
        found["carriers"] = {"backpack": int(pack_size.group(1))}
    return found


def _journey(book, section):
    travel = find(section, r"roughly (\d+) kilometers per shift on foot or roughly (\d+) kilometers on horseback", "how far a shift of travel goes")
    days = find(section, r"maximum of (\w+) shifts per day", "how many shifts a day a party travels")
    per_day = find(section, r"there are (\w+) shifts in a day", "how many shifts make a day")
    skill = find(section, r"must make a (\w+) roll every shift", "the pathfinder's skill")
    camp = section.find("Making Camp")
    journey = {"foot": int(travel.group(1)), "mounted": int(travel.group(2)), "shifts_per_day": count(per_day.group(1)), "travel_shifts": count(days.group(1)),
               "skill": packs.slug(skill.group(1)), "mishaps": ids.table("Table: Mishaps")}
    needs = re.search(r"without a (sleeping fur)", camp.text(), re.I)
    helps = re.search(r"A (tent) grants a boon", camp.text(), re.I)
    if needs and helps:
        journey["camp"] = {"skill": journey["skill"], "needs": packs.slug(needs.group(1)), "helps": packs.slug(helps.group(1))}
    return journey


def _magic(book, chapter):
    casting = chapter.find("Casting Spells")
    cost = find(casting, r"costs (\d+) WP per power level", "what a power level costs")
    power = find(casting.find("Power Level"), r"ranges from 1 to (\d+)", "how many power levels there are", own=False)
    tricks = find(casting, r"magic tricks always cost (\d+) WP", "what a magic trick costs")
    body = find(casting.find("Power Level", "Power from the Body"), r"die of your choice \(([^)]*)\)", "the dice power from the body is drawn with")
    below = find(casting.find("Power Level", "Power from the Body"), r"just (\w+) or zero WP left", "how few points it takes to draw power from the body")
    prepared = find(chapter.find("Spells", "Prepared Spells"), r"equal to your base chance for (INT|WIL|STR|AGL|CON|CHA)", "how many spells can be held prepared")
    learning = chapter.find("Learning Magic")
    trick_time = find(learning.find("Magic Tricks"), r"takes one (stretch|shift|round) to learn", "how long a magic trick takes to learn")
    dragon = casting.find("Failure, Dragons and Demons", "Rolling a Dragon")
    options = [option for option, words in (("double", r"doubled"), ("free", r"not cost any WP"), ("another", r"cast another spell")) if says(dragon, words)]
    mishap = next((ids.table(s.title) for s in casting.find("Failure, Dragons and Demons").subtree() if s.title.startswith("Table: Magical")), None)
    teacher = find(learning.find("Teachers"), r"roll against (INT), with a boon", "the roll a teacher's lesson asks for")
    grimoire = find(learning.find("Grimoires"), r"roll against (LANGUAGES)", "the roll a grimoire's lesson asks for")
    magic = {"cost": int(cost.group(1)), "max_power": int(power.group(1)), "trick_cost": int(tricks.group(1)), "track": "wp",
             "body": [roll(d) for d in re.findall(r"D\d+", body.group(1))], "body_below": count(below.group(1)), "prepared": prepared.group(1).lower(),
             "dragon": options, "trick_time": {trick_time.group(1).lower(): 1},
             "learn": {"teacher": {"roll": teacher.group(1).lower(), "boons": 1}, "grimoire": {"roll": packs.slug(grimoire.group(1)), "boons": 0}}}
    if mishap:
        magic["mishap"] = mishap
    return magic
