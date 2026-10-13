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

<!-- fixes from the review land here -->

## 0.3.0

The first version, 2026-09-27.

- `solo`, the engine: dice, the `d20-under` and `d6-pool` families, character creation, the campaign as an event log, the oracle with random events and a chaos factor, fights, dying and advancement, and the memory of a long campaign (consequences, `solo recall`, `solo resume`).
- The plugin: the d20 in the bar, the Table, and the Book, with Claude Code or Codex as the GM, run headless a turn at a time at the pace you set. Dice moments, voices, text portraits, torches, the codex, omens and the Hall of the Fallen.
- Desktop effects (`solo desk`): borders, screen shaders, sounds, candlelight, notifications and the screensaver, each put back afterwards.
- Dragonbane from your own books, read by your agent: `make rules` with the `solo-rules-import` skill, `solo extract`, `solo inventory` and `solo audit`, and the solo rules of Alone in Deepfall Breach when you have that book.
- The Red Tusk Hall and Ragna, this project's own adventure and hero for Dragonbane.
- Adventures from a PDF or a Foundry export, with the `solo-import` skill (`make adventure`).
- The website, in `site/`.
