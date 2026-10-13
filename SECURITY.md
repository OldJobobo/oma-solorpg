# Security

oma-solorpg runs your coding agent on text you didn't write: adventures and packs you import, or download from someone else, and the campaigns built from them. A pack that can make the GM do more than play the game is a security problem, and so is anything that reaches the player's files.

## Reporting

Report it privately, through GitHub's private vulnerability reporting: open the repository's Security tab and choose Report a vulnerability. Don't open a public issue with the details, and don't post a crafted pack anywhere public.

If the Security tab offers no way to report, private reporting hasn't been switched on yet. Open an issue that says only that you have a security problem to report, with no details, and the maintainer will switch it on and answer there.

Say what you ran, on which commit (`git rev-parse --short HEAD` in the plugin folder), and the smallest pack or adventure that shows it. A pack made for the report should be made up: it doesn't need anything from a book.

## What counts

- Adventure or pack text that gets the GM to run a command it isn't allowed (anything but the play commands `solo` lets a GM turn run), to read a file outside the campaign and the skill, or to write one.
- A path in a pack (an image, a rules page, an `extends`, any file it names) that reaches outside the pack's folder.
- A crafted pack or campaign that leaves the desktop changed after the game: border colours, the screen shader, the screen temperature, the screensaver, after `solo desk restore` has run.
- Anything that sends the player's files, or the words of their books, somewhere they didn't ask: into a `solo report` meant for posting, or over the network.

The GM getting a rule wrong, forgetting a fact or leaking an adventure's secret to the player goes in an ordinary issue, with the [form for the GM](https://github.com/cabral/oma-solorpg/issues/new?template=gm-did-something-wrong.yml).

## Which versions

Fixes go on `main` and into the next release. The README's install line pins a commit; a security fix moves that pin, and the release notes in [CHANGELOG.md](CHANGELOG.md) say so.
