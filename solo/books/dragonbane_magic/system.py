"""What the Book of Magic adds to the rules besides spells: a skill for each new school (secondary skills based on INT, like the core's three, except harmonism,
which is rolled as PERFORMANCE), the way a mage starts in each (its list of suitable skills), and the alchemist's ingredients."""

import re

from ... import packs
from .. import grid, pages
from ..read import count, find
from ..dragonbane_core import gear
from . import schools


def build(pack):
    book = pack.book
    preface = book.find("Preface", "New Schools of Magic")
    attribute = find(preface, r"secondary skills based on (\w+)", "the attribute the new schools of magic are based on").group(1).lower()
    harmonism = find(preface, r"harmonism isn.t a skill in itself.*?uses the skill level in (\w+)", "what harmonism is rolled as").group(1).lower()
    skills, options, starts = {}, {}, []
    for chapter in schools.chapters(book):
        school = schools.skill(chapter)
        if school != "general":
            skills[school] = {"attribute": "cha", "untrained": False, "uses": harmonism} if school == "harmonism" else {"attribute": attribute, "untrained": False}
        option = _start(pack, chapter, school)
        if option:
            options[option[0]] = option[1]
        starts += [page for section in chapter.subtree() if section.title in ("Sidebar: Starting Skills", "Sidebar: Starting Harmonists") for page in section.pages]
    pack.system["skills"] = skills
    pack.creation["choose"] = {"school": {"options": options}}
    ingredients = _ingredients(pack, book.find("11. Alchemy"))
    pack.item("schools_skills", "The schools of magic as skills and how a mage starts in each", "mechanic", [*starts, *preface.pages],
              [f"system.toml:skills.{school}" for school in skills] + ["creation.toml:choose.school"])
    if ingredients:
        pack.item("alchemy_ingredients", "Alchemical ingredients", "gear", ingredients[0], [f"gear.toml:gear.{item}" for item in ingredients[1]])


def _start(pack, chapter, school):
    """(id, option) for a mage who starts in this school: the book lists skills suited to "newly created animists" (the one the option is named for), six to be
    trained, the school's own among them; None for a school with no such list (harmonism is for bards, dracomancy is learned in play)."""
    sidebar = next((s for s in chapter.subtree() if s.title == "Sidebar: Starting Skills"), None)
    if sidebar is None:
        return None
    text = " ".join(sidebar.text(own=True).split())
    found = re.search(r"(?:newly created|beginner) ([a-z]+)\b.*?may be chosen as the (\w+) trained skills.*?\):\s*(.*?)\.(?:\s|$)", text)
    if not found:
        pack.note(f"{pages.clean(chapter.title)}, {sidebar.title!r} (p. {sidebar.page}): can't read which skills a new mage of the school starts with, "
                  "so a hero can't start in it")
        return None
    agent = re.sub(r"(?<=ch)es$|(?<=[^s])s$", "", found.group(1))
    listed = [item.strip() for item in found.group(3).split(",")]
    own = next((item for item in listed if packs.slug(item) == school), listed[0])
    return agent, {"label": own, "always": [own], "skills": listed, "train": count(found.group(2), sidebar)}


def _ingredients(pack, chapter):
    """(pages, [ids]) of the alchemist's ingredients: a table of what each costs a dose and how easy it is to get, as gear."""
    section = next((s for s in chapter.subtree() if s.title == "Sidebar: Magic Tricks"), None)
    if section is None:
        pack.note(f"{pages.clean(chapter.title)}: no table of ingredients where the importer looks for it (a sidebar on magic tricks), so they aren't gear")
        return None
    _, rows = grid.read(section.lines(own=True), pack.book.glue)
    pack.gear.setdefault("gear", {})
    made = []
    for row in rows:
        name, cost, supply = row["cells"][:3]
        item = packs.slug(name)
        pack.gear["gear"][item] = gear._entry(name, "Alchemical ingredients", {"cost": cost, "supply": supply, "comment": "Price per dose."}, row["page"])
        made.append(item)
    return section.pages, made
