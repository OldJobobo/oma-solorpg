# Security

oma-solorpg runs your coding agent on text you didn't write: adventures and packs you import, or download from someone else, and the campaigns built from them. A pack that can make the GM do more than play the game is a security problem, and so is anything that reaches the player's files.

## Reporting

Report it privately, through GitHub's private vulnerability reporting: open the repository's Security tab and choose Report a vulnerability. Don't open a public issue with the details, and don't post a crafted pack anywhere public.

If the Security tab offers no way to report, private reporting hasn't been switched on yet. Open an issue that says only that you have a security problem to report, with no details, and the maintainer will switch it on and answer there.

Say what you ran, on which commit (`git rev-parse --short HEAD` in the plugin folder), and the smallest pack or adventure that shows it. A pack made for the report should be made up: it doesn't need anything from a book.

## What counts

- Adventure or pack text that gets the GM to run a command it isn't allowed (anything but the play commands `solo` lets a GM turn run), to read a file outside the campaign and the skill, or to write one. Under Codex only the last counts, a write outside the campaign folder: Codex has no list of allowed commands and its sandbox reads anywhere, so a Codex GM can run any command in the campaign folder, clear `SOLO_BOOK` to run the player's own (`solo strike`, `solo prefs`) or write the campaign's log. [The Book](README.md#the-book), in the README, says how each agent's turn is held.
- A file a pack loads as its content (an image, a rules page, a table, a person, any file it names) that is read from outside the pack's folder. `extends` names a pack, which can be anywhere (a folder relative to this one, or a pack's name), and is not one of these.
- A crafted pack or campaign that leaves the desktop changed after the game: border colours, the screen shader, the screen temperature, the screensaver, after `solo desk restore` has run.
- Anything that sends the player's files, or the words of their books, somewhere they didn't ask: into a `solo report` meant for posting, or over the network.

The GM getting a rule wrong, forgetting a fact or leaking an adventure's secret to the player goes in an ordinary issue, with the [form for the GM](https://github.com/cabral/oma-solorpg/issues/new?template=gm-did-something-wrong.yml).

## Which versions

Fixes go on `main` and into the next release. The README's install line pins a release's commit and moves when the next one is tagged, so a security fix reaches it with its release, and that release's notes in [CHANGELOG.md](CHANGELOG.md) say so. Until then the fix is on `main` only: 0.4.0's, for one, aren't in the commit the README pins until 0.4.0 is tagged.
