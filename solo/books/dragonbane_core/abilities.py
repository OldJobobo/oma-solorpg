"""Chapter 3's heroic abilities, as [abilities.<id>] in system.toml: what each costs, the skill level it asks for and, for the ones the engine
runs, what they do. Each ability's page has a "Requirement" and a "Willpower Points" line and then what it does; the engine's keys are read from
the words the book uses for the effect, and the abilities that need the GM's judgment have none (the GM reads their page).
"""

import re

from ... import packs
from ..read import count, roll

# What "Any ... skill 12" asks for: the engine's name for the group of skills.
_KINDS = {"any melee weapon skill": "melee", "any weapon skill": "weapon", "any str-based melee weapon skill": "str_melee", "any magic school": "magic"}
# The phrases that say what an ability does, and what the engine calls it.
_EXTRA = [(r"deals an (?:extra|additional) (D\d+) damage", {}), (r"unarmed attack increases by one (D\d+)", {"weapon": "unarmed"}),
          (r"inflicts (D\d+) additional points of damage", {"grip": 2, "melee": True})]


def build(pack):
    book = pack.book
    section = book.find("3. Skills", "Heroic Abilities")
    skills = {packs.slug(s.title) for s in book.find("3. Skills", "The Core Skills").subtree()}
    abilities = {}
    for ability in section.children:
        facts = dict(found.groups() for found in (re.match(r"✦\s*([^:]+):\s*(.*)$", para) for para in ability.text(own=True).split("\n\n")) if found)
        text = " ".join(para for para in ability.text(own=True).split("\n\n")[1:] if not para.startswith("✦"))
        spec = {"name": ability.title}
        pay = facts.get("Willpower Points", "—")
        if pay.isdigit():
            spec["pay"] = {"wp": int(pay)}
        elif pay.lower() == "varies":
            spec["pay"] = "varies"
        need = _requires(facts.get("Requirement", "—"), skills)
        if need:
            spec["requires"] = need
        abilities[packs.slug(ability.title)] = {**spec, **_effects(text)}
    pack.system["abilities"] = abilities
    pack.item("abilities_heroic", "Heroic abilities", "ability", section.pages, ["system.toml:abilities"],
              note="What each costs and asks for is read from its page; the ones the engine runs have their effect in words the recipe knows, the rest are for the GM.")


def _requires(text, skills):
    """The skill level an ability asks for: {kind, level} for a group of skills ("Any melee weapon skill 9", made up), {skills, level} for
    named ones ("Knives, Slings, or Staves 7")."""
    found = re.match(r"(.+?)\s+(\d+)$", text.strip())
    if not found:
        return None
    words, level = found.group(1), int(found.group(2))
    if words.lower() in _KINDS:
        return {"kind": _KINDS[words.lower()], "level": level}
    names = [packs.slug(name) for name in re.split(r",\s*(?:or\s+)?|\s+or\s+", words)]
    # The book says "Swim" where the skill is SWIMMING: a name that starts a skill's is that skill.
    return {"skills": [next((skill for skill in sorted(skills) if skill == name or skill.startswith(name)), name) for name in names], "level": level}


def _effects(text):
    """What the engine runs of an ability, by the words the book uses for it."""
    effects = {}
    raised = re.search(r"(max HP|maximum number of Willpower Points)[^.]*?increase[sd]? by (\d+)", text)
    if raised:
        effects["max"] = {"hp" if "HP" in raised.group(1) else "wp": int(raised.group(2))}
        effects.update({"stack": True} if re.search(r"multiple times, without limit", text) else {})
    for pattern, more in _EXTRA:
        extra = re.search(pattern, text)
        if extra:
            effects["extra_damage"] = roll(extra.group(1))
            effects.update(more)
    if "extra_damage" in effects and re.search(r"aimed at a monster", text):
        effects["against"] = "monster"
    drawn = re.search(r"draw (\w+) cards instead of one", text)
    if drawn:
        effects["initiative_pick"] = count(drawn.group(1))
    if re.search(r"retain your initiative card", text):
        effects["initiative_keep"] = True
    for how, word in (("parry", "parry"), ("dodge", "dodge")):
        if re.search(rf"attempt to {word} an attack .*? without consuming your action", text):
            effects["reaction"] = how
    healed = re.search(r"heal an extra (D\d+) HP.*?(stretch|shift|round) rest", text)
    if healed:
        effects.update({"heal": roll(healed.group(1)), "rest": healed.group(2)})
    if re.search(r"shield to roll with a boon", text):
        effects.update({"boon": "parry", "weapon": "shield"})
        effects.update({"unparryable": True} if re.search(r"parry physical monster attacks", text) else {})
    if re.search(r"boon to your BUSHCRAFT roll.*?right direction", text):
        effects["boon"] = "journey"
    return effects
