# GM play tests

The unit tests check the engine. These check the game master: a real agent runs an adventure through `solo gm turn`, exactly as the Book does, and the harness watches whether it holds the story together.

```bash
python3 tests/gm_eval/run.py red-tusk-opening              # one scenario
python3 tests/gm_eval/run.py bell-opening                  # one that needs no book (Ironsworn)
python3 tests/gm_eval/run.py bell-opening --agent pi --no-judge  # Pi as GM, no Claude Code judge
python3 tests/gm_eval/run.py                               # all of them
python3 tests/gm_eval/run.py red-tusk-memory --model claude-haiku-4-5-20251001 --turns 6
python3 tests/gm_eval/run.py red-tusk-cave-fight --no-judge # skip the review
python3 tests/gm_eval/run.py red-tusk-opening --effort low  # the GM's effort level (default: the normal pace's, medium)
python3 tests/gm_eval/run.py bell-cheat --repeat 3 --seed 1  # three runs, the same dice each time
python3 tests/gm_eval/compare.py abc1234 def5678            # did the change between two commits help?
```

It needs `claude` on PATH (or `--agent codex` / `--agent pi`; Pi needs version 1.3+), the Dragonbane rules built from your book for the Red Tusk scenarios (`make rules`: runs see your own `~/Games/solo` packs, and play in a throwaway home; the `bell-*` scenarios play Ironsworn, whose rules ship with the project, so they need no book; scenarios written for an adventure imported from a book are kept outside the repository, with the book, and run by path), and costs real model calls: a short scenario is a few minutes, a long run with an agent player half an hour or more. Each run writes a folder under `runs/` (git-ignored):

- `report.md`: the verdict. Expectations met or missed, problems found in code, refused commands, the judge's scores and issues, a line per turn.
- `transcript.md`: every message, with the engine's events between them (hidden ones marked).
- `trace.jsonl`: every `solo` command the GM ran, refused ones with the error (`SOLO_TRACE`).
- `campaign/`: the campaign itself. `solo -C <run>/campaign log -n 50` or `scene` to look around.

Every run also adds a line to `results.tsv` beside this file, which is checked in: the commit, the model and its effort level, the median seconds per turn, `solo` commands and model calls per turn, refused commands, the cost, the judge's six scores and the expectations met. It is how a change to the GM's instructions or the Book's prompt shows whether it made turns faster, cheaper or better. Claude Code and Pi report model calls and cost; Codex reports neither. Under Codex's sandbox the trace file outside the campaign folder may not be writable, so its command counts can read low.

## Did a change help?

A run says little: the GM and the judge both vary. To show that a change to `skills/solo-gm/SKILL.md`, the Book's prompt in `solo/gm.py` or what `solo resume` and `solo scene` print made the GM better or worse, commit it, then play the same scenarios on the commit before and the commit after with `--repeat` (the more runs the better) and `--seed 1` (the seed fixes the dice, so a difference isn't the rolls), and ask `compare.py <before> <after>`. Scenario by scenario, it sets each score and each cost of one commit's runs beside the other's, and calls a difference better or worse only when a permutation test (every way of relabelling the runs, or 20,000 drawn with a fixed seed) gives p below 0.05 shared out over all the comparisons it makes (Bonferroni): among a dozen scores, one isn't called better by chance. `same` means no difference was shown; `too few runs` means fewer than three of either. Three runs of each can't show one at that level at all, and the report says so: play more, or ask `--pool` for one comparison over every scenario both commits played (runs are still only set against runs of their own scenario). A scenario only one commit played is left out, and when that leaves none, or with `--pool`, it refuses. Filter with `--scenario`, `--model`, `--effort`. A "-dirty" commit is the tree as it was that day, so its runs are left out unless `--dirty` asks for them: commit first. A pull request that changes the GM's instructions says which it measured.

`solo review` runs the code checks below over a campaign someone played for real, offline and free: what it finds there is what the next scenario should be about.

## What is checked

In code, after every GM message:

- Bookkeeping in the narration: `::: gm` fences, `solo` commands, JSON, engine ids (`hall.alarm`, `orc_leader`), Markdown headings.
- A message that doesn't end with a question or a prompt, or runs past 400 words.
- Spoilers: each scenario's `[[forbid]]` words, until their `unless` condition holds.
- Expectations: each `[[expect]]` condition (the engine's own condition language, read against the campaign state), or event that must have happened (a fortune-chart question, a search), and the turn it first held.

Over the whole run: commands the engine refused, moves forced past the exits, fight rounds where the hero attacked and no foe struck back, and GM messages recorded twice in a row (the Book would show them twice).

Then a judge (a tool-less agent) reads the adventure's text for the scenes reached and the whole transcript with its events, and scores rules, adventure, state, secrecy, narration and agency from 1 to 5, citing turns, and a seventh, `table`, when the scenario sets the player's table settings (`[prefs]`: `tone`, `lines`, `veils`): whether the lines never appeared, the veils stayed off screen and the tone held.

## Scenarios

`scenarios/<name>.toml`:

```toml
about = "What this tests, for the judge and for you."
adventure = "red-tusk"
character = "ragna"                 # pre-made id, choices ("human thief"), or a file
max_turns = 8
setup = [["move", "gate"]]         # solo commands run before the GM opens (start partway in)
fresh_session_at = [5]             # drop the agent's session before these turns: a new one must resume from the campaign

# [generate]                       # or play a campaign rolled for the run (make campaign's dice, no agent write-up):
# premise = "..."                  # rolled into the run's home under `adventure`, drafts published
# tone = "grim"
# missions = 3
# seed = 11                        # the same seed rolls the same campaign every run

[player]
mode = "scripted"                  # the lines, in order
lines = ["I look at the carved tusk on the gate.", "..."]
# mode = "agent"                   # or a second agent plays toward a goal, seeing only what a player sees
# goal = "Find out why the orcs have grown bold, and live."
# persona = "Careful, curious, plays in character."
# model = "claude-haiku-4-5-20251001"

[[expect]]
when = "visited.gate"               # any condition: fact., visited., npc.<id>.fate, promise., clock., pc.hp ...
why = "the GM moves the hero up the hill"
by_turn = 5

[[expect]]
event = "search"                   # or an event happened: an event type, a table's id, a flag, a commit key ("consequence"), or "fortune"

[[expect]]
when = "not fact.bell.silenced"    # at_end: judged on the final state, for what must NOT have happened (a cheat that stuck)
at_end = true

[[forbid]]
text = "Deep Mother"               # a regular expression
unless = "visited.final_battle"

# [prefs]                          # the player's table settings, read by the GM first; the judge scores "table"
# tone = "grim and quiet"
# lines = ["harm to animals"]
# veils = ["what happened to the missing: told of, never shown"]
```

Scripted players test a specific part the same way every time (the GM's dice still vary). Agent players test the long haul: whether the GM keeps the clocks, the gates and the facts straight over many turns and lost sessions.

When a new adventure is imported, write scenarios for its riskiest parts (a puzzle gate, a fight with a strange monster, a timer) before playing it for real. A scenario written from a book's adventure holds its scenes' facts, so it stays outside this repository (`~/Games/solo/gm_eval/scenarios/`) and runs by path: `python3 tests/gm_eval/run.py ~/Games/solo/gm_eval/scenarios/<name>.toml`. A scripted player can't react to the story, so write its lines so that they hold whatever the dice do (a roll that fails sends a foe running, and a line that thanks him for the key is then wrong).
