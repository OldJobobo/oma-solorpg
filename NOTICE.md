# Notice

## Dragonbane

This game is not affiliated with, sponsored, or endorsed by Fria Ligan AB. This Supplement was created under Fria Ligan AB's Dragonbane Third Party Supplement License.

oma-solorpg is a third-party supplement for Dragonbane (first edition, Fria Ligan AB, 2023), published as a virtual tabletop module under the [Dragonbane Third-Party Tabletop Module License, version 1.1](https://freeleaguepublishing.com/wp-content/uploads/2026/03/Dragonbane-License-Agreement-version-1.1.pdf). The notice above is the one that license recommends in its section 9, word for word: the supplement license it names is this one. To play Dragonbane it requires the Dragonbane core game; Ironsworn (below) needs no book. It is not a video game.

## What is Free League's

Dragonbane, Drakar och Demoner, the game's terms and the "A Supplement for Dragonbane" logo (`assets/a-supplement-for-dragonbane.png`, unmodified from Free League's logo pack) belong to Fria Ligan AB. This project uses the game's terminology (attribute, skill, condition and kin names), refers to its books by title and page, and uses the logo, as the license allows.

It does not include any of Free League's text, tables, rules or art. The rules the engine runs are built by each player from their own copy of the books (`make dragonbane`, or an agent for what that doesn't know) and stay on their machine, in `~/Games/solo`. The importers in `solo/books` hold where things are in a book (its bookmarks) and how to read them, never the book's words or numbers; a test (`tests/test_no_book_text.py`) looks for any run of eight words of a book, and any stretch of a table's numbers, in any file of the repository, against fingerprints of the books (salted hashes, no text) and against the books themselves when they are at hand. Nothing built from a Dragonbane book belongs in this repository, and pull requests that add any will be refused.

## Ironsworn

This work is based on Ironsworn, created by Shawn Tomkin, and licensed for our use under the Creative Commons Attribution 4.0 International License (https://creativecommons.org/licenses/by/4.0/).

That is the credit [Tomkin Press asks for](https://tomkinpress.com/pages/licensing), word for word.

`packs/ironsworn` holds Ironsworn's moves (35), oracle tables (33) and assets (78), which Shawn Tomkin published under that license. They were converted from [Datasworn](https://github.com/rsek/datasworn) (version 0.0.10), the rulebook as JSON, made by rsek. Datasworn's own code and schema are under the MIT License, and the text it holds keeps the license of the book it comes from, marked on each object; what this pack takes is marked CC BY 4.0.

`solo import datasworn` made these changes to the text:

- Each link to another part of the book is replaced by the words it linked.
- Where the text tells you to roll on a table, a pointer is put in its place, like "(roll it with solo table pay_the_price)". A link to a table that wasn't imported is removed.
- A row that sends you on to another table says so with `then`. When that table wasn't imported, the row loses the link, and the importer lists it.
- Bold is marked `**like this**`.
- A table is written as TOML, and a table that belongs to a group is named after the group first. Each move, table and asset is a file of its own, carrying its page in the book and the credit above.
- The ask-the-oracle tables are not tables here: their odds are the engine's (`[oracle]` in `system.toml`), and the importer prints the numbers they give so a difference shows.

Apart from that, the book's text is kept as written.

What isn't here: the rest of Ironsworn's text (its NPCs, the atlas, the truths) is licensed CC BY-NC-SA by Tomkin Press, which is for non-commercial use only and asks the same license of anything built from it, so the importer takes only what is marked CC BY and says what it left out. Tomkin Press's images, icons, trade dress and other design elements aren't licensed for use, and this project uses none; it is not an official Tomkin Press or Ironsworn product.

## What is this project's

The engine, the plugin, the skills, The Red Tusk Hall, The Bell Under the Hill (its text and its people are original), the heroes Ragna, Hrafna, Torvald and Eydis, the hero name lists, the text portraits, the `system.toml`, `creation.toml` and pre-made heroes of `packs/ironsworn`, and the made-up test rules in `tests/fixtures` are this project's own, under the MIT License ([LICENSE](LICENSE)).

That license covers the code and this project's own content. It does not cover Dragonbane, its terms or the "A Supplement for Dragonbane" logo, which belong to Fria Ligan AB and are used under its license (above).

## Generative AI

The game master is a generative AI: your coding agent writes the story as you play.

Much of this project was written with an AI coding agent, including its code, the text of The Red Tusk Hall and The Bell Under the Hill and the test adventures, the hero names and the text-drawn portraits.
