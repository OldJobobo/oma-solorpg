# The website

oma-solorpg's page: plain HTML, CSS and JavaScript, no build step. `make site` serves it on http://localhost:8000, and `.github/workflows/pages.yml` publishes this folder to GitHub Pages on every push to `main` that touches it (set Pages to "GitHub Actions" once, in the repository's settings).

## The trailer

The trailer is `media/oma-solorpg-45s.mp4`. The page lists only the cuts that exist: a 15-second cut was planned, and its tab and panel came out because the file was never made and the page asked for it on every load. To add a cut, put its file in `media/` and give it a tab and a panel in `index.html` beside the 45-second ones; with two, the tabs show. A cut whose file goes missing loses its tab, and with none left the player shows a placeholder with the path the first cut is waiting for. H.264 in an MP4 plays everywhere; keep each under about 20 MB so the page stays quick (`ffmpeg -i in.mp4 -c:v libx264 -crf 24 -preset slow -movflags +faststart -c:a aac -b:a 128k out.mp4`).

## Where the pictures come from

Every screenshot is the plugin's real QML, rendered offscreen against real engine state, not a mockup:

- The Red Tusk Hall (`img/red-*`) with `tests/qml/render.py`'s scenario, the adventure this repository ships.
- The Sinking Tower and Alone in Deepfall Breach (`img/tower-*`, `img/breach-*`, `img/table-*`) from the author's own packs, compiled from books the author owns with `make rules` and `make adventure`. The packs are not in this repository. The GM's lines in them were written for the screenshots, and a monster's attack table text was kept out of frame, but some numbers from the books are in frame: `tower-fight`, `tower-codex` and `tower-dragon` show the HP and armor of a monster from the Quickstart and its pre-generated mage's HP, WP and a skill value, and `breach-fight` shows the cultists' HP and attack roll, which come from the solo booklet's simple NPC templates.
- `img/extract-table.webp` is `solo extract`'s picture of a table page from the made-up rulebook in `tests/test_rules_import.py`.

The faces in `art.js` come from `solo/portrait.py` and `packs/dragonbane/art.toml`, one per kin and mood. Regenerate the file rather than editing it.

## Before publishing

- `og:url` and `og:image` in `index.html` assume `https://cabral.github.io/oma-solorpg/`. Change both for another address.
- The shelf section shows Free League's adventures by name, with screenshots of play. It credits them and says the packs stay private; check it against the license's terms before it goes out.
- CONTRIBUTING's rule allows no numbers from any book in the repository, quickstarts included, and the screenshots above with a book's numbers in them break it. Retake them with those numbers out of frame, or from The Red Tusk Hall or The Bell Under the Hill.

There is also a door somewhere on the page that wasn't there before. Its code is in `secret.js`.
