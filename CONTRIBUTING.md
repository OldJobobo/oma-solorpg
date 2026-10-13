# Contributing

Pull requests are welcome. This page is what to know before sending one. The design is in [docs/PLAN.md](docs/PLAN.md), what comes next in [ROADMAP.md](ROADMAP.md), the formats in [docs/PACK_FORMAT.md](docs/PACK_FORMAT.md), and how books become packs in [docs/INGESTION.md](docs/INGESTION.md).

## The one rule: nothing from a book

This repository is public, and a publisher's license lets a project like this use a game's terms and cite its pages, not carry a copy of its rules. So no numbers, tables, prose, adventure text or art from any book goes in the repository: not in a pack, not in the docs, not in a test, free adventures and quickstarts included. A pull request that adds any will be refused, however small.

- Page references (`source = "p. 58"`) and a game's own terms (skill names, conditions, kin) are fine.
- The one exception is Ironsworn, whose moves, oracles and assets are published under the Creative Commons Attribution 4.0 license and ship in `packs/ironsworn` with their credit ([NOTICE.md](NOTICE.md)). They come from the Datasworn data through `solo import datasworn`, never by hand: a fix goes in the importer, and the import runs again. Nothing else of Ironsworn's book goes in on a pull request: its NPCs, atlas and truths are CC BY-NC-SA (non-commercial use only, the same license on anything built from them), and the maintainer has decided not to carry them, so a pull request that adds them will be refused; its images and design elements aren't licensed for use at all. No credit line is ever removed, and no other game gets an exception this way without its own license saying so.
- A test that needs rules gets them from `tests/fixtures/house`: made-up rules in the same shapes as a real system pack, laid over the bundled names the way a player's pack is. If a test needs a shape the fixture doesn't have, add it there with invented values. Test adventures are this project's own (`examples/red-tusk`, `examples/bell-under-the-hill`, `tests/fixtures/delve`, `gates`, `oath`).
- What a player builds from their own books stays in `~/Games/solo`, outside this folder on purpose. `.gitignore` catches a pack written here by mistake; don't rely on it.

Before you push, read your own diff for anything you typed from a book, and say in the pull request where every number and text in it came from.

`tests/test_no_book_text.py` checks the same thing by machine: when the books you own have been extracted (`solo extract`, or `SOLO_SOURCES` pointing at a folder of extracts), it fails on any run of eight words of a book in any file of the repository, committed or not. It has nothing to check without a book, so run `make test` once with yours at hand before you push a change to an importer.

## Running the checks

```bash
make test         # the engine's tests: python3 -m unittest discover -s tests
make qml-check    # Panel.qml and BarWidget.qml, loaded offscreen with stand-ins for the shell
```

The engine and its tests are standard library only, on Python 3.11 or newer. Run one file with `python3 -m unittest discover -s tests -p "test_packs.py"`. Two kinds of test skip themselves when their tool is missing: the ones that read PDFs need PyMuPDF (`sudo pacman -S python-pymupdf` on Omarchy; [the README](README.md#pymupdf) has other systems), and the shader compile check needs `glslangValidator`. `make qml-check` needs PySide6 (`pip install PySide6-Essentials`) and writes screenshots to a temporary folder.

Every pull request runs `make test` on Python 3.11 and on the newest release, with PyMuPDF and `glslangValidator` installed so the tests that need them run, and `make qml-check` with PySide6 ([.github/workflows/test.yml](.github/workflows/test.yml)). The result shows on the pull request without anyone running it.

## Changing the engine

- Follow the code around you: its names, its comment density, its habit of one plain path from top to bottom. A new dependency needs a reason; the engine imports the standard library and nothing else (PyMuPDF is read only when `solo extract` runs).
- New behaviour comes with a test, and dice are fixed: `helpers.Dice` stands in for `random.Random`, and `SOLO_SEED` fixes the rest. A rule change shifts the dice of older fixed-dice tests; freeze a fixture (`tests/fixtures/ragna.toml`) rather than rewriting dozens of tests.
- The engine never calls a model and never touches the network. The GM's adapter (`solo/gm.py`) is the one place that runs an agent.
- Anything a pack can hold is documented in [docs/PACK_FORMAT.md](docs/PACK_FORMAT.md) in the same change. A change that would break a pack written for the format before it raises `packs.FORMAT`, writes the sentence an author needs into `packs.UPGRADES`, and adds a row to the history there. A key that older packs simply don't use doesn't.
- The panel never writes campaign files and never computes rules: it runs `solo` and reads `state.json`. If it needs a fact, the engine adds it to `state.json` or `solo library`.
- A desktop effect (`solo desk`) puts back exactly what it changed, and `solo desk restore` undoes them all ([docs/PLAN.md](docs/PLAN.md)).

## Writing an importer: `solo/books`

A recipe in `solo/books` turns one book into a pack, and it holds where things are and how to read them, never what they say ([docs/INGESTION.md](docs/INGESTION.md)). Find each value in the section of the book that states it by a short pattern made of the game's own terms, and make a section that no longer says it fail by name, so another printing is caught instead of guessed at. An adventure book's recipe builds an adventure pack the same way (`solo/books/adventure.py` reads places, exits, people and tables; each book's package says which chapters are sites and where its heroes are). A recipe is tested with `tests/fake_book.py`, a book made of invented sections laid out like a real one; its numbers are made up, and the real book is only ever read at run time on the machine of someone who owns it. `solo audit` on what a recipe built should come back with nothing unclaimed, no problems and no uncited page.

## Testing the GM: `tests/gm_eval`

The unit tests check the engine. `tests/gm_eval` checks the game master: a real agent plays a scenario through `solo gm turn`, exactly as the Book does, code checks every message and the campaign's state, and a judge scores the transcript. It costs real model calls and needs the rules built from a book you own, so it runs by hand, before a pull request that changes `skills/` or `solo/gm.py`, and never in CI. [tests/gm_eval/README.md](tests/gm_eval/README.md) has the options and what each run writes.

A scenario is a TOML file in `tests/gm_eval/scenarios/`:

```toml
about = "What this tests, for the judge and for you."
adventure = "red-tusk"
character = "ragna"
max_turns = 5

[player]
mode = "scripted"                    # the lines, in order; "agent" lets a second agent play toward a goal
lines = ["I look at the carved tusk on the gate.", "I try to slip past the guards."]

[[expect]]
when = "visited.gate"                # a condition, in the engine's own language
why = "the GM moves the hero up the hill"
by_turn = 2

[[expect]]
event = "check"                      # or an event that must have happened
why = "getting past the guards is a roll"

[[forbid]]
text = "Deep Mother"                 # a regular expression the GM mustn't say...
unless = "visited.final_battle"      # ...until this holds
```

- Test one risky thing per scenario: an opening, a gate or puzzle, a strange foe, a timer, a secret that must not leak. Keep it to a few turns; a long run belongs to an agent player.
- Scenarios in the repository play this project's own adventures (The Red Tusk Hall, The Bell Under the Hill), a fixture pack, or a campaign rolled for the run (`[generate]`). They never play an adventure from a book.
- `[[expect]]` says what must happen and by which turn; `[[forbid]]` guards what must not. Prefer checks the code can make over hoping the judge notices.
- Read the report's issues, not only the scores: the judge varies from run to run.
- A change to `skills/` or to the GM's prompt in `solo/gm.py` comes with a comparison: play the scenarios on the commit before and after with `--repeat 3 --seed 1`, then `python3 tests/gm_eval/compare.py <before> <after>` (see the README there). These cost model calls, so they run on your machine before the pull request, not in CI.

## Sending a pull request

- One change to a pull request, with the reason in its description. Say what you ran (`make test`, `make qml-check`) and anything you couldn't.
- A bug in an import, or a GM that did something wrong, belongs in an issue first, with the details the [issue templates](.github/ISSUE_TEMPLATE) ask for. Those are public: don't paste a book's text or numbers into one. A security problem is reported privately instead ([SECURITY.md](SECURITY.md)).
- The project's own words (The Red Tusk Hall, the hero names, the text portraits) and code are under the [MIT License](LICENSE); your contribution is too.
