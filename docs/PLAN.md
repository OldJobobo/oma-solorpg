# oma-solorpg: design

How the engine, the plugin and the packs fit together, and why. The pack formats are in [PACK_FORMAT.md](PACK_FORMAT.md), importing books in [INGESTION.md](INGESTION.md), what comes next in [ROADMAP.md](../ROADMAP.md).

Contents: [Goal](#goal) · [Product](#product) · [The Book](#the-book) · [Principles](#principles) · [Architecture](#architecture) · [Frontend: the plugin](#frontend-the-plugin) · [Backend: the engine](#backend-the-engine) · [Turn protocol](#turn-protocol) · [Layout](#layout) · [Formats](#formats) · [CLI](#cli) · [Verification](#verification) · [Risks and open questions](#risks-and-open-questions) · [Decisions](#decisions) · [Open](#open)

## Goal

An AI game master for solo tabletop play that runs natively on Omarchy.

- The player writes to the GM in the Book, a story window the plugin owns. Omarchy's default coding agent (Claude Code, Codex or Pi) runs headless behind it as the GM, one turn at a time; another agent opens in a terminal instead.
- A local engine, `solo`, owns dice, rules resolution, character creation and campaign state.
- An omarchy-shell plugin is the table: a bar button and a docked panel where the player starts games, makes characters, rolls, rests and watches the state.
- Content comes from material the player owns (PDFs read by the importers or by an agent, Foundry module exports), compiled once into local packs, or from free rules that ship in the repository.

Two games play today: Ironsworn, whose free rules ship here, so a fresh install plays with no book, and Dragonbane, built from the player's own books. Other games follow, so every design choice has to work for more than one system.

## Product

### Who it is for

A solo tabletop player on Omarchy who owns the game and wants to play tonight: no prep, no flags, no config files. They are comfortable talking to an agent but should never need to know which `solo` command exists.

A second, rarer user is the author: the same person on another evening, importing an adventure from a PDF or a Foundry export. Authoring may use the terminal and the agent; playing may not.

### What done feels like

1. **First game in two minutes, clicks only.** From the bar icon: New adventure, pick the adventure, take the pre-made hero or roll one, Begin. The Book opens and the GM narrates the first scene.
2. **Every pure mechanic is one click.** Skill and attribute rolls with boons and banes, pushes, rests, the oracle. Narration and decisions stay with the GM in the Book.
3. **Resume is one click.** Campaigns are listed with the hero, the scene and when they were last played.
4. **No developer output in front of the player.** An error is one plain sentence with the next step, shown where the click happened. Never a traceback or a usage string.

### Journeys

| Journey | Steps | Surface |
|---|---|---|
| First launch | Click the d20 in the bar. The panel opens on Home: "No campaigns yet" and a New adventure button. | bar, panel |
| New adventure | Pick an adventure card (title, system, a spoiler-free summary). Pick a character: a pre-made hero, or Random with optional kin, profession and age, a name field and a Reroll button, with a live sheet preview. Begin. | panel |
| Play a turn | Type to the GM. The GM rolls through `solo`, or the player clicks a skill on the sheet. Failed roll: push buttons appear. The log and meters update as it happens. | Book + panel |
| Rest | Round, stretch or shift rest buttons. Time passes, so hidden clocks may tick. The GM sees it in the log. | panel |
| Ask the oracle | Type a yes/no question, pick the odds, Ask. The answer shows under the question and in the log, with a random event when one comes up. Meaning gives two words for open questions. | panel |
| Fight | The GM starts it. The table shows initiative, the foes' HP and the hero's weapons. Pick a foe, click a weapon to attack. A foe's hit shows in red with Evade, Parry and Take it. | Book + panel |
| Dying | At 0 HP the only roll left is Death roll, with the count toward rallying or dying. Death ends the campaign and the Home card says so. | panel |
| End a session | The GM asks the end-of-session questions and marks skills; Roll advancement (or the GM) rolls them. | Book + panel |
| Resume | Home lists campaigns with the first line of the GM's last message. Click one: the table shows that message in full under Where you left off. Open the GM, and its first message is the same text, word for word. If the GM window is already open, it gets focus instead of a second one. | panel |
| Bring your own adventure | `solo import ...` plus the `solo-import` skill (terminal, agent). The adventure then appears on the New adventure screen. | terminal |

### Scope

Built, the product: the library, `solo new <adventure>` with defaults, character creation (pre-made, random and guided), rests, the panel's Home, New adventure and Table screens, a bar widget, and a GM button that focuses an open session.

Built, the game: stakes (death rolls at 0 HP), combat (initiative, attacks with damage through armor, foe attacks by skill or monster table, evade and parry, ranged attacks and their ranges, weapon durability, monster traits, a Dragon's choices), spells and WP, heroic abilities, journeys and encumbrance, oracle surprises (random events, scene checks, a chaos factor, meaning words), advancement marks, and the player's table settings (tone, lines, veils).

Built, the Book: a story window the plugin owns, with the default agent run headless behind it (`solo gm`), so the player never sees a coding agent's tool calls. Dice moments, scene title cards, voices (passive skill checks that speak up), a text portrait that follows the hero's state, torches that burn down, fights drawn as a still scene, a codex with unknowns blanked out, omens, the Hall of the Fallen, and desktop effects (`solo desk`: borders, screen shaders, sound, candlelight, notifications, screensaver).

Built, a game with no book: the `action-roll` family and Ironsworn with its starter adventure, The Bell Under the Hill, so first launch plays with clicks only.

Next: choosing trained skills by hand in the builder, a character roster, a settings entry for SOLO_HOME.

Later: adapters for more agents in the Book (Claude Code, Codex and Pi stream and resume today), the importer from the panel, other families' builders, publishing.

### UX rules

- One obvious next action per screen, visually primary. Everything else is secondary or hidden until it applies (push buttons appear only after a pushable failure).
- The panel never writes campaign files. It runs `solo` and reads `state.json`, so the engine is the single writer and its lock settles races with the GM.
- Buttons exist only for deterministic mechanics. Anything that needs judgement (damage from a narrated hit, an NPC's reaction) goes through the GM.
- The player sees what the GM sees about dice: every roll lands in one log, whoever clicked or typed it.
- GM-only information never reaches the panel: hidden clocks, the tables their ticks roll, scene secrets.
- Words from the fiction, not the engine: "Begin adventure", "Open the GM", "Stretch rest". No ids, flags or JSON on screen.

## The Book

A coding agent in a terminal shows its tool calls, permission prompts and JSON between the lines of the story. The Book takes the story out of the terminal.

```
 player writes in the Book             solo gm turn (detached)                 agent, headless
+---------------------------+  runs   +-------------------------------+  runs  +------------------------+
| BookView (plain QtQuick)  | ------> | records the player's words    | -----> | claude -p stream-json  |
| story from state.json     |         | streams text to turn.json     | <----- | codex exec --json      |
| live text from turn.json  | <------ | records the GM's final words  |  JSON  | runs solo like any GM  |
+---------------------------+  reads  +-------------------------------+        +------------------------+
```

- `solo gm turn [text]`: one exchange. It takes `.solo/turn.lock` (one turn at a time), records the player's words (`said`), runs the agent with the campaign as its working folder, and rewrites `.solo/turn.json` as the agent works: `status` (thinking, writing, done, error, stopped), `text` (the narration so far; text before a tool call is dropped as thinking aloud), `doing` (reading the table, rolling the dice, writing it down), `player`, `error`. The final message is recorded as the GM's `said`. The agent's session id is kept in `.solo/agent.json`; a new or lost session's first prompt carries what `solo resume --book` and `solo scene` print, so the campaign stays the memory and the GM spends no model call reading it.
- `solo gm pace [quick|normal|careful]`: the player's, kept in `$XDG_STATE_HOME/solo/gm.json` for every campaign (the default is normal). Each turn passes it to the agent as an effort level: `--effort low|medium|high` for Claude Code, `-c model_reasoning_effort=...` for Codex, `--thinking low|medium|high` for Pi. Without it, Claude Code would use the effort the player set for coding.
- Claude Code ignores a project's permissions until its folder is trusted interactively, so the adapter passes the GM's allowlist with `--allowedTools`. Hooks still record the transcript; recording twice is harmless (`say` drops a repeat).
- The GM starts bare: `--strict-mcp-config` and `--no-chrome` leave out the player's own MCP servers and claude.ai connectors (they took two of the three seconds a turn spent starting, and have no place beside adventure text), and `--tools Bash,Read` keeps two of Claude Code's tools, with the skill's folder readable (`--add-dir`), which cut a turn's input by more than half.
- Other agents keep the terminal (`solo play --terminal`); the Book shows their story as it is recorded, if they record it (`solo say`).
- `solo play` opens the Book when the plugin is installed and the agent is supported, and starts the opening turn when nothing has been said yet.

What the Book shows comes from state.json, derived by the engine: `story` (the last 150 beats: `gm` and `player` speech, `roll` with its outcome, `voice`, `hit`, `hurt`, `foe`, `scene`, `omen`, `oracle`, `fight`, `event`, `light`, `end`), `portrait` (`lines`, `mood`, `wounds`, `tint`), `figures` (`hero` and each foe's small figure), `faces` (a picture per NPC met), `codex` (people met: `role`, `faction`, `attitude`, `fate`, `memories`, `known` wants and fears, learned `secrets`, a count of what is `unknown`, `stats` once fought), `route` (scenes visited, each with how many ways on are unexplored), `light` (with `left`), `dark`, `voices` (heard in this scene), `fallen` (the epitaph), and `combat.last` (the last exchange). Nothing GM-only: an unknown is a count, a place not reached is never named, a failed voice never appears.

Voices are scene data (`[[scenes.<id>.voices]]`: `skill`, `text`, optional `when`, `clue`, `boons`, `banes`), rolled quietly on entering; `solo voice` lets the GM raise one. Light sources are system data (`[light.torch]`: `item`, `lasts`). A clock with `omen = true` stays hidden but its tick results reach the player. Portraits are art data (`art.toml`): a head per kin with slots (`L R` eyes, `l r` brows, `mmmm` mouth, `w` wounds, `a` age), headgear per profession, a mood per condition.

The desktop effects (`solo desk`) are the plugin's, not the engine's: they never touch a campaign. Each keeps what it replaced in `$XDG_RUNTIME_DIR/solo-play` (or the screensaver text beside itself) and puts it back; `solo desk restore` undoes everything, and the plugin runs it when it loads. Hyprland borders go through `hyprctl eval 'hl.config(...)'` (with `hyprctl keyword` for older Hyprland), read back with `getoption` first; when the original can't be read the effect is skipped. Candlelight uses hyprsunset the way Omarchy's night light does. The screen effects are Hyprland screen shaders (`solo/shaders/*.frag`, GLSL ES 3.0): each step of a flash bakes its level into a file of its own in the runtime folder and puts it up with `decoration:screen_shader`, the dying rim is held still, baked with how weak the hero is (none use Hyprland's `time` uniform: it only moves when something else redraws, and Hyprland warns that it needs damage tracking off), and the player's own shader (or none) goes back afterwards. A newer moment takes the screen over from an older one by a token, so two never fight over it. Sounds are synthesised with the standard library into `$XDG_CACHE_HOME/solo-play/sounds` (`solo/sounds.py`); `solo desk sound` bakes them and says what plays them, and the plugin plays them itself so the dice land with the Book's to the millisecond. Switches live in `$XDG_STATE_HOME/solo/fx.json`.

The manifest sets `keepLoaded`, so the panel entry (the Table, the Book and the watcher) stays alive between summons and reacts to the game with both windows closed.

## Principles

- Mechanics come from code, narrative facts from the adventure text, and state only from validated commits. The model interprets and narrates.
- The engine never calls a model and never touches the network. The Book's adapter (`solo/gm.py`) runs the player's agent, which does; it has no rules in it. It is standard-library Python (3.11+, for `tomllib`) so the plugin runs on a stock Omarchy install, where `omarchy plugin add` cannot install dependencies.
- Every change is an event appended to `events.jsonl`. `state.json` is derived from the log and can be rebuilt at any time.
- Multi-system by construction: one resolver per mechanics family, one data pack per game. Character creation is data too (`creation.toml`); a system without it still plays from pre-made or imported characters.
- Agent-agnostic: a CLI plus skills, the same way Omarchy wires `diagnose-crash` into every agent. MCP is optional and can wrap the CLI later.

## Architecture

```
 player types here                      player clicks here
+-----------------------------+        +-------------------------------------+
| the Book: the story         |        | bar: d20 button (left: table,       |
| solo gm turn runs the agent |        |      right: the Book)               |
| headless: claude/codex/pi,  |        | panel: Home | New adventure | Table |
| skill solo-gm, cwd campaign |        | sheet, rolls, rests, oracle, clocks |
+--------------+--------------+        +------+---------------+--------------+
               |                              ^               |
   the agent runs solo ...         watches state.json    runs solo ... (JSON out)
               v                              |               v
+----------------------------------------------------------------------+
| solo (stdlib Python, no LLM, no network)                             |
|   dice + resolvers    d20-under, d6-pool, action-roll                |
|   packs               system pack (+ creation.toml), adventure pack  |
|   library             bundled packs + ~/Games/solo (yours)           |
|   creation            pre-made, random or guided characters          |
|   campaign            events.jsonl -> state.json, lock, rests        |
+----------------------------------------------------------------------+
               ^ one-time import
   PDFs (solo import book, or the agent) / Foundry "Export Data" JSON / Datasworn
```

Two surfaces, both the plugin's: the Book for the conversation, the Table for everything clickable. The Table docks on the right with an exclusive zone, and the Book opens beside it. The agent has no window of its own: it runs headless for each turn. An agent the Book can't drive opens in a terminal instead (`solo play --terminal`), with the skills and the same campaign folder, and the Book shows what that agent records.

## Frontend: the plugin

`manifest.json` declares two kinds: `panel` (`Panel.qml`) and `bar-widget` (`BarWidget.qml`). Both are plain QML on the shell's own kit (`qs.Commons`, `qs.Ui`: Button, TextField), so the plugin follows the Omarchy theme and needs nothing installed.

### Bar widget

A d20 glyph (Nerd Font `md-dice_d20`). Left click toggles the panel; right click runs `solo play` (open or focus the GM).

### Panel screens

The panel keeps a `view` of `home`, `new` or `table`. It opens on `table` when a current campaign exists, otherwise on `home`. `omarchy-shell shell summon cabral.oma-solorpg '{"view":"new"}'` opens a given screen.

**Home**
- Header: oma-solorpg, close.
- Continue: one card per campaign (title, hero, scene, last played). The current one is marked. Click: `solo use <dir>`, then Table.
- Primary: New adventure.

**New adventure** (one scrolling page, three numbered sections)
1. Adventure: cards from `solo library` (title, system, summary). One is selected.
2. Character, for the adventure's system:
   - Pre-made heroes as buttons (from `packs/<system>/characters/`).
   - Random: one row of choices per creation table (Kin, Profession, Age; School or Craft appears when Mage or Artisan is picked). Each row starts on "Any". A Name field (empty means a name from the kin's list). Reroll.
   - A preview of the sheet: name, kin/profession/age, attributes, HP/WP, trained skills, abilities, gear. It comes from `solo character ... --seed N`, so the preview is exactly the hero Begin creates.
3. Primary: Begin adventure: `solo new <adventure> --character <choice> --seed N [--name ...] --play`. On success the panel shows Table and the GM window opens.

**Table**
- Header: campaign title, scene and elapsed time; Campaigns (back to Home); Open the GM.
- Character: name and kin/profession, attributes, HP and WP meters, conditions (lit when held), abilities and ratings (movement, damage bonus).
- Roll: Boons and Banes steppers, then the skills as buttons (trained first, the rest under "Other skills"), plus the attributes. Click rolls `solo check <skill> --boons N --banes N` and clears the steppers.
- Last roll: the result in words and dice. After a pushable failure, the push buttons (Dragonbane: one per condition not held).
- Rest: one button per rest in the system pack. A rest already taken this shift is disabled with the reason.
- Oracle: question field, odds buttons, Ask. The latest answer shows below.
- Fight (while one is on): round and initiative, a card per foe with its HP (click to target, Attacks you to roll its attack), the hero's weapons as attack buttons, and when a hit is coming, Evade, Parry per weapon, Take it. Next round.
- Dying: the tally and a Death roll button, in place of the roll buttons. Ended: a card with how the adventure ended.
- Marked skills carry a dot; Roll advancement appears while any are marked.
- Clocks (visible ones), People met, Promises, Clues, Table settings, Log (last 14, newest first).
- Errors: one red line under the section that caused them.

### Engine and panel contract

The panel reads two files and runs one program:

- `$XDG_STATE_HOME/solo/current`: path of the current campaign (written by `new`, `use`, `play`).
- `<campaign>/state.json`: `title`, `scene_title`, `time`, `pc` (`name`, `info`, `attributes`, `skills` with `value`/`name`/`attribute`/`trained`, `tracks`, `conditions`, `items`, `abilities`, `ratings`, `marks`, `dying` with `successes`/`failures` or null, `dead`), `labels` (`attributes`, `tracks`, `conditions`, `push`, `rests`, `likelihood`, `dying` with `rally`/`die`, `advancement`), `rests` (when each was last taken), `last_check`, `clocks`, `npcs`, `promises`, `clues`, `chaos`, `combat` (`round`, `order`, `foes` with `hp`/`max`/`armor`/`down`, `incoming`) or null, `prefs` (`tone`, `lines`, `veils`), `ended`, `kit` (carried `weapons`, each with its `condition` (`damaged` or `broken`), and `armor`, derived from the pack when state.json is written), `load` (`carried`, `capacity`, `over`), `choice` (a Dragon waiting: `kind`, `options`, `target`), `magic` (a hero with spells: `track`, `max_power`, `limit`, `ready`, the dice the `body` can give, and `spells` with `name`, `rank`, `school`, `trick`, `prepared`, `power`, `cost`, `damage`, `heal`, `reaction`), `abilities` (what the hero has of the pack's: `name`, `cost`, `afford`, and `use`: `attack`, `defend` with `on` the parry or the dodge, `rest`, `round`, `journey`, `alone`, or none for a passive one), `log`.
- `bin/solo` from the plugin folder (never PATH, so the panel works before setup): `library`, `character`, `new`, `use`, `play`, `check`, `push`, `rest`, `ask`, `attack`, `enemy`, `defend`, `fight --round`, `death-roll`, `advance`. Queries print JSON on stdout; errors print one line on stderr with exit status 1.

Anything the panel shows is either in `state.json` or in `solo library`. If the panel needs a new fact, the engine adds it to one of those, and the panel does not compute rules.

### Keyboard

The panel window uses on-demand keyboard focus: clicking the Name or Oracle field focuses it, and Escape closes the panel. Everything else is mouse-first.

## Backend: the engine

### Library

Bundled content lives in the repository (the plugin folder). The player's own content and campaigns live under `SOLO_HOME` (default `~/Games/solo`), outside the repository so packs built from purchased books never get published.

```
<repo>/packs/<system>/              bundled system packs (Dragonbane: names only)
<repo>/packs/<system>/characters/   pre-made heroes
<repo>/examples/<adventure>/        bundled playable adventures (red-tusk)
~/Games/solo/systems/<system>/      your system packs (built from books you own)
~/Games/solo/adventures/<id>/       your adventures (imports)
~/Games/solo/campaigns/<id>/        campaigns created by `solo new`
```

A name resolves in `~/Games/solo` first, then in the repository. A path always works. `campaign.toml` keeps absolute pack paths; if a pack moved (the plugin reinstalled elsewhere), the engine finds it again by folder name in the library.

Every command is a process of its own (the Table runs one per click, the GM one per roll or commit), so nothing it reads may cost much to read again. Two caches keep it at about 55 ms, and both are safe to delete:

- `$XDG_CACHE_HOME/solo/toml-<python>.marshal` (default `~/.cache/solo`): every pack's TOML files as parsed, each kept while its file keeps its size and modification time. A file changed in the last two seconds is parsed afresh, so a second save in the same clock tick is never missed. A Dragonbane campaign reads some four hundred files a command; parsing them was a third of its time.
- `<campaign>/.solo/replay.marshal`: the state and the chronology after the log's first events, so a long campaign doesn't replay its whole log for every command. It stands while those events are the same bytes (their crc32) and the packs and the engine are the ones it was made from, and it is written again once the log has grown fifty events past it. `solo rebuild` replays from the log alone.

`solo library` prints everything the Home and New adventure screens need: systems (name, family, creation tables, pre-made heroes), adventures (id, title, system, summary), campaigns (path, title, hero, scene, last played, current), and `problems`: packs of the player's own that didn't load, and why (a half-built pack is left out, never the whole library).

### Character creation

`creation.toml` holds a rulebook's creation tables as data, in the pack built from the player's book. `solo/creation.py` reads it; no system-specific code.

```toml
attributes = "3d6"               # rolled for each attribute, in system order
attribute_range = [3, 18]
key_swap = true                  # the best roll moves to the key attribute
trained_multiplier = 2           # a trained skill starts at twice its base chance
tracks = { hp = "con", wp = "wil" }

[ratings.movement]               # read off an attribute; adds to a base an option gives
label = "Movement"
attribute = "agl"
table = [[7, -2], [13, 0], [18, 2]]

[choose.kin]                     # picked by the player or rolled on `roll`
label = "Kin"
roll = "1d8"
[choose.kin.options.dwarf]
range = [4, 5]
abilities = ["Stone Sense"]
ratings = { movement = 8 }
# names: from [names] in the bundled creation.toml unless the option has its own

[choose.profession.options.mage]
key = "wil"
then = "school"                  # a follow-up table
```

(Made-up values, from `tests/fixtures/house/creation.toml`. The real tables are the player's book.)

Option keys: `label`, `range`, `attributes` (modifiers), `key`, `skills` + `train` (profession skills, how many trained), `always` (skills always trained), `extra` (free trained skills), `abilities`, `ratings`, `names`, `gear`, `kits` (one is picked), `then`. Gear text can roll: `"{1d8} silver"`.

Order: attributes are rolled first, then the tables. So locking Kin after seeing the rolls keeps the same numbers, and a seed reproduces a character exactly. Skills marked `untrained = false` in `system.toml` (Dragonbane's magic schools) can't be rolled untrained and are only trained through an option's `skills`/`always`.

A character given to `solo new` or `solo character` is one of:

- a file (`.toml` or `.json`, the existing sheet format),
- a pre-made id (`ragna`),
- words naming options (`"dwarf fighter"`, `"elf mage old"`) or `random`, built with `--seed` and `--name`.

Every sheet is normalised the same way: all system skills are present with `value` and `trained`, and `abilities` and `ratings` pass through.

### Rests

Declared per system in `system.toml` and run by `solo rest <id>`:

```toml
[rest.stretch]
label = "Stretch rest"
recover = { hp = "1d8", wp = "1d8" }   # dice, or "max" (made-up values)
heal = 1                               # conditions healed (a number or "all")
time = { stretch = 1 }
limit = "shift"                        # once per shift
```

A rest is a `rest` event whose changes go through the commit validator, so tracks clamp and the time it takes advances clocks (a shift rest in the Red Tusk Hall ticks the ritual).

### Opening the GM

`solo play` links `solo` and the skills if they are missing (the same idempotent links as `solo setup`, so a plugin installed with `omarchy plugin add` works on first click). If a GM is already running for the campaign, it focuses that window. Otherwise it refreshes the campaign's agent files (AGENTS.md and CLAUDE.md are rewritten, `.claude/settings.json` is merged) and launches the default agent in the campaign folder with one fixed prompt: run `solo resume` and do what it says. The launched process carries `SOLO_GM=<campaign>`, and the engine finds that process's window through Hyprland. With no `omarchy-agent`, it says how to start one by hand.

## Turn protocol

```
player text
 -> agent picks ONE intent from what `solo scene` offers (exit, skill, npc)
 -> solo check <skill> [--boons N --banes N]     code: roll, Dragon/Demon, boons/banes
 -> agent reads the scene text, proposes the consequence
 -> solo commit '<json>'                          code: validate, append, derive clocks
 -> agent narrates from what was committed
```

The player acts from the panel too (checks, pushes, rests, oracle). In the Book, each prompt lists what they did since the GM's last message; in a terminal the GM starts every turn with `solo log -n 5`. Either way it narrates what already happened instead of rolling again.

### The transcript and resuming

The campaign keeps the conversation, not the agent. Every GM message and every player message is a `said` event in `events.jsonl` (`by` is `gm` or `player`, with the scene it was said in), in the same order as the rolls. The agent session is disposable: closing its window loses nothing.

- Capture: in Claude Code, the campaign's `UserPromptSubmit` and `Stop` hooks run `solo say --hook`, which records the player's prompt and the GM's last message (from the hook's `last_assistant_message`, or else the transcript file). No model cooperation needed. Other agents record their own replies with `solo say -` and the player's with `solo say --player`, as the skill says. The same words twice in a row from the same speaker are recorded once.
- State: `state.json` has `last_said` (the GM's last message, its seq, time and scene) and `awaiting_player`. Speech stays out of the panel's dice log.
- Resume: `solo resume` prints the GM's last message under "Last said", the events after it ("Since then", hidden ones marked), anything the player said after it, and the four messages before it for context. The GM sends "Last said" back word for word as its first message: no greeting, no recap, no new description. With nothing said yet, it tells the GM to open the adventure.
- The panel shows `last_said` directly, so the player sees the exact text before the agent has loaded.

Resuming the agent's own conversation (`claude --continue` and the like) is not the mechanism: it works for some agents only, `omarchy-agent` hides which one runs, and long sessions get compacted. The transcript carries the exact words; the long memory ([Long campaigns](#long-campaigns)) carries the story.

Open questions ("does the orc leader show up?") go down a fixed ladder:

1. The adventure text decides: the engine evaluates the branch condition.
2. The rules decide: a skill check, with boons or banes from tracked attitude.
3. Neither: `solo ask` rolls the oracle (Dragonbane's fortune chart), tilted by what the state makes likely.

The agent narrates the answer. It never picks it.

## Layout

Repository (also the plugin: `omarchy plugin add` clones it as-is):

```
manifest.json               omarchy-shell plugin manifest (panel + bar widget)
Panel.qml                   the table: Home, New adventure, Table
BarWidget.qml               the d20 bar button
bin/solo                    CLI entry point
solo/                       engine package, standard library only
  dice.py                   dice expressions
  mechanics.py              resolvers per mechanics family (d20-under, d6-pool, action-roll)
  datasworn.py              Ironsworn's moves, oracles and assets from Datasworn, as pack files
  packs.py                  system/adventure packs, validation, branch conditions
  library.py                where packs and campaigns live, and the listing for the panel
  creation.py               character building from creation.toml, pre-mades, files
  campaign.py               event log, state fold, actions, commits, rests, clocks
  foundry.py                Foundry export importer
  cli.py                    commands and output
packs/dragonbane/           hand-written system pack, creation tables, pre-made heroes
packs/ironsworn/            a whole game: hand-written system.toml, creation and heroes; generated moves, tables, assets (CC BY, credited)
examples/red-tusk/          a small original adventure, bundled and playable (Dragonbane)
examples/bell-under-the-hill/  the starter adventure for Ironsworn: needs no book
skills/solo-gm/SKILL.md     GM protocol for the agent
skills/solo-import/SKILL.md building or enriching an adventure pack (PDF or Foundry)
templates/AGENTS.md         copied into each new campaign
tests/                      python3 -m unittest discover -s tests
```

A campaign is a folder (by default `~/Games/solo/campaigns/<adventure>-<hero>/`):

```
campaign.toml     system pack, adventure pack, title
AGENTS.md         instructions the agent reads on launch (+ CLAUDE.md, .claude/settings.json)
events.jsonl      append-only log, the source of truth: rolls, commits and the conversation
state.json        derived; the panel watches it
```

`~/.local/state/solo/current` holds the path of the active campaign, so the panel and a `solo` run outside the folder know which one to use.

## Formats

Hand-written files are TOML. Generated files are JSON, because the standard library can read TOML but not write it. Where both exist for the same thing (an NPC imported from Foundry and then given a profile), the TOML file extends and overrides the JSON one, so re-running an import never clobbers authored content.

System pack, `packs/<system>/`:

```toml
# system.toml
name   = "Dragonbane"
family = "d20-under"
needs  = ["time", "push", "rest", "combat", "creation.choose"]   # what a campaign can't start without

[attributes]  # key = label
str = "Strength"   # ... con, agl, int, wil, cha

[conditions]  # condition = attribute it puts a bane on
exhausted = "str"  # ... sickly, dazed, angry, scared, disheartened

[tracks]      # resources with value/max on the character
hp = "Hit points"
wp = "Willpower points"

[time]        # unit = seconds
round = 10
shift = 21600

[push]
cost = "condition"   # d6-pool packs use e.g. { stress = 1 } plus add_dice

[rest.shift]  # see Rests
label = "Shift rest"
recover = { hp = "max", wp = "max" }
heal = "all"
time = { shift = 1 }

[skills]      # skill = attribute; skills.json from the importer adds to this
sneaking = "agl"
animism = { attribute = "int", untrained = false }

[foundry]     # where the Foundry system keeps a character's values, for the importer
tracks = { hp = "hitPoints", wp = "willPoints" }
conditions = "conditions.{attribute}.value"
```

The bundled `packs/dragonbane` holds only the names (attributes, conditions, tracks, skills) and `needs`: the rest is the player's book, built into a pack laid over it (`extends`). Optional sections for stakes, fights and growth, shown with made-up values (`tests/fixtures/house` has them all):

```toml
[dying]            # at 0 on the track: death rolls until rally or die successes/failures
track = "hp"
roll = "con"       # attribute or skill rolled
rally = 3
die = 3
recover = "1d8"    # track restored on a rally

[advancement]      # Dragon/Demon on a skill marks it; `solo advance` rolls each mark
mark_on = ["dragon", "demon"]
roll = "1d20"      # over the skill's value: +1
max = 18

[combat]
initiative = 10    # cards 1..N dealt each round, lowest first
dragon = "double"  # a Dragon on an attack rolls the weapon dice twice
evade = "evade"    # the skill for evading
track = "hp"       # where damage goes
unarmed = { skill = "brawling", damage = "1d4", bonus = "str" }
damage_bonus = { str = [[11, ""], [15, "1d4"], [18, "1d8"]] }

[weapons]          # matched to sheet items by slug
broadsword = { skill = "swords", damage = "2d6", bonus = "str" }
short_bow = { skill = "bows", damage = "1d8", bonus = "agl", parry = false }
shield = { skill = "brawling", attack = false }

[armor]            # worn items add up
leather_armor = 1
```

Beside it: `creation.toml` (see Character creation), `characters/*.toml` (pre-made heroes), and generated `skills.json`, `rules/*.md`, `tables/*.json`. A pack built from a book lives in `~/Games/solo/systems`, never in this repository.

`untrained` (base chance by attribute) is a d20-under setting. d6-pool packs add `success`, `[pool]`, `[extra_dice.<name>]` (with `on_one` triggers) and `[triggers.<name>]` tables; see `tests/fixtures/yze/system/system.toml`. action-roll packs (Ironsworn) add `[momentum]`, `[progress]`, an `odds` oracle and the `moves/` and `assets/` folders; see `packs/ironsworn/system.toml` and docs/PACK_FORMAT.md.

#### The action-roll family

Ironsworn is the family's first game and the project's one whole game in the repository: its moves, oracles and assets are published under the Creative Commons Attribution 4.0 license (the rest of the book's text is CC BY-NC-SA, non-commercial only, and is left out), so they ship in `packs/ironsworn` with their credit, and a fresh install plays with no book. What the engine adds for it:

- `mechanics.action_roll`, `progress_roll` and `burn`: an action die (d6) and a stat plus adds (at most 10) against two challenge dice (d10), read as a strong hit, a weak hit or a miss, a tie going to the dice, matched dice a twist; negative momentum equal to the action die cancels it; burning cancels every challenge die under momentum; a progress roll counts a track's full boxes and ignores momentum.
- `solo act <move>`: the move's roll as an `act` event, and the move's own words for the result (`says`) for the GM, who chooses within them and commits the cost. `solo burn` is a `burn` event that replaces the last result and resets momentum. What a result sets off for the clocks (`check:miss`, `check:weak_hit`, `check:strong_hit`, `check:match`) waits while a burn could still change it, and happens when the story goes on (a `settled` event) or the burn is made, so a burn spares the clock a miss that never was.
- Momentum is a track with a `min` and a `reset`; each impact (a condition) lowers its `max` and `reset` by one, and an impact keeps the track it names (wounded: health) from rising. Health, spirit, supply and momentum change by commit, as every track does.
- Progress tracks (`progress` in state, `progress` events, `solo track`): vows, journeys and fights at a rank, and bonds, which every hero has. A mark fills ticks by rank; only full boxes count on a progress roll.
- The yes/no oracle is `oracle.chart = "odds"`: a d100 against the chance of a yes at each of five odds, a double a twist. Characters come from a stat array dealt at random, three assets, and constant tracks.
- The Table shows moves in place of skills (by group, with a stat to choose and `Adds`), momentum as a bar with a zero and a reset mark, the vows and roads as boxes with Mark progress and Progress roll, and Burn momentum when `state.json`'s `burn` says it would change the roll. The Book's dice moment throws an action die and two challenge dice and lights each as the score beats it, and its side column keeps the momentum bar and the tracks.
- `solo import datasworn <classic.json> --out packs/ironsworn` writes `moves/`, `tables/` and `assets/`, and takes only objects whose own license (else their collection's, else the package's) is CC BY 4.0; it says what it left out and the odds the ask-the-oracle tables give.

Adventure pack, `adventures/<adventure>/`:

```
adventure.toml   authored: title, system, summary, start, factions, clocks, scene extras, branches
scenes.json      generated: scene titles, exits, NPCs and tables linked per scene
scenes/<id>.md   scene text; GM-only parts inside ::: gm ... ::: blocks
npcs/<id>.json   generated stat block + description
npcs/<id>.toml   authored profile: faction, attitude, wants, fears, secrets; foes add
                 [stats] hp/armor and [attack] (skill + damage) or attacks = "<table>"
tables/<id>.*    formula + result ranges (json generated, toml authored)
```

```toml
# adventure.toml
title   = "The Red Tusk Hall"
system  = "dragonbane"                 # the system pack it is written for
summary = "Orcs have grown bold on the hill above the village."   # player-safe, shown on its card
start   = "road"
chaos   = 3                            # oracle chaos factor to start at (1-9, default 5)
# scene_checks = false                 # never alter or interrupt scenes

[factions.orcs]
name = "Red Tusk orcs"
standing = -1                          # -2 hostile .. 2 allied

[clocks.dark_ritual]
label    = "The ritual below"
segments = 6
advance  = ["time:shift", "fact:hall.alarm"]
stop     = ["npc:priest:dead"]         # stops it for good (same triggers as advance)
on_tick  = "omens"                     # table rolled on every tick
at_full  = "ritual_completes"          # scene flagged as urgent

[scenes.final_battle]
title  = "The Final Battle"
climax = true
npcs   = ["orc_leader"]

[[scenes.final_battle.branches]]
when = "npc.orc_leader.fate == 'alive' and promise.warband_joins == 'kept'"
text = "The Red Tusk warband charges through the east gate."
```

Branch conditions are a small expression language evaluated by the engine, never `eval`: `and`, `or`, `not`, comparisons, `in`, and the names `npc.<id>.<fate|attitude|location>`, `faction.<id>`, `promise.<id>`, `fact.<key>`, `clock.<id>`, `scene`, `visited.<scene>`, `pc.<track>`, plus `hostile unfriendly neutral friendly allied` (-2..2).

Commit, the only way the agent changes state (every key optional):

```json
{
  "note":    "parleyed with Grukk instead of fighting",
  "facts":   {"hall.alarm": false},
  "npc":     {"orc_leader": {"attitude": "+1", "memory": "PC spared his son", "fate": "alive"}},
  "faction": {"orcs": "+1"},
  "promise": {"id": "warband_joins", "npc": "orc_leader",
              "terms": "joins the final battle if the idol is returned", "status": "open"},
  "pc":      {"hp": "-3", "conditions": {"add": ["scared"]}, "items": {"add": ["idol"]}},
  "clock":   {"dark_ritual": "+1"},
  "time":    {"stretch": 2},
  "clue":    ["secret_tunnel"],
  "chaos":   "-1",
  "chronicle": "Session recap, written at the end of a session.",
  "end":     "How the adventure closed."
}
```

A monster attack table's results may carry `damage`, `defend = false` (can't be dodged or parried), `parry = true` (Dragonbane monster attacks can't be parried otherwise: `[combat] monster_parry = false`) and `armor = false`.

### Official content

What a published adventure needs beyond a hand-written one, added while importing a timed tournament adventure and meant for whole books:

```toml
move_time = { stretch = 1 }            # every move takes game time unless its exit says otherwise

[scenes.gallery.exits.library]         # an exit as a table: gated and timed
label = "A staircase that wasn't there before"
when  = "fact.gallery.stairs_open"     # closed until this holds; `solo move` refuses it, the digest lists it apart
time  = { round = 1 }

[clocks.collapse]
advance = ["time:round", "fact:tower.sinking"]
while   = "fact.tower.sinking"         # counts nothing until this holds; time before it started doesn't count

[[clocks.collapse.stages]]             # what changes for good at a segment
at    = 2
text  = "The floor lurches; water climbs the stairs."   # the player feels it (an omen on a hidden omen clock)
note  = "The library is under."                         # the GM reads it, never the player
facts = { tower.library_sunk = true }
clock = { other = "+1" }
```

- Fight rounds pass game time (`time:round`), so a clock can count rounds. A scene's `each_round` text (a breath held under water) is in every fight line there, and a monster's effect without damage comes back as "run this now".
- Foes: `stats.ferocity` (actions a round, in the fight's to-act list), `stats.immune` (weapons do nothing). `solo wound <foe> <dice|all> --why` is harm by fire, spells, traps or light, ruled by the GM and rolled by the engine.
- `characters/` in an adventure: pregenerated heroes (offered on the New adventure screen before the system's) and replacements (`replacement = true`). `solo hero <character>` after a death: the story goes on with a new hero, the dead one stays in `heroes` and the Hall of the Fallen, and an NPC who became the hero leaves the cast.
- `rules/` in an adventure: pages `solo rule` finds, for rules the adventure leans on (stand-ins in our own words when the system pack has no imported rules).
- The GM's memory: `solo scene` lists the facts the story has settled; `solo resume` ends with the latest chronicle entries, open promises, clues, who is gone and earlier heroes.
- Review: `source` on anything; `solo outline` (scenes, gates, stages, people, and every fact a condition reads, which the GM must commit somewhere); `solo validate` adds warnings for scenes nobody can reach, dead ends and NPCs no scene brings in.
- `SOLO_TRACE=<file>` logs every command with its error; `SOLO_GM_MODEL` picks the GM's model and `SOLO_GM_EFFORT` its effort level, over the pace. All three are for play tests. `SOLO_GM_TIMEOUT` (seconds, default 180) ends a GM turn whose agent has printed nothing for that long, so a hung agent never leaves the Book thinking for good.

### Solo rules

Dragonbane has its own solo rules (Alone in Deepfall Breach, the core set's solo adventure). The engine runs them from data in the pack the player builds from that book; nothing of it ships here. Without them, the engine's own likelihood oracle, random events and scene checks run solo play. The sections, with the book's values left out:

```toml
[oracle]                 # a chart replaces the likelihood oracle, its random events and scene checks
chart = "fortune"
scene_checks = false
inspiration = ["<table>", "<table>", "<table>"]   # --meaning
[oracle.fortune]         # a die read in a column; two dice keep the highest or lowest when one end is likelier
bands = [[1, 1], ...]
yes_no = ["...", ...]    # one list per column

[effects]                # a Dragon or Demon outside a fight rolls these tables
dragon = "<table>"
demon = "<table>"
[threats]                # counters that advance on time and failures and happen when full
segments = ...
start = ...
advance = ["time:<unit>"]
table = "<random threats>"
[search]                 # solo search: time passes, a skill roll, the search table
skill = "..."
table = "<table>"
time = { <unit> = ... }
[scavenge]
table = "<table>"
again_time = { <unit> = ... }
[npcs]                   # simple NPCs: template and attacker role, by commit or in a pack
attacks = "<table>"
attackers = ["melee", "ranged", "sneaky", "magic"]
[npcs.templates.minion]  # hp, armor, damage, skill, other, movement, attributes
[abilities.<id>]         # heroic abilities the engine runs: initiative = n (cards), or push = { track = n }
[rest.stretch]
tend = { skill = "...", recover = { hp = "..." } }     # solo rest stretch --tend
[dying]
self_rally = { skill = "..." }                         # solo rally
self_save = { skill = "...", recover = "..." }         # solo death-roll --heal
```

- Ferocity is initiative cards, and so is an ability that draws more: the order lists a fighter once per card, and each card is a turn.
- A volley (an NPC attack that strikes twice) queues its second attack: the next `solo enemy` for that foe takes it without a new roll.
- Creation adds `extra_abilities = { count = 1, from = [...] }` after everything else, so a seed still builds the same hero.
- A table result finishes itself: `roll` (its value, where the text says `{value}`), `choices` (one picked), `then` (tables rolled next) and `again`. Dice take multipliers: `2d6x10`.
- `solo rule` pages for the chart, threats, searching, simple NPCs, heroic abilities and healing alone are written from this data, in the engine's words.

### Campaigns

A campaign written as one (missions from a hub) is one pack: a hub scene where missions are given and ended, gated exits that open each mission when the one before is done (a fact per mission), and a scene per waypoint. Its state (a prisoner freed, a relic taken) lives in one campaign folder from the first mission to the last.

A book of separate adventures is imported one adventure per pack, each play-tested on its own, and the hero carries from one to the next (`solo new <next> --character <campaign>`). The hero's story carries too ([Long campaigns](#long-campaigns)): each earlier adventure as a few lines (how it ended, the last chronicle entries, what was left open, the people who remember the hero) and the hero.* facts. What doesn't carry yet is the world as state: NPC fates, factions, promises and facts stay in the campaign that made them, and the next GM reads them as text. When a book needs it, the next step is a campaign manifest (an ordered list of packs sharing ids) whose `solo new` of a later pack seeds its state from the earlier campaign's facts and NPCs. Until then, each pack notes what an earlier adventure could have changed.

Validation rules: ids must exist (a new NPC needs a `name`), attitude moves one step per commit unless `"override": "<reason>"` is given (logged), dead stays dead without an override, tracks and clocks are clamped, conditions and time units must be declared by the system pack.

### Long campaigns

For a model GM, time is harder than any rule. A campaign runs for months, the agent's session can be lost, compacted or replaced at any time (the Book keeps one until the agent loses it), and a fresh GM knows only what the engine puts in front of it. Play tests showed the fix every time: put the thing in front of the GM at the moment it matters. The pieces below do that for the hero's past, so the small things the hero does keep mattering.

- Consequences: a commit's `consequence` (`id`, `text`, `npc`, `at`, `when`, `after`, `status` open/done/dropped) is something the hero did that will come back. `at` (scene ids), `when` (a condition) and `after` (game time) must all hold, those given; with none of them, `npc` alone means the next time the hero meets them, and beside them it only says whom it concerns. `at` and `npc` count from the hero's next arrival, so one made in front of the smith waits for the hero to come back. When one's moment comes, after any command, from the GM or the panel, the engine appends a hidden `due` event: the GM reads it in the command's `then`, in the log and in the next Book prompt, and `solo scene` lists what is due now. Consequences stay out of state.json.
- The chronology: the log replayed into moments with the scene and game time of each (arrivals, notes, people met and what they remember, fates, attitudes, factions, promises, consequences, gear, fights, deaths, stages, threats, advancement, the chronicle). Derived, so older campaigns have it too. `solo resume` shows the moments since the last chronicle entry (the last 25), so a GM who never wrote one still leaves the next session a record; `solo history` shows them all, chaptered by chronicle entries.
- `solo recall <words>` searches everything the campaign holds in words: every message said, notes, facts, memories, faction memories, consequences, oracle answers, table results, voices, stages and the hero's earlier adventures. Best matches first, accents and case ignored. The GM looks up before it invents.
- The resume's long memory: before this adventure, the hero (hero.* facts), the chronicle (last six, each with when and where), since the last entry, loose ends, promises, clues, the people the hero knows (latest first, with what they remember), factions (standing and what they've heard), who is gone.
- The scene digest: "Back here" on a return (how long the hero was away, what happened here before), "Due now", facts ordered by relevance (this scene's, the people here, those this scene's conditions read, then the latest; the rest counted, never silently dropped), people lines with their last three memories, what is waiting on them and what their faction has heard, the hero's own story, and a reminder to write a chronicle entry after twelve GM messages without one (also in the commit report).
- People: an NPC the GM made up keeps a `role`, `description`, `voice`, `wants` and `fears` (the codex blanks wants and fears until learned; the adventure's own NPCs refuse fields they already have). A faction keeps `memories`: word of what the hero did, for every one of them met later. A committed `location` wins over the adventure's scene lists (the freed prisoner goes home and is found only there). An NPC marked `many = true` is a kind of foe: fights never run out of them and no commit gives them a fate.
- Commits with nothing the player can see (facts, consequences) are hidden from the table's log, and `gm_line` carries the GM-only parts as `[for the GM: ...]`.
- Threats wait in a scene marked `safe` (a chapel, a village): time there doesn't bring them closer. A threat that comes to pass carries a GM note to run it in the same reply.
- Commits read the shapes GMs reach for when the meaning is plain (`npcs` for `npc`, `learn` as `{"gudrun": "wants"}`, consequences and promises keyed by id, `text` for a promise's terms, a promise's id made from its terms, `{"scene": {"facts": ...}}` for facts under the current scene, facts as a list or a line, a sentence of a fact filed under the scene by its first words, time in words like `"10 minutes"`), each said in the commit's warnings, and refuse the rest with what to write instead (a top-level `memory`, `at` on an NPC, a `when` in prose).

The first real GM run of this (a scripted session dropped partway, and the hero walking back into a village) met every expectation: the people the GM invented, a hero's lost sister and a promise were written down and found again by the fresh GM. It also found a threat running to its end on a safe road and a dozen refused commits in shapes GMs reach for; both are fixed above.

## CLI

Every command is in the [README's Commands table](../README.md#commands) with its main options, and `solo <command> --help` has the rest.

`solo new examples/red-tusk` and `solo new red-tusk` both work: the system comes from the adventure, the hero is random unless `--character` says otherwise, and the folder is `~/Games/solo/campaigns/red-tusk-<hero>` (suffixed if taken). Mechanical commands print JSON; prose commands print Markdown; errors go to stderr with exit status 1.

## Verification

- Unit tests (stdlib `unittest`) cover engine behaviour: creation reproducibility and rule invariants (attribute range, trained counts, base chance doubling, age modifiers), library resolution, `new` defaults, rest limits and clock ticks, and the CLI's JSON contract the panel depends on.
- `omarchy plugin validate .` for the manifest.
- Live shell: the plugin folder is linked into `~/.config/omarchy/plugins`, so saving QML hot-reloads it. Check `qs log -p $OMARCHY_PATH/shell` for warnings from `cabral.oma-solorpg`, summon each screen over IPC, and look at a `grim` screenshot.
- `tests/gm_eval`: a real GM plays scenarios of The Red Tusk Hall on the rules you built, and a judge reads the transcript.

## Risks and open questions

- Dragonbane plays only once the player has built its rules from their book. The Makefile and the `solo-rules-import` skill carry that; a wrong number there is the import's to find (`solo audit`).
- Chaos at 5 alters or interrupts half of all scene entries, which crowds a short written adventure; Red Tusk starts at 3. Tune after play.
- The GM runs `solo enemy` for foes, so a GM that forgets would let the hero fight unopposed. The skill says to; watch for it in play tests.
- Foes' HP lives in the fight. Ending a fight and starting a new one against the same NPC restores them.

- The agent's first launch in a new folder may ask to trust it (Claude Code does). Campaigns share one parent folder, so trusting `~/Games/solo/campaigns` once may cover all of them; to confirm on a real run.
- The replay is only as exact as the model's copying. `solo resume` asks for the text word for word and the panel shows the original, so a drift is visible; watch for it in play tests.
- Claude Code's hook input: `last_assistant_message` is used when present, the transcript file otherwise. If a Claude Code update changes the transcript format, capture falls back to nothing, silently; `solo log` shows whether `said` events are arriving.
- Player clicks and GM commands interleave. The lock keeps the log consistent; the GM skill reads the log each turn so narration follows the dice. A GM that ignores the log would roll twice. Watch for it in play tests.
- Rests are player-initiated, so a player can rest where the fiction forbids it. The GM can answer in the story (and commit a consequence); a "GM must allow" toggle is possible later.
- Lines and veils reach the GM as instructions, and in play nothing checks them. The player has the cut button (`solo strike`, the Book's "cut the GM's last message"), and `tests/gm_eval` has scenarios for them, which haven't met a real GM yet (ROADMAP items 4 and 5).
- A GM turn has limits in code whatever the agent does: going quiet for `SOLO_GM_TIMEOUT` seconds, a wall-clock limit, a cap on Claude Code's model calls, and a spending limit per session, 10 dollars or 200 turns by default (`solo gm budget`). What they can't stop is a GM that spends its turns badly inside them.
- Free League's Dragonbane license lets this project use the game's terms, not carry a copy of its rules: no numbers, tables or text from a book in the repository, tests included (their rules are made up). See [NOTICE.md](../NOTICE.md).
- `~/Games/solo` as the default home: visible and easy to back up, but it is a new folder in the player's home. It is created only by `solo new`.

## Decisions

- Local engine over a VTT at runtime. Foundry needed a server, a connected GM browser (headless Chromium unattended), a relay (100 requests a month on the free public tier) and per-system roll scripts, while a local engine adjudicates in plain Python. Foundry stays useful as an import source.
- Alchemy is not usable as a backend: no API (its only developer docs cover a one-way 5e NPC import) and no export of purchased content.
- The agent is the GM brain, through CLI + skills: works with all agents `omarchy default agent` supports, including pi, which has no MCP option. No API keys or model IDs in the project.
- Standard library only, including tests (`unittest`). One exception, for authors only: `solo extract` reads PDFs with PyMuPDF, imported when the command runs, and its tests skip without it.
- The panel is a client of the CLI, not of the files: one writer, one set of rules, and the JSON contract is testable without QML.
- Character creation as data (`creation.toml`), with pre-made heroes as the fallback for any system without it.
- Seeds, not temporary files, carry a previewed character to `solo new`, so the preview and the created hero can't drift apart.
- One plugin with two kinds (bar widget + panel) rather than two plugins: one install, one enable.
- The story in a window of the plugin's own (the Book), with the agent headless behind it, rather than in the agent's terminal, which shows tool calls, permission prompts and JSON between the lines of the story. This settled the question of a single-window mode that was open before the Book.

## Open

- Content source per adventure: Foundry module when available, PDF otherwise.
