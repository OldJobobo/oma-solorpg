# Book selection examples

These are real offscreen renders of this branch's Book components, driven by `QTest` under PySide6 6.11.2 with Qt's software renderer. They are not screenshots of a player's campaign and do not invoke an agent.

- `drag-copy-paste.gif`: drag across formatted narration, open the real Copy menu, and paste the resulting plain text into the real composer. The generator asserts the exact clipboard/composer text and that no message was sent.
- `copy-result.png`: still frame of that final paste, for readers who prefer a non-animated example.
- `selection-holds-stream.gif`: incoming narration is simulated while a word remains selected. The generator asserts the rendered document, selection and scroll position stay unchanged, then that Escape displays the latest text.
- `codex-selection.png`: cropped Codex from the existing project-owned Bell Under the Hill fixture; selecting Tam's name and copying it is asserted.

Captions and pointer rings are demonstration annotations, not new Book controls. The captures are cropped to the actual passage/composer or Codex area; no before/after styling comparison is implied.

The Lantern Road, Riverside Landing, Merrin and the dialogue are invented for these examples. The existing `scenario.play_ironsworn` fixture supplies a valid sheet from the already-credited bundled CC BY 4.0 system data; the animated crops show only invented prose and existing controls. The Codex uses this repository's own example NPCs, not Ironsworn's non-commercial setting material. No purchased book extracts, book artwork, private campaign content or desktop clipboard data is included.

To regenerate in a throwaway HOME/XDG environment:

```sh
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python3 tests/qml/selection_visuals.py docs/images/book-selection
```

The script forces an offscreen clipboard and 1x scale, isolates its campaign pointer/library, and requires `ffmpeg` only for generating these GIFs. The committed animations were encoded at 12 fps with a 128-color palette using ffmpeg 9.0.2. `ffmpeg` is not needed by the plugin or normal tests.
