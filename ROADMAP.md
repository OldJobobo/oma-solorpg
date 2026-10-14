# Roadmap

The next pieces of work, for an agent or anyone picking this project up. Each item gives its goal, where it stands, what is left and when it is done. What each pass built, with its dates and numbers, is in [docs/HISTORY.md](docs/HISTORY.md).

Read [docs/INGESTION.md](docs/INGESTION.md) first (how content gets into the engine, and what went wrong before), then [docs/PACK_FORMAT.md](docs/PACK_FORMAT.md) (every key a pack can hold). [docs/PLAN.md](docs/PLAN.md) has the design, and its Scope section lists the smaller things planned for later.

The order is by who each item unblocks. Item 1 lets other people send changes. Item 2 proves the one way into Dragonbane works on real books. Item 3 lets someone with no book play at all. Items 4 and 5 are about trusting the GM: hard limits in code, and a way to measure whether a change to its instructions made it better. Item 6 is campaign generation.

## 1. Open the project to contributors

Goal: anyone can send a change, and the pull request shows whether it passes.

Status: done (2026-09-30), but for one check. CI runs the tests and the QML check, and CONTRIBUTING.md, the issue forms and SECURITY.md say what to send and where. The test for a book's words and numbers (`tests/test_no_book_text.py`) skips in CI, because no book fingerprints are committed.

Left:

- Generate the book fingerprints from the maintainer's extracts (`python3 tests/test_no_book_text.py --fingerprint`, with `SOLO_FINGERPRINT_KEY` set), commit `tests/fixtures/book_fingerprints.txt`, and save the key as the repository's Actions secret, so CI checks every pull request for book text as the maintainer's machine does.
- Create the labels the issue forms put on an issue (`gm`, `import`), and switch on private vulnerability reporting, which SECURITY.md sends people to.

Done when: a pull request from someone new runs every check the maintainer runs locally, apart from the GM evaluation, which costs model calls.

## 2. Rules ingestion from a rule book, run on a real book

Goal: a player hands over a rulebook PDF they own and gets a system pack the engine runs, checked against the book's pages. For Dragonbane's books that is `make dragonbane`, with no agent; a book no importer knows goes to an agent with the `solo-rules-import` skill.

Status: the importers build the core rules, the Book of Magic, the three card decks, the solo booklet and the two adventure books, and the engine runs what they hold (2026-09-30 to 2026-10-01; the adventures had a GM play test on 2026-10-02). What is left is mostly play.

Left:

- Alone in Deepfall Breach, the adventure half of the solo booklet, has no importer, only the maintainer's agent-made private pack. Decide whether it gets a `dragonbane_solo` recipe, and give it a GM play test (a mission, a fight, a search, a rest).
- Its foes are the booklet's minion and boss templates; swapping in the rulebook's bestiary (`monster = "troll"`) is the maintainer's choice.
- The play-test scenarios for the imported rules, run from outside the repository, including a hero built from the imported creation tables who gets through a fight, a rest and a push. They cost model calls, and nobody has run them yet.
- A fixed-dice test in the private packs' `checks/` for each rule that lands from now on.
- The imported adventures' timers as clocks (The Sinking Tower's two hours, the Adventure Book's village time loop), what opens each gated exit, a person's attitude, ferocity that depends on the party, and a `checks/` folder for each adventure.
- Swap the maintainer's agent-made packs (`~/Games/solo/systems/dragonbane-*`) for the built ones: build beside them with `--systems <dir>` and read a `solo compare` diff first. The agent-made packs are what the built ones are compared against, and are never overwritten blind.
- Play the Table by hand on a real desktop with a Dragonbane campaign. The Magic section, riders, the Dragon card, Mend and the load have only run in the headless `panel_check.py`.

Done when: a player can give a rulebook PDF, an agent produces a system pack that validates, `solo audit` shows nothing unaccounted for, The Red Tusk Hall and the maintainer's regression adventures play on it, and a GM play test with a hero built from its creation tables gets through a fight, a rest and a push with the rules as the book has them.

## 3. A game anyone can play without buying a book

Goal: someone who installs oma-solorpg with no book plays at once. The game is Ironsworn, whose moves, oracles and assets are CC BY 4.0, with The Bell Under the Hill as its starter adventure.

Status: done (2026-09-30), apart from what is left below. New adventure, The Bell Under the Hill, Begin works on a fresh install.

Left:

- A GM play test with a real agent on The Bell Under the Hill (the scenarios are written; nobody has spent the model calls), and a run of the Table by hand on a real desktop.
- What the engine doesn't run: an asset's abilities (the GM reads the page and passes `--add`), a companion's own health (`companion_endure_harm` is imported with no roll), experience (a `hero.xp` fact), Delve and Starforged.
- Portraits for Ironsworn heroes: the text art is Dragonbane's kins.
- Campaigns generated on Ironsworn (item 6).

Done when: a player with no book starts The Bell Under the Hill from the New adventure screen, and a real GM has played it through.

## 4. Safety and controls

Goal: the player's lines and veils and a GM turn's reach are held in code, not only in the GM's instructions.

Status: built (2026-09-30): the X-card (`solo strike`), hard limits on a GM turn and on a session's spending (`solo gm budget`), adventure text treated as untrusted, and `solo report`.

Left:

- Run `injected-scene` with a real GM, and add the cheat and lines-and-veils scenarios of item 5.
- A control for the budget on the Table, and a line in the Book when a session is close to its limit.
- A Codex GM can still delete or rewrite `.solo/agent.json` (the session id the spending count is keyed to), and the next turn starts a fresh session whose count starts at zero. Closing it means keeping the session id outside the campaign folder too, which changes how the play-test harness starts a new session.
- The Book's first prompt now puts the table and the adventure's text in a block marked as data (2026-10-13), and a resumed turn what happened at the table since its last message (2026-10-14). `injected-scene` hasn't been run against it.

The lint can't stop a clever injection, only the obvious; the GM's own tool limits are what hold when it fails.

Done when: a player can cut a message and never see it come back (built), a turn can't run past its limits whatever the agent does (built), and item 5's safety scenarios pass.

## 5. Measure the GM, then improve it

Goal: show whether a change to what the GM reads (`skills/solo-gm/SKILL.md`, the Book's prompt in `solo/gm.py`, what `solo resume` and `solo scene` print) helps or hurts. The GM is the player's own agent, so there are no weights here to train: `tests/gm_eval` plays scenarios with a real GM, checks each message and the campaign state in code, and has a judge score the transcript.

Status: the tools that need no model call are built (2026-09-30). `tests/gm_eval/results.tsv` holds six runs at commit 65d2734, three each of `bell-opening` and `red-tusk-memory`. Those runs used `SOLO_SEED`, which until now gave every command the same roll, so the baseline needs running again.

Left, all of it model calls, so it waits for the maintainer:

- A baseline: every scenario, `--repeat 3 --seed 1`, with Claude Code on its default model and a small one, at the normal pace, checked in to `results.tsv`. Commit first: `compare.py` matches runs by commit.
- Run the new scenarios once and read the reports: the cheat, table-settings and resumed-fight scenarios and `injected-scene` have never met a real GM, and their patterns may need tuning.
- The GM habits the 2026-10-02 play test of the adventures turned up: the per-round roll a scene asks for, dropped after round one; evade-or-take loops when the scripted player is vague; naming someone the hero hasn't met. Each is a change to measure with `compare.py` before keeping it (three runs a commit, about $15 for the four adventure scenarios).
- Those scenarios hold the adventures' facts, so they live outside the repository (`~/Games/solo/gm_eval/scenarios`, run by path). Keep eval output in `tests/gm_eval/runs/`, which is git-ignored because it holds book text; never `git add -f` it. Spread runs out: the first batch hit a session limit.
- What `solo review` finds in campaigns played for real (the maintainer's own play first) becomes scenarios. Its "two names" check sees only commits and ids, not a GM naming a person differently in its narration.
- A manual workflow with an API key as a repository secret can come later.

Done when: `results.tsv` has a baseline, every change to the GM's instructions since carries a comparison against it, and the safety scenarios are part of the set.

## 6. Generate campaigns

Goal: a player with no book for the story they want pitches one (a premise, a tone, a length), and an agent writes it as a campaign pack the engine plays like any other, with the dice taking part in the writing. The website already presents this; build to it, or change the page with it.

Status: the engine side is built and tested: `make campaign`, `make campaign-next`, `solo campaign new|next|roll|check` and the `solo-campaign` skill.

Left:

- Run `generated-mission` with a real GM on rules built from a book, and fix the rolled prompts or the skill where the GM stumbles.
- A campaign written up by an agent, from `make campaign` to a second mission with `make campaign-next`, played for real. What it teaches goes into the skill and docs/INGESTION.md.
- The generator's own lists (places, roles, voices, obstacles, hazards, omens) are short and plain on purpose, since the agent rewrites them. If write-ups keep the same placeholder shapes, give them more variety, or let a system pack name tables to roll instead.
- Campaigns on Ironsworn. The generator refuses an action-roll system today, since it writes rolls by skill (`solo check`) and skill voices. It needs waypoints written as moves (Face Danger, Gather Information, an Undertake a Journey per waypoint), the oracle's odds and tables (`place_region`, `character_role`, `settlement_name`, `major_plot_twist`) for what each holds, and a bell-style clock on `check:miss`.

Done when: a player gives a premise, gets a campaign that validates and shows on the New adventure screen, plays its first mission, and the second mission, written after the first, pays off something the hero did in it.
