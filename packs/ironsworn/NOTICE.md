# Ironsworn

This work is based on Ironsworn, created by Shawn Tomkin, and licensed for our use under the Creative Commons Attribution 4.0 International License (https://creativecommons.org/licenses/by/4.0/).

`packs/ironsworn` holds Ironsworn's moves (35), oracle tables (33) and assets (78), which Shawn Tomkin published under that license. [Datasworn](https://github.com/rsek/datasworn) (version 0.0.10) publishes them as data, with the license of each object marked, and the pack's files were converted from it.

`solo import datasworn` made these changes to the text:

- Each link to another part of the book is replaced by the words it linked.
- Where the text tells you to roll on a table, a pointer is put in its place, like "(roll it with solo table pay_the_price)". A link to a table that wasn't imported is removed.
- A row that sends you on to another table says so with `then`. When that table wasn't imported, the row loses the link, and the importer lists it.
- Bold is marked `**like this**`.
- A table is written as TOML, and a table that belongs to a group is named after the group first. Each move, table and asset is a file of its own, carrying its page in the book and the credit above.
- The ask-the-oracle tables are not tables here: their odds are the engine's (`[oracle]` in `system.toml`), and the importer prints the numbers they give so a difference shows.

Apart from that, the book's text is kept as written.

What isn't here: the rest of Ironsworn's text (its NPCs, the atlas, the truths) is licensed CC BY-NC-SA by Tomkin Press, which is for non-commercial use only and asks the same license of anything built from it, so the importer takes only what is marked CC BY and says what it left out. Tomkin Press's images, icons, trade dress and other design elements aren't licensed for use, and this project uses none; it is not an official Tomkin Press or Ironsworn product.

`moves/`, `tables/` and `assets/` are generated: `solo import datasworn <classic.json> --out packs/ironsworn` rewrites them, and a fix belongs in the importer (`solo/datasworn.py`). `system.toml`, `creation.toml` and `characters/` are this project's own, under the MIT License. The project's [NOTICE.md](../../NOTICE.md) has the rest.
