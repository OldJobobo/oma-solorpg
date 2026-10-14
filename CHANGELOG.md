# Changelog

What changed in each version of oma-solorpg. The version is the one in `manifest.json`. A release is a git tag of the same name, and the README's install line pins its commit; [Update](README.md#update) says how to move to one.

## 0.4.0 (not yet tagged)

### Added

- Ironsworn, playable with no book. Its moves, oracles and assets, which are CC BY 4.0, ship in `packs/ironsworn`, converted from Datasworn by `solo import datasworn`. A third mechanics family, `action-roll`, runs them (`solo act`, `burn`, `track`), and the Book and the Table show moves, momentum and progress tracks. The Bell Under the Hill is this project's own starter adventure for it.
- Importers for Dragonbane's books. `make dragonbane BOOKS=<folder>` (`solo import book`) builds the core rules, the Book of Magic, the three card decks and the solo booklet into private packs in about twenty seconds, with no agent, and audits each against the book's pages. A pack can extend a list of packs, `make supplement` lays another book over the rulebook with an agent, and `solo compare` shows two packs side by side.
- Adventure importers for the Quickstart (The Sinking Tower, with its seven pre-generated heroes) and the Adventure Book (The Secret of the Dragon Emperor, with Outskirt as the hub and eleven adventure sites), from your own PDFs, by the same command.
- Campaigns generated from a premise: `make campaign` and `make campaign-next`, `solo campaign new|next|roll|check` and the `solo-campaign` skill. The dice decide what each waypoint holds, every roll is kept in `rolls.toml`, and each mission after the first brings back something the hero did.
- Safety controls. The X-card: `solo strike`, the Book's "cut the GM's last message", which can also make it a line or a veil. Hard limits on a GM turn, and a spending limit per session (`solo gm budget`). Adventure text is treated as untrusted, and `solo validate` points out text that gives the model orders. `solo report` makes a bug report safe to post.
- Tools to measure the GM: `tests/gm_eval` repeats scenarios with fixed dice (`--repeat`, `--seed`), `compare.py` compares two commits, and new scenarios cover cheating, lines and veils, injected text and a session lost mid-fight. `solo review` runs the play test's checks over a campaign played for real.
- The rest of Dragonbane on the Table and in the engine: a Magic section (`solo cast`, `prepare`, `learn`), heroic abilities (`solo ability`), a Dragon's choice on an attack (`solo dragon`), weapons that get damaged or break (`solo repair`, Mend and Artisan in Gear), the load, ranged attacks, monster rules, and journeys (`solo journey`, `camp`).
- For contributors: CI on every pull request, CONTRIBUTING.md, issue and pull request templates, and a format version in every pack (`format = 1`).
- `make uninstall`.

### Changed

- The player's words reach the GM on stdin, never in the process list, and every event written while `SOLO_SEED` is set records the seed.
- A command runs in about a third of the time, and the GM starts with only the tools it needs, so an opening turn is quicker and cheaper.
- A commit reads the shapes GMs reach for (facts under the scene, a list of facts, time in words) and says how it read them.
- The README's install pins the clone to a full commit.

### Fixed

Campaigns and commits:

- A commit is checked before it is written. Time must be a number from zero up and at most a year in one step (`"1"` reads as 1, and "2 stretches" now reads); a memory is one line of text; lists where objects belong, NaN, infinity and ids that aren't text are refused with a sentence saying what the key holds. A commit with a string for time used to hang, and a list as a memory broke `solo resume` for good. Text holding half a character (half an emoji, or a byte that isn't UTF-8) and lists nested deeper than Python reads are refused with a sentence too, in a commit or anything else the log is given, and in a Book turn too, where `SOLO_TRACE` used to end the command on a traceback. A fuzz test throws malformed commits at the engine.
- A condition comparing values of different kinds (a fact `"two"` against 2) is false, instead of failing every later command after its event was already written.
- `state.json` always matches the log: any command, read-only ones included, brings it up to date after a crash or an update to the engine or the packs, and a map, codex or art the packs can't supply leaves it without them and says why on stderr. A disk that refuses `state.json` (a full one) fails no command, `solo log` and `solo state` included: it is said on stderr, and the next command catches it up.
- Every event is on the disk (fsync) before the command goes on. A write that fails is taken back and the command stops with a sentence. A campaign whose start stopped before its first event, and a damaged line in the middle of the log, say what happened and what to do.
- A clock filled by a commit or a clock stage sets off the clocks that listen to it.
- A failed check can be pushed, and momentum burned on a roll, only while the roll is still open: once a commit or a move follows it, it stands (one refused leaves it open), and the Table stops offering both. A check stands after a rest, a journey, a torch lit, or a fight begun, gone on a round or ended, too, so a tended wound or a missed blow can't be pushed once it can no longer change anything; a roll the rules don't push says so instead of calling it a success. The push and burn the GM is offered say how long they last, and the GM's skill and AGENTS.md tell it to end the turn on the offer and commit once the player has chosen.
- Removing what the hero lacks warns about the right list. A second foe of a kind never takes another person's id. `solo log -n 0` shows nothing, and `solo log | head` ends quietly.
- `SOLO_SEED` gave every command the same roll; a seeded run now repeats roll for roll and its rolls differ.
- Files in a pack that link outside it (rules pages, tables, people, chapters and the rest) are no longer read, and `solo validate` lists them.
- `solo recall` folds text about twice as fast on a long campaign.
- A game whose rules aren't built is told its own way to build them (`build` in `system.toml`), not Dragonbane's.

The GM:

- Claude Code runs the GM with `--restricted` and `--permission-mode dontAsk` when it has them, so the player's own Claude Code settings, allow rules and permission mode never reach a GM turn. Those flags keep the campaign's CLAUDE.md out too, so the GM is handed AGENTS.md with its system prompt.
- The GM can no longer strike a message, change the table settings, set its own budget or pace, or record words as the player's (`solo say --player`): those commands refuse inside a Book turn. Under Codex, which has no list of allowed commands and can write the campaign folder, that refusal stops a slip, not a GM set on it. What a session has spent is counted in `~/.local/state/solo`, out of the campaign folder.
- A new session's first prompt puts the table and the adventure's text in a block marked as data, never instructions, and so does every resumed turn with what happened at the table since (a table's result, a clock's note). The player's table settings and cuts in it are theirs to respect, not data.
- A turn ended by the quiet limit, the clock or Stop is charged an estimate (the session's dearest turn, or 50 cents) instead of nothing. Only an agent's own lost-session messages start a fresh session.
- Stop works while the agent is still starting, and only ever ends this campaign's agent. After a stopped turn the GM is told its reply never reached the player, and its rolls aren't passed off as the player's.
- GM narration that says "commit", "the player", "narrated" or "your first solo journey" no longer disappears from the Book. Commands Claude Code's permissions refused show in `solo report`, `solo review` and play tests.
- The Book and the make targets pick the agent the same way (`AGENT`, then Omarchy's default, read past blank lines, then claude, then codex), and `solo gm agent` says why when there is none or it can't run, in the words `solo setup` uses too, naming `AGENT` when that chose it. `solo play --terminal` opens the agent `AGENT` names too, as `bin/ask-agent` does, or says how, instead of Omarchy's default through `omarchy-agent`. `SOLO_AGENT` is now `AGENT`.
- A desktop border that couldn't be restored no longer stays red after later effects, and a screen shader that couldn't be restored is put back by the next restore instead of lost for good; an omen's words can't be read as notify-send options. `SOLO_GM_*` limits ignore zero, negative and non-numeric values.
- `tests/gm_eval/compare.py` compares scenario by scenario with a permutation test corrected for the number of metrics, and says the runs are too few only when they are; play tests record the model they asked for and, apart from it, the one the GM ran on, and keep their report when the judge can't start.

The Table and the Book:

- The X-card takes the cut message off the page, and only that one; a note that starts with a dash still cuts; a cut that fails keeps its words.
- Clicks while a command runs wait their turn instead of vanishing, and the buttons say so. A message the GM never got stops the Book waiting.
- A shut Book runs no animations. The d20 follows the very first game without a restart of the shell.
- With no agent set up, the Book says how to set one. Errors are kept per source, and a `solo` that can't start says so.
- Quiet text stays readable and quieter than the body on light themes too. The Table and the d20 load on Qt 6.12.
- At 0 HP the Table offers the death roll and what a dying hero can do, nothing else. In a fight the weapons sit right under the last roll.
- New adventure names each adventure's system, and says why one can't be played yet.
- Folds, cards and the Book's links work from the keyboard (Tab, Enter, Space) and are named to a screen reader; Enter in the hero's name begins.
- The Table tells the time as the Book does, names a skill once in its last roll, leaves out empty rows of buttons, goes Home when a campaign's folder is gone, and never shows an empty scene card. A campaign whose `state.json` is missing (deleted, or never written: `solo use` doesn't write it) has solo make it again and opens on its table, and one that can't be opened (its start stopped before the first event) goes Home with the engine's sentence why, from its card too, instead of "Loading the table" for good.

Imports and the audit:

- `solo audit` reads a table's results on their rows and checks its dice against them, reads every number of a weapon, rest, monster, spell, creation choice and hero back against its page, fails a mapped item whose pages have no text, and counts spells, moves and assets an inventory must claim. Corruptions it used to pass (swapped rows, a number, die or "not" changed in a table's result, 1d6 made 1d20, a weapon's STR or an armor's rating taken from another row, a monster's HP changed to another number on the page, or to another creature's on the same page) now fail. A table whose numbers the PDF wrote after their words, or whose row wraps before a number, is read as its rows all the same. A typical NPC's armor that the importer adds up from its armor and helmet is read back as that sum.
- `solo import book` (`make dragonbane`) exits non-zero when a book is unknown, unreadable, can't be built or fails its audit, after building the rest, and says when a PDF looks scanned. `--replace` keeps the old pack until the new one is built and playable. System packs are validated after a build, and one the engine can't play is never left where the library would list it, on a first build too, or by a build killed half way.
- A changed layout names the book, table and page instead of "something went wrong" (a cell with more than its number in it too), and an importer that stops some other way fails only its own book; a grip written "1-handed" is still a weapon, and one the importer can't read ("1H/2H") is named instead of making the weapon plain gear; a roll table whose rows stop short of its die fails the import; what an importer leaves out, it says in its notes.
- No importer writes into the repository. An inventory keeps its extract relative to `SOLO_HOME`, so a built pack is the same on every machine.
- `solo new` on rules that aren't built says so before asking for a hero, and `solo library` gives each adventure `ready`, `why` and `system_name`.
- `tests/test_no_book_text.py` can check every pull request against fingerprints of the maintainer's books, tables included, once the maintainer generates them. They are keyed with a secret kept out of the repository (`SOLO_FINGERPRINT_KEY`, an Actions secret), so the committed file can't be worked back into a book's rows or read on from a known sentence; a pull request from a fork is checked by the base branch's own test, which reads its files and runs none of them.

Install and docs:

- `solo` on a Python older than 3.11 says so in a sentence. `solo setup` and `solo play` link skills only for the agents you have, and setup says what playing needs.
- `make uninstall` puts the desktop back first. A premise with backticks or `$( )` reaches `solo` as typed and runs nothing.
- PyMuPDF is installed with pacman on Omarchy, wherever the docs say how. The website installs the way the README does.

## 0.3.0

The first version, 2026-09-27.

- `solo`, the engine: dice, the `d20-under` and `d6-pool` families, character creation, the campaign as an event log, the oracle with random events and a chaos factor, fights, dying and advancement, and the memory of a long campaign (consequences, `solo recall`, `solo resume`).
- The plugin: the d20 in the bar, the Table, and the Book, with Claude Code or Codex as the GM, run headless a turn at a time at the pace you set. Dice moments, voices, text portraits, torches, the codex, omens and the Hall of the Fallen.
- Desktop effects (`solo desk`): borders, screen shaders, sounds, candlelight, notifications and the screensaver, each put back afterwards.
- Dragonbane from your own books, read by your agent: `make rules` with the `solo-rules-import` skill, `solo extract`, `solo inventory` and `solo audit`, and the solo rules of Alone in Deepfall Breach when you have that book.
- The Red Tusk Hall and Ragna, this project's own adventure and hero for Dragonbane.
- Adventures from a PDF or a Foundry export, with the `solo-import` skill (`make adventure`).
- The website, in `site/`.
