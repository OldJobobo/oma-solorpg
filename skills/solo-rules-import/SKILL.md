---
name: solo-rules-import
description: Turn a tabletop RPG rulebook PDF the user owns (Dragonbane's core rules first, then Year Zero games or others) into a system pack the `solo` engine runs and the GM reads, verified page by page against the book. Use when the user wants to import, ingest or digest a rulebook, a bestiary, a spell book or a GM screen, build or correct a system pack from a book, add price lists, travel rules, monsters or tables from a book, or fix what `solo audit --system` reports.
---

# Importing a rulebook

You are compiling a book the user owns into data and pages. The engine runs the data (dice, rests, fights, tables, prices, monsters); the GM reads the pages (`solo rule <topic>`) for everything it rules on itself. Every number comes from a page of the book, and `solo audit` checks that it does.

Read `docs/INGESTION.md` (how books became packs before, and what went wrong) and `docs/PACK_FORMAT.md` (every key) before you start. The adventure side is the `solo-import` skill.

**Try the importers first.** Dragonbane's core rules, the Book of Magic, the three card decks and the solo booklet have importers (`solo import book <pdf or folder of PDFs>`, or `make dragonbane BOOKS=<folder>`): deterministic, no agent, audited against the pages. Use this skill for a printing they refuse (they say which section they couldn't find), for a book they don't know, and to fill a gap an importer reports; never write by hand what an importer already writes, and when you correct an importer's pack, change the importer (`solo/books/`, with a test) rather than the pack, or the next import loses your correction.

## Before you start: settle with the user

1. Which book, and where the PDF is. The PDF never goes through the chat.
2. Where the pack goes (`make rules` stops if an older, unlayered pack is at `~/Games/solo/systems/dragonbane`; move it aside, never over it, and keep it to compare with). For Dragonbane, `make rules` has set it up (see "Dragonbane: what the bundled pack leaves to the book" below): the rulebook goes in `~/Games/solo/systems/dragonbane-rulebook/`, laid over the bundled pack (`extends = "bundled:dragonbane"`), and `~/Games/solo/systems/dragonbane/` sits on top of it, the pack campaigns use, holding the solo rules when the user has that book. A game the repository doesn't have gets a full pack in `~/Games/solo/systems/<game>/`.
   Another book over the rulebook (a card deck, the Book of Magic, a bestiary) is a pack of its own, `~/Games/solo/systems/dragonbane-<id>/` with `extends = "dragonbane-rulebook"`, so it audits against its own pages; the top pack lists it: `extends = ["dragonbane-rulebook", "dragonbane-<id>", ...]` (later ones win). `make supplement ID=<id> BOOK=<pdf>` starts one.
3. What may be committed to the repository: nothing from the book, ever. This repository is public, and the publisher's license lets it use the game's terms but not carry a copy of its rules. The book's text, tables and numbers stay in `~/Games/solo`.

## The pipeline

### 1. Extract

```bash
sudo pacman -S python-pymupdf            # PyMuPDF on Omarchy; the README's Troubleshooting has other systems
solo extract ~/Books/<book>.pdf          # into ~/Games/solo/sources/<book>/
```

Check what it says and what it wrote:

- Pages with almost no text and a picture (`scanned` in the manifest): covers and chapter openers look like this and need nothing. Only if a page that should hold text is among them, run `ocrmypdf` on the PDF and extract again (`uvx ocrmypdf --force-ocr in.pdf out.pdf` needs no install beyond tesseract).
- A card deck is different: each card is a page, and its text layer holds some of the words (a card's name, a value) and misses others, because they are art. OCR of decorated cards misreads them ("sflver coms"), so read the pictures. Render each card's face (PyMuPDF `page.get_pixmap`, or a contact sheet of the card faces), read every value off it, and write what the PDF's text lacks into `picture/<page>.txt` beside `pages/` in the extract (a new extract leaves that folder alone). The audit reads it after the page's own text and lists the pages it came from: tell the user to look at those pages themselves, since the pack is then checked against your reading. Keep the contact sheet in the extract for them to look at.
- `toc.json` from the PDF's outline, or guessed from font sizes (then check it against the contents page).
- `manifest.json`: `running` lists the headers and footers taken out of the text; `labels` maps PDF pages to printed ones (`labels_from` says whether from the PDF or its footers). Cite PDF pages everywhere; use `labels` to follow the book's own "see page 42".
- `chapters/` is what you read, a chapter at a time. `tables/` has each table found, as Markdown and as a picture of its page. When a table's columns come out scrambled, the picture is the truth (open the PNG and read it).
- What the extract gets wrong in a typeset book: the drop cap of a chapter opener is lost ("he adventurer"), a sidebar lands in the middle of a sentence on a two-column page, and a heading can end up under the wrong entry. Read every opener's first words, and expect to cut sidebars out by line number.

### 2. Start the pack and its inventory

```bash
mkdir -p ~/Games/solo/systems/dragonbane-rulebook
printf 'format = 1\nextends = "bundled:dragonbane"\n' > ~/Games/solo/systems/dragonbane-rulebook/system.toml
solo inventory ~/Games/solo/systems/dragonbane-rulebook --extract ~/Games/solo/sources/<book>
```

`make rules BOOK=<pdf>` in the repository runs steps 1 and 2 (and the solo booklet's, with `SOLO_BOOK=<pdf>`), then opens your agent on the rest. Check what it left before you begin: `solo inventory` refuses a pack that already has an inventory, so a second run picks up where the first stopped.

`solo inventory` writes `inventory.toml` and a file per chapter under `inventory/`: an item per section and per table found, each `todo` with its pages and a guessed kind. Every page with text is cited from the start. Your job is to turn each chapter's items into what the book really holds (merge, split, rename, fix kinds), and give each a status: `mapped` with `to`, `engine`, `skipped` or `house`, each of the last three with a `note`.

### 3. Read and map, a chapter at a time

Read the chapter from `chapters/`, then its inventory file. For each item, decide where it goes (the table below) and write it there. Keep the book's wording for anything the GM reads; keep numbers exact.

The scaffold's items are a first cut, and on a book with regular structure it is faster to write the inventory yourself from a script than to edit a hundred items: each item's `to` list comes from the files that exist (every ability's page, every spell of a school, every price of a category on its page), so nothing is left unclaimed, and what is left to judge is each item's pages, kind and note. Give each engine mechanic the book has and the engine doesn't its own `engine` item.

On a long book, you can give each chapter to its own agent. Each writes only its own files: its `inventory/<chapter>.toml`, the tables, rules pages and bestiary entries it creates, and `drafts/<chapter>.toml` for anything that goes into the shared files (`system.toml`, `gear.toml`, `creation.toml`). You merge the drafts. Ids are shared across the whole pack; `solo audit` reports an item id used twice.

### 4. Tables

```bash
solo import table ~/Games/solo/sources/<book>/tables/p0045-1.md --out <pack>/tables/fear.toml --name "Fear" --pages 45
sed -n '12,20p' ~/Games/solo/sources/<book>/pages/0045.txt | solo import table - --out <pack>/tables/fear.toml --pages 45
```

It reads a Markdown grid or roll lines ("2-3 Shaken", or the row number alone on its line with the text after it, which is how most books' text comes out), takes the dice from the header ("D6", "2D6", "D66") or the ranges, joins results that run onto a second line, and says when the ranges don't cover the dice. A number starts a row only if it is the next one and within the header's die, so "20 meters..." at the start of a wrapped line stays in its result. Slice the table's lines out of the page (a range of lines, or between two headings), pipe them in, and check the result against the page's picture.

Tables the text can't give you: two columns side by side, interleaved (`--sorted` style: read every row's number and text, then order by number), and tables of several columns that are really several tables (random NPCs, quests, journeys, sites: one die per column). Read those from the picture into a table per column, and let the first column's results roll the rest with `then` so one roll reads as the book's sentence. Then add what the engine runs: `damage` (with `defend`, `parry`, `armor`) on a monster's attack results, `roll` for a value written as `{value}`, `choices`, `then` for a table rolled next. Never retype a table by hand when this can read it.

### 5. What the book holds, and where it goes

| The book has | Put it in |
|---|---|
| Attributes, skills and their attributes, conditions and what they bane, tracks (HP, WP) | `system.toml`: `[attributes]`, `[skills]`, `[conditions]`, `[tracks]` |
| Boons and banes, the base chance of an untrained skill | `system.toml`: `untrained`; the page in `rules/` |
| Time units (round, stretch, shift, day) | `system.toml`: `[time]` in seconds |
| Pushing a roll, rests and what they heal, dying and death rolls, advancement | `system.toml`: `[push]`, `[rest.<id>]`, `[dying]`, `[advancement]` |
| Initiative, damage bonus, what a Dragon or Demon does in a fight, unarmed attacks | `system.toml`: `[combat]` |
| Weapons (skill, damage, what can parry) and armor | `system.toml`: `[weapons.<id>]`, `[armor]`; their prices go in `gear.toml` under the same ids |
| Coins and what they're worth | `gear.toml`: `[money] coins = { gold = 100, silver = 10, copper = 1 }` (worth in the smallest coin), `aliases` for abbreviations |
| Price lists: gear, clothing, food and lodging, services, animals, transport | `gear.toml`: `[gear.<id>]` with `name`, `category` (the book's heading), `price` as written, and `weight`, `supply`, `note` when the book gives them |
| Character creation: kin, profession, age, names, starting gear | `creation.toml` (docs/PACK_FORMAT.md). Hero names can stay the bundled pack's: a kin option without `names` draws from `[names]` in the bundled `creation.toml` under its id |
| Heroic abilities, kin abilities | Data the engine runs where it can (`[abilities.<id>]`: initiative cards, paying for a push); otherwise a rules page and an `engine` item |
| Spells and magic schools, their costs | A rules page per school (the GM runs them); an `engine` item for casting and WP |
| Monsters with stat blocks and attack tables | `bestiary/<id>.toml` (`name`, `role`, `[stats]` hp, armor, ferocity, immune; `attacks = "<table>"` or `[attack]`) and `tables/<id>_attacks.toml` |
| Journeys and travel: distance per shift by terrain, getting lost, weather, camping, food and sleep | A rules page with every number the GM needs to turn a journey into game time, plus the tables (weather, mishaps, encounters); an `engine` item if the user wants travel rolled by the engine |
| Fear, poison, disease, cold, falling, drowning, fire | A rules page each, with the book's numbers; the GM applies them with `solo check` and `solo wound hero` |
| Random tables of any kind (encounters, treasure, mishaps) | `tables/<id>.toml`, exact |
| Game master advice | `skill:solo-gm` if it changes how the GM should run solo play (tell the user), else `skipped` |
| Setting, lore, maps, fiction | A rules page if the GM needs it in play (a village's inn, the calendar), else `skipped` with why |
| Credits, index, contents, adverts | `skipped` |

The bundled pack has no numbers at all: every number in your pack comes from a page, and every section the bundled pack lists under `needs` must be in it before a campaign can start.

Names the engine matches by slug, so they must agree:

- A hero's item is a weapon or armor when its slug is a key of `[weapons]` or `[armor]`. Key them as the kits write them, adjective first (`small_shield`, `light_warhammer`, `light_crossbow`, `leather_armor`), give a shield the skill BRAWLING if the book names none for it, and check that every weapon and armor any kit hands out is a key.
- Top-level keys of `system.toml` (`untrained`, `needs`) go above the first `[table]`; written below one, they belong to it.
- A price the engine can't read (`2 gold x potency`, `2 gold/day`, a dash) is `price = "varies"`, or the amount without its unit, with the rest in the entry's `note`. A value the book derives without printing it (a power attack that rolls twice the weapon's dice) is written as the printed terms (`2d8+2d8`), so each is found on a cited page.
- A table the adventures name must have the id they use. From the private adventures that play on Dragonbane: the core rules' `fear`, a monster's attack table `<monster>_attacks` (`ghost_attacks`), and from the solo rules the tables `areas`, `inhabitants`, `location_details`, `treasure`, `harm` and `traps`, with `threats`, `search`, `scavenge`, `npc_attacks`, `demon_effects`, `dragon_effects`, `inspiration_action`, `inspiration_attribute`, `inspiration_thing` and `location_danger` for the sections named above (`tests/fixtures/house/tables` has the shapes). Random tables the core rules have follow the same habit: `<what>` or `<what>_<column>` (`severe_injuries`, `magical_mishaps`, `journey_mishaps`, `hunting`, `quest_hook`, `nicknames_<profession>`).

### Dragonbane: what the bundled pack leaves to the book

The bundled `packs/dragonbane` holds only names: `[attributes]`, `[conditions]`, `[tracks]`, `[skills]` and hero names. The engine refuses to start a campaign until the packs over it hold every key in its `needs` list, so these come from the rulebook, into `dragonbane-rulebook`:

| Key | From the rulebook |
|---|---|
| `untrained` | the base chance of an untrained skill, by attribute |
| `[time]` | round, stretch, shift in seconds |
| `[push]` | `cost = "condition"` |
| `[rest.round]`, `[rest.stretch]`, `[rest.shift]` | what each recovers and heals, how long it takes, how often |
| `[light.torch]` | how long a torch burns (optional, but the Book shows it) |
| `[dying]` | the death roll's attribute, successes and failures, what a rally restores |
| `[advancement]` | what marks a skill, the roll, the cap |
| `[combat]`, `[combat.damage_bonus]` | initiative cards, a Dragon on an attack, the evade skill, unarmed attacks, whether monster attacks can be parried, damage bonus by attribute |
| `[weapons.<id>]`, `[armor]` | every weapon's skill, damage, bonus attribute and whether it parries; armor and helmet ratings |
| `creation.toml` | the kin, profession (and its follow-ups), age tables, attributes roll and range, the key attribute swap, trained skills, `tracks`, `[ratings.*]` |

And from the solo rules, when the user has them, into the top `dragonbane` pack (each is optional; without them the engine's own likelihood oracle and random events run solo play):

| Key | From the solo rules |
|---|---|
| `[oracle]`, `[oracle.fortune]` | `chart = "fortune"`, `scene_checks = false`, the chart's `bands` and one list per column, `inspiration` naming its word tables |
| `[effects]` | the tables a Dragon or a Demon rolls outside a fight |
| `[threats]` | the counter's size, start, what advances it, the random threat table |
| `[search]`, `[scavenge]` | skill, table and time |
| `[npcs]`, `[npcs.templates.<id>]` | the NPC attack table and its role columns, the simple NPC templates |
| `[abilities.<id>]` | the lone hero's abilities the engine runs (`initiative`, `push`) |
| `creation.toml` `extra_abilities` | the extra heroic ability a lone hero starts with |
| `[rest.stretch] tend`, `[dying] self_rally`, `self_save` | healing alone and rallying alone |
| `tables/` | every table those name, and the booklet's others (harm, traps, areas, locations), exact |

A deck of cards (treasure, adventure, improvised weapons) is a book of its own, and its pack is one too (`make supplement ID=<id> BOOK=<pdf>`, laid over the rulebook and listed under the top pack's `extends`, the rulebook first). A deck of coins and finds is one table with a result to a card: `range = [n, n]`, `page = <its PDF page>` (the audit then reads that card against its own page, not the whole deck), `text` with `{value}` and `roll = "2d6x10"` for a value the card rolls, `choices` for a card that says "roll a D6: 1: dagger, 2: ...", a `then` for a card that sends you on. Cards that are one-off rules (improvised weapons) are a page each in `rules/`, plus an index page whose `Search:` holds the shared words; give each page only its own name, or a search for one card finds another. The rest of the solo booklet, and its adventure, is mapped as above: the adventure's missions are `skipped` here ("for the adventure pack") and built with the `solo-import` skill. `tests/fixtures/house` shows every one of these keys in use, with made-up values: read it for the shapes, never for the numbers.

### 6. Rules pages the GM can find

A rules page is `rules/<topic>.md`, one topic per page, titled with the book's heading. The line after the title lists the words a GM would look it up by:

```markdown
# Journeys
Search: travel, travel time, journey, distance, kilometers, getting lost, pathfinder

(the book's text for this topic, or your faithful summary with every number)
```

GMs search by what they need in the moment, not by the book's headings: "prices", "inn", "travel time", "how far", "fear", "poison", "bartering". Give every page the words of the questions it answers (a word of three letters or fewer has to match whole: "inn" is never "innate"). The GM reads one page at a time, so split a long chapter into pages of one topic each: a page for each heroic ability, skill and spell, and a page for each rule topic. Pages built from the book's text stay in the private pack.

For a regular list, write a throwaway script that slices the extract between headings: it saves the retyping that gets numbers wrong. It has to join a word broken by a soft hyphen at a line's end without a space, read a non-breaking space as a space in headings, know the few headings the book sets in mixed case, and not take a sentence's last word in capitals for a heading. Lift sidebars out by line number into pages of their own, write flattened tables in words (`Age table: 1-3 Young: ...`), and end every page with where it is from (`Source: ..., PDF p. 34 (printed 32)`). Then scan the pages for a paragraph that starts in lowercase: that is where a sentence was cut. Point every table's page at it (`The table is solo table fear (D8)`).

### 7. Check it

```bash
solo validate --system <pack>
solo audit --system <pack>
```

The audit fails until everything is accounted for, both ways:

- Every item is decided, and every `to` names something in the pack (or in the pack it extends).
- Everything the pack itself holds (each section of `system.toml`, `gear.toml` and `creation.toml`, each table, monster, character and rules page) is claimed by an item. A reference claims what it names and everything under it: `system.toml:weapons` claims every weapon.
- Every page of the book with text is cited by an item.
- What a mapped item points at is on its pages: every result of a table, word for word; every dice expression, stat and price in its data. A line under "Not on the cited pages" means the pack says something the book doesn't. Copy it from the page (or its picture) or cite the right pages. A difference on purpose is a `house` item with a note.

"By file" shows each chapter file's progress. "Needs engine work" is the list for the user.

### 8. Play on it

```bash
solo new red-tusk --dir /tmp/check        # a campaign on the new pack
solo -C /tmp/check rule prices            # and the other questions a GM asks: inn, travel time, fear, poison
solo -C /tmp/check rule bestiary
solo -C /tmp/check commit '{"npc": {"wolf_1": {"name": "Wolf", "monster": "wolf"}}}'
solo -C /tmp/check fight wolf_1
```

Every page should come up from a GM's words, and a monster should fight from its table. Also try a rest twice in a shift (the second is refused), a push, three death rolls, and a table that chains (`solo table quest_when`). Keep those as fixed-dice tests in the pack's own `checks/` (`<pack>/checks/test_*.py`, unittest, the book's page in each test's name): `make check` runs them after the audit, and they say when the engine or the pack changes a rule. Then lay the adventures you already have over the new rules (`solo validate --system dragonbane --adventure <folder>`): every table or key one names that the import named differently is a gap in this skill, and the ids above are how they are closed. For the risky rules, write a scenario in `tests/gm_eval/scenarios/` and run it with a real GM (tests/gm_eval/README.md).

### 9. Walk the user through it

What you mapped, chapter by chapter, with its pages; everything `house`, `skipped` and `engine`, with why; and anything you weren't sure how to read. They own the book. Engine work is theirs to decide: don't build it unasked, and never stand in for a missing mechanic with data that only looks right.

## Never

- Write a number or a table result from memory. If a page can't be read, say so and mark the item.
- Paste the book into the chat, or put its text, tables or numbers anywhere in the repository. The repository is public.
- Map an item to something the book doesn't say, to make the audit pass.
