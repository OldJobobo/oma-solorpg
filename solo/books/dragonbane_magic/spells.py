"""The Book of Magic's spells as spells/<id>.toml (solo/books/spelllist.py): each school's spells by rank, its magic tricks (a list of "Name: what it does") and,
for alchemy, its recipes. A school's skill is the skill of the school's name; general magic is cast with any school the hero knows.
"""

import re

from ... import packs
from .. import pages, spelllist
from . import schools


def build(pack):
    book = pack.book
    for chapter in schools.chapters(book):
        school = schools.skill(chapter)
        made = [_write(pack, name, spelllist.trick(school, name, page)) for name, page in _tricks(pack, chapter)]
        listed = next((child for child in chapter.children if child.title in ("Spells", "Recipes")), None)
        for section in _spells(listed):
            made.append(_write(pack, section.title, spelllist.spell(book, school, section)))
        if made:
            pack.item(f"spells_{school}", f"{pages.clean(chapter.title)}: spells, tricks and recipes", "spell", chapter.pages, [f"spells/{spell}" for spell in made])


def _write(pack, title, spell):
    pack.toml(f"spells/{packs.slug(title)}.toml", spell)
    return packs.slug(title)


def _spells(listed):
    """The spells under a list: by rank ("Rank 1" and the spells under it), or, when the school has no ranks to sort them by (dracomancy), the list's own."""
    found = []
    for child in (listed.children if listed else []):
        if child.title.startswith("Rank "):
            found += [spell for spell in child.children if not spell.title.startswith(("Chart:", "Sidebar:"))]
        elif not child.title.startswith(("Chart:", "Sidebar:")):
            found.append(child)
    return found


def _tricks(pack, chapter):
    """(name, page) of a school's magic tricks: the paragraphs of its tricks section that begin "Name:", up to the first that doesn't (a chart of spells follows),
    which the pack's notes say."""
    section = next((s for s in chapter.subtree() if s.title == "Magic Tricks"), None)
    found = []
    for paragraph in (section.text(own=True).split("\n\n")[1:] if section else []):
        trick = re.match(r"([A-Z][A-Za-z’' /&-]{1,40}): \S", paragraph)
        if not trick:
            pack.note(f"{pages.clean(chapter.title)}, magic tricks (p. {section.page}): read up to a paragraph that isn't a trick's \"Name: what it does\" "
                      f"({' '.join(paragraph.split()[:6])} ...); the rest of the section isn't read as tricks")
            break
        found.append((trick.group(1), section.page))
    return found
