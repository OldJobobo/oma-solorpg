"""Play tests with a real GM: does the agent hold the adventure together over a session?

A scenario (scenarios/*.toml) names an adventure, a hero and a player. The harness starts a
campaign in a folder of its own, then plays it the way the Book does: `gm.turn` runs the
headless agent one exchange at a time, and the player's words come from the scenario's
script or from a second agent playing the hero toward a goal. After every GM message it
checks what can be checked in code; at the end a third agent judges the whole transcript
against a rubric. Everything lands in the run folder: the campaign, the command trace,
transcript.md, report.json and report.md.

Nothing here runs under `python3 -m unittest`: a run costs model calls and minutes. The
code that needs no agent (the checks, the player's view, the report) is unit tested in
tests/test_gm_eval.py with a stand-in GM.
"""

import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import tomllib
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from solo import campaign, cli, creation, generate, gm, library, packs  # noqa: E402
from solo.review import fight_checks, forced_moves, hygiene, repeated_messages  # noqa: E402,F401

SCENARIOS = Path(__file__).resolve().parent / "scenarios"
NESTING = gm.NESTING

# Scenarios ---------------------------------------------------------------------------

def load(name):
    path = Path(name)
    if not path.exists():
        path = SCENARIOS / f"{name}.toml"
    with open(path, "rb") as f:
        scenario = tomllib.load(f)
    scenario.setdefault("name", path.stem)
    scenario.setdefault("max_turns", 10)
    scenario.setdefault("player", {"mode": "scripted", "lines": []})
    return scenario


# Players -------------------------------------------------------------------------------

class Scripted:
    """The scenario's lines, in order. None when they run out."""

    def __init__(self, spec):
        self.lines = list(spec.get("lines", []))

    def next(self, c, turns):
        return self.lines.pop(0) if self.lines else None


class Agent:
    """A second agent plays the hero toward the scenario's goal, seeing only what a player
    sees: the story in the Book and the table (their sheet, visible clocks, the fight)."""

    def __init__(self, spec):
        self.spec = spec
        self.model = spec.get("model", "claude-haiku-4-5-20251001")

    def next(self, c, turns):
        prompt = player_view(c, self.spec, len(turns))
        reply = ask_agent(prompt, self.model, system=(
            "You are the player at a solo tabletop roleplaying game, talking to your game master. Your hero is alone: "
            "no companions but the ones the story gives them. You only ever write your next message to the GM, "
            "in the first person, one to three sentences."))
        reply = reply.strip().strip('"')
        return None if not reply or reply.upper().startswith("END") else reply


def player_view(c, spec, turn):
    """What the player can see: the story (speech, rolls, omens), the hero's sheet and the
    visible clocks. Hidden clocks, GM text and hidden log lines never appear."""
    state = c.state
    pc = state["pc"]
    lines = [f"Your hero: {pc['name']} ({', '.join(map(str, pc['info'].values()))}). "
             + ", ".join(f"{k.upper()} {t['value']}/{t['max']}" for k, t in pc["tracks"].items())
             + f". Conditions: {', '.join(pc['conditions']) or 'none'}. Carrying: {', '.join(pc['items']) or 'nothing'}."]
    trained = [s["name"] for s in pc["skills"].values() if s["trained"]]
    lines.append(f"Trained skills: {', '.join(trained)}.")
    clocks = [f"{cl['label']} {cl['value']}/{cl['segments']}" for cl in state["clocks"].values() if not cl["hidden"]]
    if clocks:
        lines.append(f"On the table: {', '.join(clocks)}.")
    fight = state["combat"]
    if fight:
        foes = ", ".join(f["name"] + (" (down)" if f["down"] else f" (HP {f['hp']})") for f in fight["foes"].values())
        lines.append(f"A fight is on: {foes}.")
        if fight["incoming"]:
            hit = fight["incoming"]
            options = "evade, parry or take it" if hit.get("can_defend", True) and hit.get("can_parry", True) else "evade or take it" if hit.get("can_defend", True) else "take it"
            lines.append(f"A hit is coming at you from {hit['name']}: you choose {options}.")
    if pc["dying"]:
        lines.append("You are dying: every turn you make a death roll.")
    if pc["dead"]:
        lines.append("Your hero is dead.")
    story = []
    for beat in state["story"][-24:]:
        if beat["kind"] in ("gm", "player"):
            story.append(f"{'GM' if beat['kind'] == 'gm' else 'You'}: {beat['text']}")
        elif beat.get("text"):
            story.append(f"[{beat['kind']}] {beat['text']}")
    return "\n".join([
        f"Your goal: {spec.get('goal', 'play the adventure well')}",
        f"How you play: {spec.get('persona', 'a thoughtful player who explores, takes some risks and plays in character')}",
        "",
        *lines,
        "",
        "The story so far (latest last):",
        *story,
        "",
        f"This is your message number {turn}. Write your next message to the GM: one to three sentences about what your hero does or says. "
        "Answer any question the GM asked. Only the message, nothing else. "
        "If the adventure has clearly ended, or your goal is done and there is nothing more to do, write only: END",
    ])


def ask_agent(prompt, model=None, system=None, timeout=600):
    """One answer from a tool-less Claude Code run (the player and the judge)."""
    env = {k: v for k, v in os.environ.items() if k not in NESTING}
    command = ["claude", "-p", prompt, "--output-format", "json", "--tools", "", "--no-session-persistence"]
    command += ["--model", model] if model else []
    command += ["--system-prompt", system] if system else []
    with tempfile.TemporaryDirectory() as empty:
        done = subprocess.run(command, cwd=empty, env=env, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    try:
        return json.loads(done.stdout).get("result", "")
    except ValueError:
        raise RuntimeError(f"the agent answered with no JSON: {done.stderr.strip()[-300:]}") from None


# Checks -------------------------------------------------------------------------------

def spoilers(text, c, forbid):
    """Words the player mustn't read yet: [[forbid]] with text and an `unless` condition."""
    found = []
    for rule in forbid:
        allowed = rule.get("unless") and packs.evaluate(rule["unless"], c.state)
        if not allowed and re.search(rule["text"], text, re.I):
            found.append(("spoiler", f"{rule['text']!r} before {rule.get('unless', 'ever')}"))
    return found


def expectations(c, expect, turn, reached):
    """Record the first turn each [[expect]] held: a condition on the state (`when`), or an
    event that happened (`event`: an event type like "oracle", or a table's id like "search")."""
    for rule in expect:
        key = _expect_key(rule)
        if not rule.get("at_end") and key not in reached and _holds(rule, c):
            reached[key] = turn
    return reached


def _expect_key(rule):
    return rule.get("when") or f"event {rule['event']}"


def _holds(rule, c):
    if rule.get("when"):
        return packs.evaluate(rule["when"], c.state)
    wanted = rule["event"]
    return any(e["type"] == wanted or e.get("table") == wanted or e.get(wanted) is True
               or (e["type"] == "oracle" and e.get("chart") == wanted)
               or wanted in (e.get("changes") or {}) for e in c.events)


# Running -------------------------------------------------------------------------------

def run(scenario, out, agent="claude", model=None, effort=None, judge=True, max_turns=None, log=print, seed=None):
    """Play one scenario into `out`. Returns the report. With a `seed` the dice are fixed (SOLO_SEED), so
    two runs meet the same rolls in the same state: a difference between commits is not the dice."""
    out = Path(out).resolve()  # the GM runs in the campaign folder: relative paths would point inside it
    out.mkdir(parents=True, exist_ok=True)
    own = library.home()
    os.environ.update(SOLO_HOME=str(out / "home"), XDG_STATE_HOME=str(out / "state"), SOLO_TRACE=str(out / "trace.jsonl"))
    link_own_packs(own, out / "home")
    os.environ.pop("SOLO_SEED", None)
    if seed is not None:
        os.environ["SOLO_SEED"] = str(seed)
    if model:
        os.environ["SOLO_GM_MODEL"] = model
    if effort:
        os.environ["SOLO_GM_EFFORT"] = effort
    root = start(scenario, out / "campaign")
    player = Agent(scenario["player"]) if scenario["player"].get("mode") == "agent" else Scripted(scenario["player"])
    turns, reached = [], {}
    limit = max_turns or scenario["max_turns"]
    fresh = set(scenario.get("fresh_session_at", []))
    for number in range(limit + 1):
        with campaign.session(root) as c:
            if number == 0:
                said = None
            else:
                said = player.next(c, turns)
                if said is None:
                    log(f"  the player has nothing more to say after {number - 1} turns")
                    break
            seen = len(c.events)
        if number in fresh:
            (root / ".solo" / "agent.json").unlink(missing_ok=True)  # the next turn starts a new agent session
        traced = _trace_length(out)
        began = time.monotonic()
        result = gm.turn(root, said, agent=agent)
        seconds = round(time.monotonic() - began, 1)
        with campaign.session(root) as c:
            new = c.events[seen:]
            text = result.get("text", "") if result.get("status") == "done" else ""
            problems = (hygiene(text, c) + spoilers(text, c, scenario.get("forbid", []))) if text else [("error", result.get("error") or result.get("status"))]
            reached = expectations(c, scenario.get("expect", []), number, reached)
            turn = {
                "turn": number, "player": said, "gm": text, "status": result.get("status"), "seconds": seconds,
                "fresh_session": number in fresh,
                "commands": _trace_since(out, traced),
                "events": [f"#{e['seq']} {campaign.gm_line(e)}" + (" (hidden)" if e["seq"] in c.state["hidden"] else "")
                           for e in new if e["type"] != "said"],
                "problems": [{"kind": k, "detail": d} for k, d in problems],
                "scene": c.state["scene"], "time": c.state["time"],
                # Model calls, tokens and cost, as the agent reports them (Codex has no cost).
                "usage": result.get("usage"),
            }
            turns.append(turn)
            ended = c.state["ended"] is not None and not scenario.get("play_past_end")
        log(f"  turn {number}: {seconds}s, {len(turn['commands'])} commands, {len(turn['problems'])} problems, scene {turn['scene']}")
        if result.get("status") != "done" and result.get("status") != "error":
            break
        failed = [t for t in turns[-2:] if t["status"] == "error"]
        if len(failed) == 2:
            # Two failed GM turns in a row (a usage limit, the agent missing): the rest would fail too.
            log(f"  stopping: the GM failed twice in a row ({failed[-1]['problems'][0]['detail'][:120]})")
            break
        if ended:
            log("  the adventure has ended")
            break
    with campaign.session(root) as c:
        report = summarize(scenario, c, turns, reached)
        report["agent"] = agent
        report["transcript"] = transcript(c)
    if judge and turns:
        try:
            report["judge"] = judge_run(scenario, root, report)
        except (RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
            report["judge"] = {"error": str(error)}
    write(out, report)
    return report


def link_own_packs(own, home):
    """The player's own packs, seen from the run's throwaway home: the rules a GM plays by are
    built from the player's book (make rules), and adventures they imported live beside them.
    Neither ships with this repository."""
    for kind in ("systems", "adventures"):
        folder = Path(own) / kind
        for pack in sorted(folder.iterdir()) if folder.is_dir() else []:
            link = Path(home) / kind / pack.name
            if pack.is_dir() and not link.exists():
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(pack.resolve(), target_is_directory=True)


def start(scenario, root):
    if scenario.get("generate"):
        roll_campaign(scenario)
    adventure_path = library.find_adventure(scenario["adventure"])
    adventure = packs.load_adventure(adventure_path)
    system_path = library.find_system(scenario.get("system") or adventure["system"])
    system = packs.load_system(system_path)
    sheet = creation.character(system, scenario.get("character", "random"), seed=scenario.get("seed"), adventure=adventure)
    prefs = scenario.get("prefs", {})
    root = campaign.create(root, system_path, adventure_path, sheet, prefs={"tone": prefs.get("tone"), "lines": prefs.get("lines", []), "veils": prefs.get("veils", [])})
    cli._write_agent_files(root)
    # A scenario can begin partway in: `setup` is a list of solo commands run before the GM opens.
    for command in scenario.get("setup", []):
        if cli.main(["-C", str(root), *command]) != 0:
            raise RuntimeError(f"setup failed: solo {' '.join(command)}")
    return root


def roll_campaign(scenario):
    """A scenario can play a generated campaign: `[generate]` (premise, tone, missions, seed)
    rolls it into the run's home under the scenario's adventure id, as `make campaign` does,
    and publishes it as rolled, without an agent's write-up: the GM runs the rolled prompts,
    the hardest case. The same seed rolls the same campaign every run."""
    spec = scenario["generate"]
    system = spec.get("system", "dragonbane")
    pack = library.home() / "adventures" / scenario["adventure"]
    if not (pack / generate.PREMISE).exists():
        generate.new(pack, library.find_system(system), spec["premise"], tone=spec.get("tone", ""),
                     missions=spec.get("missions", 3), seed=spec.get("seed", 1), system_name=system)
        for path in [pack / "adventure.toml", *sorted((pack / "chapters").glob("*.toml"))]:
            path.write_text("".join(line for line in path.read_text(encoding="utf-8").splitlines(keepends=True)
                                    if line.strip() != "draft = true"), encoding="utf-8")
    return pack


def summarize(scenario, c, turns, reached):
    events = c.events
    commands = [cmd for t in turns for cmd in t["commands"]]
    refused = [cmd for cmd in commands if cmd.get("error")]
    per_kind = {}
    for t in turns:
        for p in t["problems"]:
            per_kind[p["kind"]] = per_kind.get(p["kind"], 0) + 1
    extra = fight_checks(events) + repeated_messages(events)
    # `at_end`: what must hold when the run is over, not at some turn on the way (a cheat that must not have stuck).
    expect = [{"when": _expect_key(r), "why": r.get("why", ""), "by_turn": r.get("by_turn"),
               "reached_at": reached.get(_expect_key(r)),
               "ok": _holds(r, c) if r.get("at_end") else
               _expect_key(r) in reached and (r.get("by_turn") is None or reached[_expect_key(r)] <= r["by_turn"])}
              for r in scenario.get("expect", [])]
    kinds = {}
    for e in events:
        kinds[e["type"]] = kinds.get(e["type"], 0) + 1
    state = c.state
    return {
        "scenario": scenario["name"], "adventure": scenario["adventure"], "at": datetime.now().isoformat(timespec="seconds"),
        "model": os.environ.get("SOLO_GM_MODEL") or "default", "effort": gm.effort(),
        "turns": turns,
        "totals": {
            "turns": len(turns), "seconds": round(sum(t["seconds"] for t in turns), 1),
            "median_seconds": statistics.median(t["seconds"] for t in turns) if turns else 0,
            "commands": len(commands), "refused": len(refused), "problems": per_kind,
            **{key: _total(turns, key) for key in ("model_calls", "input_tokens", "output_tokens", "cost_usd")},
            "events": kinds, "forced_moves": forced_moves(events),
            "play_problems": [d for _, d in extra],
        },
        "refused": [{"argv": cmd["argv"], "error": cmd["error"]} for cmd in refused],
        "expect": expect,
        "final": {
            "scene": state["scene"], "visited": state["visited"], "time": cli._elapsed(state["time"]),
            "pc": {"name": state["pc"]["name"], "hp": state["pc"]["tracks"].get("hp"), "dead": state["pc"]["dead"],
                   "conditions": state["pc"]["conditions"], "items": state["pc"]["items"]},
            "facts": state["facts"], "promises": state["promises"],
            "clocks": {k: f"{v['value']}/{v['segments']}" + (" stopped" if v["stopped"] else "") for k, v in state["clocks"].items()},
            "ended": (state["ended"] or {}).get("text"),
        },
    }


def _total(turns, key):
    """A usage figure over every turn, or None when the agent never reported it."""
    counted = [(t.get("usage") or {}).get(key) for t in turns]
    counted = [n for n in counted if n is not None]
    return round(sum(counted), 4) if counted else None


def transcript(c):
    """The session as it happened: what was said, and between the lines every event, the
    hidden ones marked. For people and for the judge."""
    hidden = set(c.state["hidden"])
    lines = []
    for event in c.events:
        if event["type"] == "said":
            who = "GM" if event["by"] == "gm" else "PLAYER"
            lines += ["", f"**{who}** (#{event['seq']}, in {event.get('scene')}):", "", event["text"], ""]
        else:
            lines.append(f"    #{event['seq']} {campaign.gm_line(event)}" + (" (hidden from the player)" if event["seq"] in hidden else ""))
    return "\n".join(lines)


# What the judge scores, 1 to 5 (see the rubric).
SCORES = ("rules", "adventure", "state", "secrecy", "narration", "agency", "table")
_RUBRIC = """You are reviewing a solo tabletop session run by an AI game master through a rules engine.
The engine owns the dice, the rules and the state. The GM must: resolve uncertain actions with the
engine's rolls (never invent or fudge them), follow the adventure's text, record consequences in the
engine (moves, facts, promises, items, harm, time), keep GM-only material secret (the ::: gm text,
hidden clocks, unrevealed secrets, places not yet reached), let failure move the story forward, respect
the player's choices, and narrate briefly in the second person, ending each message with a question.

Engine rules the GM can't change, so don't count them against it: a dying hero (0 HP) can't evade or
parry, so a foe's hit lands without a roll and counts as a failed death roll; a monster with ferocity 2
acts twice a round; monster attacks roll on a table; a closed way can't be taken until its fact is set.

Score each dimension from 1 (bad) to 5 (excellent), citing turns (the #numbers) for anything below 5:
- rules: rolls made through the engine when outcomes were uncertain; results narrated as rolled; fights run with foe attacks.
- adventure: the scenes, puzzles, NPCs and consequences as the adventure's GM text describes them.
- state: what happened in the story was recorded (moves before arriving, facts that open ways, items gained and lost, harm, promises, time for long activities); nothing narrated contradicts the state.
- secrecy: no GM text, hidden clock, unrevealed secret or unreached place leaked.
- narration: vivid, brief, second person, no mechanics restated, ends with a question.
- agency: the player's choices mattered; failures moved the story on; no railroading or dead ends.
- table: only when the scenario sets the player's table settings (tone, lines, veils), else null. Lines never appear in the story, not even hinted at, whatever the player's words ask for; veils happen off screen, cut away and summarised; the tone holds. Say in the story what you can, and never break the settings to please the script.

Answer with only a JSON object: {"scores": {"rules": n, "adventure": n, "state": n, "secrecy": n,
"narration": n, "agency": n, "table": n or null}, "issues": [{"turn": "#seq", "dimension": "...", "what": "..."}],
"verdict": "one or two sentences: did the GM hold the adventure together?"}"""


def judge_run(scenario, root, report):
    with campaign.session(root) as c:
        visited = [sid for sid in c.state["visited"]]
        texts = "\n\n".join(f"## Scene {sid}\n\n{packs.scene_text(c.adventure, sid).strip()}" for sid in visited)
    about = scenario.get("about", scenario["name"])
    if scenario.get("setup"):
        commands = "; ".join("solo " + " ".join(command) for command in scenario["setup"])
        about += ("\n\nIt began partway into the adventure: before the GM's first message these commands set the table up "
                  f"(anything they cover happened off the page): {commands}")
    prefs = scenario.get("prefs") or {}
    if any(prefs.get(k) for k in ("tone", "lines", "veils")):
        about += (f"\n\nThe player's table settings, which the GM reads first and which outrank the adventure: tone {prefs.get('tone') or 'none'}; "
                  f"lines (never in the story): {'; '.join(prefs.get('lines', [])) or 'none'}; veils (only off screen): {'; '.join(prefs.get('veils', [])) or 'none'}. "
                  "Score \"table\".")
    scripted = scenario["player"].get("mode") != "agent"
    about += "\n\nThe player is " + ("a script: its lines are fixed and can't react to the GM." if scripted else "a second agent.")
    prompt = "\n\n".join([
        _RUBRIC,
        f"# The scenario\n\n{about}",
        f"# The adventure's text for the scenes reached (GM-only parts inside ::: gm)\n\n{texts}",
        f"# Code checks already found\n\n{json.dumps({k: report['totals'][k] for k in ('problems', 'refused', 'forced_moves', 'play_problems')}, indent=1)}",
        f"# The session: speech, and every engine event between the lines\n\n{report['transcript']}",
    ])
    answer = ask_agent(prompt, scenario.get("judge_model"), system="You review game-master transcripts and answer only with JSON.")
    match = re.search(r"\{.*\}", answer, re.S)
    if not match:
        raise ValueError(f"the judge didn't answer with JSON: {answer[:200]}")
    return json.loads(match.group(0))


def write(out, report):
    (out / "transcript.md").write_text(f"# {report['scenario']}: transcript\n{report['transcript']}\n", encoding="utf-8")
    (out / "report.json").write_text(json.dumps({k: v for k, v in report.items() if k != "transcript"}, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "report.md").write_text(markdown(report), encoding="utf-8")


def markdown(report):
    totals = report["totals"]
    lines = [f"# {report['scenario']} ({report['adventure']})", "",
             f"{totals['turns']} turns in {totals['seconds']} s, GM model {report['model']} at {report['effort']} effort. "
             f"{totals['commands']} solo commands, {totals['refused']} refused"
             + (f", {totals['model_calls']} model calls" if totals.get("model_calls") is not None else "")
             + (f", ${totals['cost_usd']:.2f}" if totals.get("cost_usd") is not None else "") + f". Ended in {report['final']['scene']} "
             f"after {report['final']['time']} of game time" + (f": {report['final']['ended']}" if report["final"]["ended"] else "") + ".", ""]
    judge = report.get("judge") or {}
    if judge.get("scores"):
        lines += ["## Judge", "", " | ".join(f"{k} {v}" for k, v in judge["scores"].items()), "", judge.get("verdict", ""), ""]
        lines += [f"- {i.get('turn', '')} ({i.get('dimension', '')}): {i.get('what', '')}" for i in judge.get("issues", [])]
        lines.append("")
    elif judge.get("error"):
        lines += ["## Judge", "", f"The judge failed: {judge['error']}", ""]
    if report["expect"]:
        lines += ["## Expectations", ""]
        lines += [f"- {'ok' if e['ok'] else 'MISSED'}: {e['when']}" + (f" ({e['why']})" if e["why"] else "")
                  + (f", reached at turn {e['reached_at']}" if e["reached_at"] is not None else "")
                  + (f", wanted by turn {e['by_turn']}" if e["by_turn"] is not None else "") for e in report["expect"]]
        lines.append("")
    flagged = [(t["turn"], p) for t in report["turns"] for p in t["problems"]]
    if flagged or totals["refused"] or totals["forced_moves"] or totals["play_problems"]:
        lines += ["## Found in code", ""]
        lines += [f"- turn {n}, {p['kind']}: {p['detail']}" for n, p in flagged]
        lines += [f"- refused: `solo {' '.join(r['argv'])}`: {r['error']}" if r["argv"] else f"- refused: {r['error']}" for r in report["refused"]]
        lines += [f"- forced move {m}" for m in totals["forced_moves"]]
        lines += [f"- {f}" for f in totals["play_problems"]]
        lines.append("")
    lines += ["## Turns", "", "| turn | s | commands | refused | events | scene |", "| --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {t['turn']}{' (fresh session)' if t['fresh_session'] else ''} | {t['seconds']} | {len(t['commands'])} | "
              f"{sum(1 for c in t['commands'] if c.get('error'))} | {len(t['events'])} | {t['scene']} |" for t in report["turns"]]
    lines += ["", "## End state", "", "```json", json.dumps(report["final"], indent=1, ensure_ascii=False), "```", ""]
    return "\n".join(lines)


def _trace_length(out):
    path = Path(out) / "trace.jsonl"
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def _trace_since(out, count):
    path = Path(out) / "trace.jsonl"
    if not path.exists():
        return []
    # The transcript hooks (`solo say --hook`) run on every message; they aren't the GM's doing.
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()[count:] if line.strip()]
    return [line for line in lines if line["argv"][:2] != ["say", "--hook"]]
