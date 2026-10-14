# Ingesting content

How books become packs the engine can run, what has been done so far, and what went wrong along the way. Written for the agent doing the next import, and for whoever writes an importer. The formats are in [PACK_FORMAT.md](PACK_FORMAT.md); the step-by-step skills are `skills/solo-import` (adventures) and `skills/solo-rules-import` (rulebooks).

Contents: [What imports have taught the engine](#what-imports-have-taught-the-engine) · [Books with an importer](#books-with-an-importer-solo-import-book) · [A game that ships: Ironsworn](#a-game-that-ships-ironsworn-from-datasworn) · [The process](#the-process) · [Mapping a book to the engine](#mapping-a-book-to-the-engine) · [Rules and system packs](#rules-and-system-packs) · [Lessons learned](#lessons-learned) · [Play-testing an ingestion](#play-testing-an-ingestion) · [Legal and privacy](#legal-and-privacy)

## What imports have taught the engine

Only The Red Tusk Hall, The Bell Under the Hill and Ironsworn's CC BY rules (below) ship here. Everything else below was imported from books the maintainer owns, into a private `~/Games/solo`, and each import left features in the engine that any book can use.

| Imported | What it forced into the engine |
|---|---|
| The Red Tusk Hall (original, `examples/red-tusk`) | The adventure format itself: scenes, clocks, branches, NPC profiles, voices |
| A tournament adventure with a real-time limit | Gated and timed exits, clock stages and `while`, round time, ferocity, immunity, monster parry/armor flags, `solo wound`, replacement heroes (`solo hero`), adventure `rules/` pages, `each_round` |
| A solo rules booklet | `[oracle]`, `[effects]`, `[threats]`, `[search]`, `[scavenge]`, `[npcs]`, `[abilities]`, `tend`, `self_rally`, `self_save`: a chart oracle, inspiration words, dragon/demon effects, threats, search and scavenge, simple NPCs with attacker roles, abilities for a lone hero, healing alone, ferocity as initiative cards |
| A solo campaign of missions from a hub | Missions in order, generated waypoints, adventure weapons, `defend resist`, safe scenes, kinds of foes |
| A deck of treasure cards | Dice multipliers (`2d6x10`) and self-resolving table results (`roll`, `choices`, `then`, `again`) |
| A campaign generated from a premise (no book) | Adventures in chapters, draft packs and chapters, rolls recorded and cited (`rolls.toml`, `solo campaign check`), people made up in play written into the pack without changing the campaign's replay |
| A core rulebook | Packs laid over packs, `gear.toml`, `bestiary/`, rules pages found by `Search:` words, running heads kept to the page edges, soft hyphens in the audit's page check, a guard against inventorying the extract itself |
| Ironsworn's moves, oracles and assets, from Datasworn's JSON (no book, and the one import whose result is committed) | A third mechanics family, `action-roll`: `solo act`, `burn` and `track`, momentum with a floor, a reset and impacts that lower them, progress tracks with ranks, an odds oracle, `moves/` and `assets/` in a pack, a stat array and constant tracks in creation, a `credit` on every generated rules page, and an importer that reads each object's license |
| The same rulebook, from `make rules` to `make check` (Dragonbane's second printing) | `solo import table` reading a row number alone on its line, a price read back beside its item's name in the audit, short search words matching whole, a pack's own `checks/` run by `make check`, a `format` on every pack |
| The solo booklet (v1.2) and three card decks (treasure, improvised weapons, adventure), each from its own PDF | `extends` as a list so each book is a pack that audits against its own pages, `make supplement`; `picture/` (what an agent reads off a card's art, which the audit reads and names); a table result's own `page`; the audit reading `choices`, numbers, an attack table's role columns and a dice multiplier (`2d6x10`) back; a lone hero's self-save recovering the rulebook's `[dying]` recovery |

## Books with an importer: `solo import book`

Dragonbane's own books have importers in `solo/books/`, so anyone with the PDFs gets the same packs without an agent: `make dragonbane BOOKS=~/Books/Dragonbane` (or `solo import book <pdf or folder>`). An importer ("recipe") is a Python module that knows one printing of one book:

- It recognises the book by its bookmarks (`Book.fingerprint()`: a hash of their levels and titles, the same for every copy of a printing whatever a shop stamped on it; a deck of cards has none and is told by its page count and first card). A book it doesn't know, or another printing, is named with its bookmark count and fingerprint (and a note when most of its pages have no text, as a scan's don't), the rest of the folder is still built, and the import ends with an error; that book goes to an agent and the skills below. A known book whose section reads differently fails by name, with the table and page; one the importer trips over some other way fails with what stopped it, and the rest of the folder is still built.
- It holds **where things are and how to read them**, never what they say. Each value is found in the section of the book that states it by a short pattern made of the game's own terms (a dice expression, a count, a unit); a section that no longer says it fails by name. No book text or number is in the repository: `tests/test_no_book_text.py` looks for any run of eight words of a book, and any stretch of a table's numbers, in any file: against the maintainer's committed fingerprints (`tests/fixtures/book_fingerprints.txt`, hashes keyed with a secret only the maintainer and CI hold) on every pull request, and against the extracts when the books are at hand (`SOLO_SOURCES`).
- It writes the same pack an agent would (`system.toml`, `creation.toml`, `gear.toml`, `tables/`, `bestiary/`, `spells/`, `rules/`) and an `inventory.toml` that says where each thing came from, so `solo audit` checks the result against the book's pages exactly as it checks an agent's work. `solo import book` runs that audit and fails if the pack and the book disagree.

How it reads, in the order it works (all of it stdlib; only `solo extract` needs PyMuPDF):

1. `solo extract` also writes `layout/NNNN.json` (every line of every page with its place, typeface, size, colour and the words' positions) and `outline.json` (the bookmarks with where they point).
2. `solo/sections.py` turns them into sections: a bookmark runs from where it points to the next, the bookmarks are a tree, and every line has an owner. Body text (the typeface most of the book is set in, or headings) goes to the last section that starts text; boxes, sidebars and table cells go to the last bookmark of any kind. Where the PDF's order of lines parts a heading from the words under it, or a table from its last row, geometry puts them back together. A big initial that is a drawing (so not in the text) is completed from the book's own vocabulary and said in a note; a hyphen at a line's end is joined or kept as the book writes the word elsewhere.
3. `solo/books/dice.py` and `grid.py` read tables from where their cells sit: a roll table's rows by number (two columns side by side, a range, "18+", a number in a cell of its own, a long result that wraps, several dice read together as a sentence), a grid's rows by height and its cells by gap. `solo/books/pages.py` writes a rules page for each section with words of its own; `spelllist.py` reads spells; `cards.py` a deck.
4. The recipe for each book is a package: `dragonbane_core/` (the core rules: gear, the numbers of every roll and fight, tables, character creation, the bestiary, heroic abilities, spells, rules pages), `dragonbane_magic/` (the Book of Magic), `dragonbane_cards/` (the three decks), `dragonbane_solo/` (the solo booklet, laid over whichever of the others are there) and, for the adventures, `dragonbane_tower/` (The Sinking Tower) and `dragonbane_vale/` (the Adventure Book's campaign), which build adventure packs into `~/Games/solo/adventures` for the system pack `dragonbane` (built first: `--systems` says where it is, `--adventures` where the adventures go).

To add a printing or a book: `solo extract` it, load it with `solo.sections.Book`, find its sections by title, and write a package like the ones above with a test on a made-up book (`tests/fake_book.py` builds one with the typefaces the real ones use, so no book is needed to run it). Where an importer had to choose (which of two weapons is a goblin's attack, which letter a big initial is), it says so in `pack.note`, and `solo compare` shows the result against a pack made another way.

What an importer reads and what an agent still has to: everything printed as text. Art that carries words only as a picture can't be read this way.

### Adventure books

An adventure book is read by `solo/books/adventure.py`, which knows how the Dragonbane adventures are set out: a chapter for each site, a numbered section for each place in it (what to read aloud in semibold italic, the things to find as bullets, the ways on as bullets named for a direction with the place's number), and under a place its people and monsters. It builds:

- **A scene for each place**, in a chapter file of the pack (`chapters/chapter_05_<site>.toml`), its text in `scenes/<id>.md`: the read-aloud words first, the rest inside a GM fence, a place's number turned into its name where the text refers to it (`#4 Mound Tunnels`). What the book says before its places (the situation, the sidebars) goes with the first scene, its tables are on every scene of the chapter.
- **Exits** from the bullets named for a direction (and the bullets about a door, gate, portcullis or passage that give a place's number) and from the labels on the book's maps ("To #3", with "(hidden)" beside it for a way that must be found). A way the text calls locked, blocked, barred, sealed, hidden or secret is a **gated exit** opened by a fact: the scene says which, in the exact `commit` the GM runs when the heroes get through. A place no way leads to is linked from the place before it in the book, and back, and the build says so (the book's maps are pictures, so the importer can't tell where a way really goes). A village is a hub: every place opens on its square and the square on them.
- **NPCs** from the stat blocks (a stat block is set in a colour of its own, which is how it is told from what the book says): `[stats]`, the one weapon the engine fights with (the first listed; the rest are in the description) or, for a monster, its table of attacks (`bestiary._attacks`, the same reader as the core rules' monsters, nested tables included), skills, and everything else the book says as the description. A person the book gives "stats as per the Rulebook" is that rulebook monster (`monster = "<id>"`, found by the person's name or the sentence that sends the reader, with the numbers the book changes laid over it); one with no stat block is a profile with no stats, and the build says so for each, and says when more than one rulebook monster fits.
- **Tables** (random events, encounters, omens, whatever the book rolls on), with the die read from the header, or, where the header has none or two ("D6/D10"), as high as the rows go; a section called a table whose rows are First, Second ... is left as words in its scene.
- **Rules pages** for the book's introduction and its notes on journeys, which the GM looks up (`solo rule`).
- **Pre-generated heroes** (`dragonbane_tower/heroes.py`) from the sheets, read by where each value stands: a value lettered over its printed label, a skill's number to the left of its name. A hero the adventure also names as a person in one of its places is a `replacement`, with the same id as the NPC.

What it leaves to the agent and the player, because the book leaves it to its GM: clocks and timers (a real-time limit, a time loop), what a fact opened by play does (the exits are only as gated as the text says), the attitude of a person (`neutral` for a person, `hostile` for a monster), and ferocity that depends on the party (one card). The adventure's own `checks/` are the agent's to add. The reading is checked the way every importer's is: the audit finds every page cited, every scene, NPC and table claimed, and each stat and table result on the page it cites.

## A game that ships: Ironsworn from Datasworn

Ironsworn is the one game whose rules may live in this repository, because the moves, oracles and assets are published under the Creative Commons Attribution 4.0 license, which allows it with credit and for any use (its NPCs, atlas and truths are under CC BY-NC-SA, which is for non-commercial use only and asks the same license of anything built from it, so they are left out). [Datasworn](https://github.com/rsek/datasworn) publishes the book as JSON with the license of every object marked, so this is the one import that needs no PDF and no agent:

```bash
curl -o classic.json https://raw.githubusercontent.com/rsek/datasworn/main/datasworn/classic/classic.json   # a 0.0.x release
solo import datasworn classic.json --out packs/ironsworn
```

- It reads `_source.license` of each object, else its collection's, else the package's, and takes only CC BY 4.0. It says what it left out (`atlas`, `npcs`, `truths` and any table under another license), and prints the yes/no odds the ask-the-oracle tables give, which `packs/ironsworn/system.toml` (`[oracle.odds]`) has to agree with. It refuses a Datasworn that isn't 0.0.x: the shape changed after it.
- It writes `moves/<id>.toml` (what the move rolls, the book's words, the words for each result, where in the book), `tables/<id>.toml` (a row that sends you on to another table, or says to roll twice, is a `then`) and `assets/<id>.toml`. Every file opens with a `# Generated by ...` line naming the book, the author and the license. A run rewrites the files that carry that line and deletes the ones the book no longer has; a file without it is somebody's own and is left alone.
- `system.toml`, `creation.toml` and `characters/` of the pack are written by hand and hold what the data doesn't: the attributes, tracks, momentum's range, the progress ranks, the odds, the stat array. Datasworn doesn't carry the numbers of the rules themselves (a rank's ticks, momentum's reset), so they come from the book and are checked against its rules pages by hand.
- Checking it: `tests/test_datasworn.py` runs the importer on a tiny made-up ruleset (`tests/fixtures/mini_datasworn.json`), and `tests/test_action_roll.py` checks that the real pack validates, that every move rolls something the sheet holds and that every generated file names its license. The imported moves were also read against the printed rulebook once, when the engine was written: 273 of their 286 sentences are in it word for word, and the rest are small rewordings Datasworn made ("first set the rank" is "set the rank") and the table pointers the importer adds. The assets weren't checked that way (the assets PDF is laid out as cards). The engine's own rules (a tie goes to the dice, a score never passes 10, negative momentum cancels a matching action die, burning cancels the dice under momentum, momentum's limits, progress by rank) were read off the rulebook's pages, and `tests/test_action_roll.py` holds each of them.
- What it taught: the counts in the file are of moves (35), tables (33) and assets (78); Datasworn's own count of 41 and 105 objects includes the collections that hold them. A move that rolls something the sheet doesn't keep (a companion's health) is imported with no roll and says so. Rows keep the source's own punctuation, slips included.

## The process

1. Get the text. `solo extract <pdf>` writes it to `~/Games/solo/sources/<book>/`: a file per page, a file per chapter with its page range and size, `book.md` for grep, and every table as Markdown and as a picture of the page. Running heads and page numbers are taken out of the text (`manifest.json` lists them under `running`), and when the PDF has no page labels the printed numbers are read off the footers (`labels`, `labels_from`). It needs PyMuPDF (`sudo pacman -S python-pymupdf` on Omarchy; [the README](../README.md#pymupdf) has other systems); nothing else in solo does. The PDF never has to go through a chat upload, whatever its size. If it lists pages with almost no text and a picture, they are usually the cover and the chapter openers (a title over art) and need nothing; only when a page that should hold text is among them, run `ocrmypdf` on the PDF and extract again. If the PDF has no bookmarks, `toc.json` is a guess from font sizes: check it against the contents page. Read a chapter at a time from `chapters/`; for a table, look at the page's picture in `tables/` when the text has scrambled its columns.
2. Read all of it before writing anything, and write the inventory as you go: `inventory.toml` in the pack (PACK_FORMAT.md), one item per mechanic, table, creature, place, set piece, clock-like thing and component, each with its pages and `status = "todo"`. Note what the book assumes about the table (a party, a GM, real time). Set `extract` to the extract folder so the audit checks pages. `solo inventory <pack> --extract <folder>` starts one: a file per chapter under `inventory/`, an item per section and table found, every page with text already cited. On a long book, one agent per chapter file refines its items; ids are shared, and the audit reports one used twice.
3. Map each thing to the engine (the table below) and record it on its item: `mapped` with `to`, `engine` with what the engine needs, `skipped` with why. What maps to nothing is engine work: note it, decide with the user, build it with tests, then use it.
4. Decide what belongs where. Rules of the game go in the system pack. Rules one adventure leans on go in the adventure's `rules/`. Components that the engine can simulate (a deck, a timer) become tables and clocks.
5. Write the pack. Tables come in with `solo import table` (from the extract's Markdown or a page's roll lines), never retyped. For many similar pieces (a few dozen waypoints), a throwaway script that renders the files from a data list saves time and mistakes; the files it writes are the source afterwards, and the script isn't kept.
6. `solo validate --adventure <pack>` until ok and nothing is worth a look; `solo outline --adventure <pack>` and check every gate, stage, branch and read fact against the book. `solo audit --adventure <pack>` (or `--system`) until everything is accounted for: no `todo`, no reference to something that isn't there, nothing in the pack that no item claims, no page with text that no item cites, and nothing a mapped item points at that isn't on its pages (table results, dice, stats, prices).
7. Fixed-dice tests of the routes that matter (see `tests/test_playtest.py`). Tests of a private pack stay private with it: this repository's tests run on made-up rules and its own adventures.
8. GM play tests (`tests/gm_eval`): scenarios for the risky parts and one long run with an agent player. Read the reports, fix the text or the engine, run again. Several rounds is normal.
9. Walk the user through every inference and translation with its page. Put the translations at the top of `adventure.toml` so they travel with the pack.

## Mapping a book to the engine

| The book says | Encode it as |
|---|---|
| A door, stair or passage that appears when something is done | A gated exit (`when = "fact.x.y"`), and the exact commit that sets the fact in the scene's GM text |
| After an hour, at midnight, on the third day | A clock advancing on `time:<unit>`, with a stage at that segment (text for the player, note for the GM, facts it sets) |
| Once it starts, every round X | A clock with `while` and `advance = ["time:round"]` |
| Every round in this place, the hero must X | `each_round` on the scene: it shows in every fight line there |
| Moving takes time; the tournament has a timer | `move_time`, and `time` on particular exits |
| Roll on this table | A table copied exactly; results that roll a value or pick a sub-option use `roll`/`choices`/`then` |
| A random treasure | `solo table treasure` (when the pack has the core set's deck) or `then = "treasure"` |
| A monster's stat block and attack table | `npcs/<id>.toml` with `[stats]` (hp, armor, ferocity, immune) and `attacks` naming its table; result flags `defend`, `parry`, `armor` |
| A creature named with no stats | `template` (minion, boss) and `attacker` (melee, ranged, sneaky, magic) |
| A person with skills who may fight beside the hero | `[attack]` and `[skills]` in the profile; `solo ally` runs them |
| A pregenerated character | `characters/<id>.toml` |
| If a character dies, the player takes over X | `characters/<id>.toml` with `replacement = true`; `solo hero <id>` |
| A relic weapon | `[weapons]` in `adventure.toml` |
| A rule the adventure relies on (fear, drowning, scoring) | `rules/<topic>.md` in the adventure, in your own words, marked as a stand-in if the book doesn't give it |
| Something the hero's skills might notice | A voice (`[[scenes.x.voices]]`), one or two per scene |
| Missions from a hub, in order | A hub scene with branches per mission, and gated exits into each mission's first scene on the previous mission's done fact |
| Places generated at the table | A placeholder scene whose GM text is the generation procedure (which tables to roll) |
| "The players", "a player character" | The hero; attacks on everyone nearby hit the hero |

## Rules and system packs

A rulebook is imported with the `solo-rules-import` skill, and `make rules` starts it. The pieces it stands on:

- The bundled `packs/dragonbane` holds only the game's names (attributes, conditions, tracks, skills, hero names) and a `needs` list. The engine won't start a campaign until the packs laid over it hold every key there.
- A pack from a book the player owns lives in `~/Games/solo/systems/`. For Dragonbane, `make rules` makes two: `dragonbane-rulebook` over the bundled names (`extends = "bundled:dragonbane"`), and `dragonbane` over that, the one campaigns use, which holds the solo rules when the player has that book. Each has its own inventory, so each audits against its own book. A pack can also hold `checks/`: fixed-dice tests of the rules the import mapped, with the book's page in each test's name, which `make check` runs after the audit.
- The data the engine runs goes in `system.toml`, `creation.toml` and the tables. Price lists and coins go in `gear.toml`; monsters in `bestiary/`, which every adventure's NPCs can be (`monster = "wolf"`) and the GM can bring into play by a commit.
- Everything the GM rules on itself (travel, fear, poison, spells, the book's own words on anything the engine runs) goes in rules pages, one topic each, with a `Search:` line of the words a GM will ask with. Play tests showed GMs asking `solo rule prices`, `bartering`, `inn`: they search by the question, not by the book's headings.
- A rule the engine runs should also be explainable: `packs.engine_rules` writes `solo rule` pages from the system pack's data (and the price pages and the bestiary), so the GM gets exactly what the engine does. Add a page there for each new data-driven mechanic. The book's own page of the same title replaces the engine's.
- A solo booklet maps cleanly because each of its rules is either a table (copied), a procedure with a roll and a table (search, scavenge), a counter (threats), a modifier on existing mechanics (more initiative cards, paying for a push, tending wounds at a rest), or advice for the GM (resolving failures, avoiding combat), which belongs in the GM skill.
- Nothing from a book is committed here, not its prose, tables or numbers. The tests use made-up rules (`tests/fixtures/house`) in the same shapes.

## Lessons learned

In the data and the engine:

- An agent transcribing a book writes plausible numbers when it half-remembers the game. Coverage can't see that; the audit now reads each mapped table, dice expression, stat and price back against the cited pages.
- Search by substring found "inn" in "beginning" and answered "prices" with nothing, because no page was titled so. Rules pages carry the words GMs ask with, and matching is by whole words.

- TOML reads `facts = { hall.flooded = true }` as a nested table. The engine flattens stage facts, but quoting the key (`"hall.flooded" = true`) is safer anywhere else.
- Names collide. NPC profiles already had `role` (a description), so the NPC attack role became `attacker`. Grep for a key before giving it a new meaning.
- A GM writes `{"hp": -1}` meaning a loss. A number sets a value, so the engine now reads negative numbers on tracks as losses. It also accepts one name where a list is expected (`"add": "dazed"`).
- Time that passed before a clock started must not count on it: the stretch whose stage starts a countdown in rounds holds 90 rounds.
- Read the rule instead of guessing it. Ferocity is the number of initiative cards, not actions on one card; the first version had it wrong.
- A rule change shifts the dice of every older fixed-dice test. Freeze a fixture (`tests/fixtures/ragna.toml`) rather than rewriting dozens of tests, and give new behaviour its own tests.
- A `str.replace` on code can hit two places; check the count.
- The extract took a line for a running head when it sat at a page's edge on enough pages. On two-column pages a spell's "Rank: 1" or a table's "D6" often comes out first, so they vanished from the text; a running head now has to be at the edge nearly everywhere it appears. Compare the manifest's `running` list against the book.
- Soft hyphens split words ("market\u00adplace"), and the audit read them as two. The page check drops them now.
- The Markdown grids lose ligatures ("sufer") and scramble columns; the page text is clean. Roll lines built from the page text (a row number alone on its line joined to what follows, a number with text only when it is the next row) import best. Tables of six side-by-side columns (random NPCs, quests, journeys, sites) had to be read from the picture, a column to a table, chained with `then` so one roll reads as the book's sentence.
- Numbers typed from memory of a game were wrong in several places, weapons among them. Nothing is typed from memory now: every number cites a page, and the audit reads it back.
- A kit offering a choice of three weapons becomes a kit per weapon, the book's other kits repeated so each keeps its one in three.
- Whole-word search still matches the start of a word: "inn" found "innate" on every kin page before any page about inns. A GM's question needs a page carrying it as a search term.

From the first import of a whole rulebook (Dragonbane's core rules, 116 pages, start to finish):

- Every table in the book came out as a row number alone on its line, its text on the lines after. `solo import table` read only "1 text" and refused them, so the importer now reads both, and a number starts a row only when it is the next one (or on a D66 the step from 16 to 21) and within the die the header names: "20 meters suffer a fear attack" on a wrapped line is not row 20 of a D6. Slice a table out of a page between two lines and let the importer read it; type nothing.
- Tables of six columns (random NPCs, quests, journeys, sites) came out wrong as text and right in the page's picture (`tables/pNNNN.png`): read each column into a table of its own, and let the first column's results roll the others (`then`), so one `solo table quest_when` reads as the book's sentence.
- A top-level key written below a `[table]` header belongs to that table: `untrained = [[5, 3], ...]` under `[skills]` became a skill with a list for an attribute, and validation crashed. Top-level keys go above the first table; `solo validate` says so now.
- The book's own words differ from the engine's slugs. A hero's item is matched to a weapon by slug, so a kit that says "small shield" only parries if the weapon is `small_shield`. Key weapons adjective first, as the kits write them (`light_warhammer`, `small_shield`, `light_crossbow`), and check that every weapon and armor a kit hands out is a key (a check in the pack's `checks/` does). The bundled hero carried a plain "shield" until this import.
- The audit found a price on the page and never asked whether it was the right row. It now reads each price beside its item's name, in the direction most of the table's entries agree on, and skips a table whose columns came out scrambled. For what it can't read (a weapon table's columns, a stat block), a throwaway script that walks the page text in reading order and compares every row with what you wrote is cheap, and worth running before the audit does its looser check: it found nothing wrong here, which is what it is for.
- A price the engine can't read ("2 gold x potency", "2 gold/day", "-") is `price = "varies"` (or the amount) with the rest in the entry's `note`. A number the book doesn't print, but the text derives ("twice the weapon's dice"), is written as the printed terms (`2d8+2d8`) so each is found on a cited page; otherwise the item is `house`.
- The extract loses the drop cap of every chapter opener ("he adventurer", "his game features", "elcome"): read the first words of each opener. On two-column pages a sidebar lands in the middle of a sentence, and the extract put the elf's ability under the mallard's heading. After generating pages, scan them for a paragraph that starts in lowercase: that is where a sentence was cut.
- A regular list (heroic abilities, skills, spells, monsters) is one throwaway script that slices the extract between headings and cleans the text: join a word broken by a soft hyphen at a line end without a space, treat a non-breaking space in a heading as a space, know the few headings the book sets in mixed case ("Lethal Poison"), and don't take a sentence's last word in capitals ("PERFORMANCE.") for a heading. Lift sidebars out by line number into pages of their own.
- Writing the inventory from a script beat editing the scaffold: each item's `to` list comes from the files that exist (every ability page, every spell of a school, every price of a category on its page), so the audit's "unclaimed" list is empty by construction and only the items' pages and notes are judgment.
- Search by a short word matched the start of longer ones ("inn" found "innate" on every kin ability page before the lodging prices). A word of three letters or fewer now has to match whole.
- The bundled names had the three schools of magic on WIL. The book says they are INT skills. The first import is where a names-only pack's small errors show; the import layer corrects them, and the bundled names should follow.
- A pack's own checks live in `<pack>/checks/` (they hold the book's numbers, so not in the repository) and `make check` runs them: fixed-dice tests of each rule the import mapped, with the page in each test's name. Play through it once by hand as well: `solo new red-tusk`, `solo rule` for what a GM asks (prices, inn, fear, a heroic ability), a fight with a bestiary monster, a rest twice, a push, three death rolls, a table that chains.

From the solo booklet and the three card decks (each its own PDF, each its own pack):

- A book's inventory is checked against the pages it cites, all of them together. That is fine for a chapter and useless for a deck: the treasure deck is forty cards on forty pages, and "2d6x5" is somewhere among them, so every card passed whatever it said. A result can now name its `page`, and it is read against that page alone; `choices` are read too (they were not: most of a deck's content), and so are the numbers in a result's text (a ruby "worth 35 gold") and a dice multiplier (`roll = "2d6x10"` was never looked at, since the pattern stopped at the x). Corrupt a copy of a pack on purpose and see the audit fail before you trust it: it let a wrong multiplier and a wrong gem value through until this.
- A card's words are half in the PDF's text layer and half in the art (a name, a value line), and OCR of ornate cards was unusable (tesseract read "sflver coms"). The values were read from the pictures by the agent and kept in `picture/<page>.txt` in the extract, where the audit reads and names them; twelve of forty treasure cards and three of eighteen improvised weapon cards needed it. The audit against those pages is a check of the pack against the agent's own reading, so the contact sheet of the card faces stays in the extract for the user to look at.
- `solo import table` mistook the wrapped line "2: cursed item, 3: ..." for row 2 of a D10 and cut the result short. A table whose results contain lists of numbered options is read by its known range labels in order ("1", "2-4", "5"...), not by the next number it sees.
- A table with columns side by side (inspiration, the four location subtables, the trap and area lists set in three columns) came out as a row number and then one line per column, or as pairs in scrambled order. A few lines pair each number with its cells; check the count, and check that every cell is on the page.
- A procedure that says "roll a D4, then roll that many times on this table" is a table of its own whose four results each `then` the other table that many times (`location_detail_rolls`), so one `solo table` plays it. A trap that says "18 or more: roll twice" is `then = ["traps", "traps"]`; a "roll again" is `again = true`.
- Each card of a one-off rule (an improvised weapon) is a rules page, and one shared `Search:` line on all of them made "wasp nest" find the index and "improvised weapon cards" find the bats. Give each card only its own name; the index takes the shared words.
- A booklet mixes rules and its adventure (five missions, a named NPC, a weapon). The system pack's inventory marks the adventure `skipped`, "for the adventure pack", and the `solo-import` skill builds that.
- The threat counter advances once for every stretch that passes, so a shift's rest (24 stretches) brings any threat to its end. The book says to advance it for the activity, once. Left as it is, and listed in the roadmap.

In compiling adventures:

- Don't close a way the book leaves open. A flooded room could still be swum through; closing it stranded a hero.
- Keep the book's resets. A creature that the book sends back to what it was doing needs the fact that angered it cleared.
- Give the GM procedures, not only outcomes: "a torch is a skill roll, then `solo wound <foe> 1d6 --through-armor`".
- Every fact a condition reads needs its exact commit in the GM text of the scene where it becomes true. `solo outline` lists them all.
- Don't invent names or numbers. Where the book is silent and a number is needed, say so in the text ("the book gives no number: D6").
- Stand-in rules shape play. A made-up fear result ("must attack") forced a fight the player was avoiding.
- Long procedures repeated in every scene cost the GM attention on every turn. Put them in a rule page and point to it.

In what GMs do (from the play tests):

- They guess skill names from other games (search, insight). The scene digest lists the hero's skills, and an unknown skill lists the system's.
- They forget what a place asks every round (holding a breath). `each_round` puts it in the fight lines.
- They skip a monster result that is an effect rather than damage. The engine says "run this now".
- They offer choices the rules don't allow (evading while dying) when the engine's own lines suggest them. The lines now say what's allowed.
- They think aloud in the final message, and once copied a `::: gm` block into it. The Book drops both; the harness flags them.
- They drift into third person. `AGENTS.md` carries the rule in one line.
- They write the dice into the story ("(Sneaking, 14 vs 5, failed)") though the Book shows them. `AGENTS.md` and the skill forbid it by example; the harness flags it.
- They reach for money as its own thing (`"silver": 30`, `"gear"`, `pc.tracks.silver`). Coins are items; the refusal now says so. They also nest tracks (`{"pc": {"tracks": {"hp": 3}}}`), which the engine now reads.
- They want to hurt the hero outside a fight (a fall, a trap) and tried `solo wound pc`. `solo wound hero` now does it, with armor. They also guess table names (`table danger`); the refusal suggests the near ones.
- They set a threat and then forget it: over a whole mission, failed rolls never advanced the goblins. A failed check out of a fight now names the live threat and the command.
- A hub scene has to carry what the GM must say there. A mission briefing skipped the waypoints and the threat until the hub's text listed them for each mission.
- They answer from the text or a skill roll before the oracle, as the ladder says. Scenarios meant to test the oracle need questions nothing else answers.
- A resumed session picks the story up from the campaign well, but the first turn is slow (several minutes).

In solo play:

- Content written for a party kills a lone hero. The system's own solo rules (two turns a round, pushing for willpower, healing alone) fixed that without touching the adventure's numbers. Prefer the book's solo rules to ad-hoc scaling.

## Play-testing an ingestion

Runs cost real usage: one long run can take half an hour, and a usage limit can cut a run off mid-way (the harness stops after two failed GM turns in a row). Run the short scenarios first, and the long one once they pass.

Write scenarios in `tests/gm_eval/scenarios/` for: the opening, each gate or puzzle, each unusual monster, any timer, and one long run with an agent player and a dropped session. Expectations can be state conditions (`when`) or events (`event = "search"`). A short scenario costs a few minutes; a long run half an hour. The judge varies between runs, so read its issues rather than only the scores, and trust what the code checks find.

## Legal and privacy

This repository is public. Free League's Dragonbane Third-Party Tabletop Module License lets a supplement use Dragonbane's terminology and cite its pages, and forbids carrying a copy of its rules or any of its text or art (see [NOTICE.md](../NOTICE.md)). So:

- Nothing from a book goes into this repository: no prose, tables, numbers or adventure text, free adventures included. It stays in `~/Games/solo`.
- Page references are fine (`source = "p. 58"`), and so are the game's terms (skill names, conditions, kin).
- Tests use made-up rules and this project's own adventures.
- Every pack says where its content comes from (`source`, and the header of `adventure.toml`).
