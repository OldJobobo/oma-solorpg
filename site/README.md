# The website

oma-solorpg's page: plain HTML, CSS and JavaScript, no build step. `make site` serves it on http://localhost:8000, and `.github/workflows/pages.yml` publishes this folder to GitHub Pages on every push to `main` that touches it (set Pages to "GitHub Actions" once, in the repository's settings).

## The trailer

The trailer is `media/oma-solorpg-45s.mp4`. The page lists only the cuts that exist: a 15-second cut was planned, and its tab and panel came out because the file was never made and the page asked for it on every load. To add a cut, put its file in `media/` and give it a tab and a panel in `index.html` beside the 45-second ones; with two, the tabs show. A cut whose file goes missing loses its tab, and with none left the player shows a placeholder with the path the first cut is waiting for. H.264 in an MP4 plays everywhere; keep each under about 20 MB so the page stays quick (`ffmpeg -i in.mp4 -c:v libx264 -crf 24 -preset slow -movflags +faststart -c:a aac -b:a 128k out.mp4`).

## Where the pictures come from

Every screenshot is the plugin's real QML, rendered offscreen against real engine state, not a mockup:

- The Red Tusk Hall (`img/red-*`) with `tests/qml/render.py`'s scenario, the adventure this repository ships.
- `img/table-new.webp` (and the Table in `og.png`) is the New adventure screen on the author's machine, with a hero rolled at random.
- `img/extract-table.webp` is `solo extract`'s picture of a table page from the made-up rulebook in `tests/test_rules_import.py`.

The faces in `art.js` come from `solo/portrait.py` and `packs/dragonbane/art.toml`, one per kin and mood. Regenerate the file rather than editing it.

## Before publishing

- `og:url` and `og:image` in `index.html` assume `https://cabral.github.io/oma-solorpg/`. Change both for another address.
- The shelf section shows Free League's adventures by name. It credits them and says the packs stay private; check it against the license's terms before it goes out.
- CONTRIBUTING's rule allows no numbers or text from any book in the repository, quickstarts included, and that covers pictures. Take a screenshot from The Red Tusk Hall or The Bell Under the Hill, not from a pack built from a book: a fight shows the monster's numbers, the codex the book's own lines about its people, and a title card the scene faded under it. That is why the shelf has no screenshots: the ones of The Sinking Tower and Alone in Deepfall Breach showed a book's numbers, and came out. They are still in the repository's history, from its first commit; taking them out of it means rewriting that history, which is the maintainer's call.

There is also a door somewhere on the page that wasn't there before. Its code is in `secret.js`.
