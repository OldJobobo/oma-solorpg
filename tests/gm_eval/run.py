"""Run GM play tests: python3 tests/gm_eval/run.py <scenario>... [options]

Each scenario plays into runs/<scenario>-<time>/ beside this file (git-ignored), and a
summary of every run is printed at the end and added to results.tsv (checked in), so runs
before and after a change can be compared. See README.md.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results.tsv"
COLUMNS = ("at", "scenario", "commit", "agent", "model", "effort", "seed", "run", "turns", "median_s", "commands_per_turn", "model_calls_per_turn",
           "refused", "cost_usd", *harness.SCORES, "expectations")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenarios", nargs="*", help="scenario names (scenarios/<name>.toml) or files; default: all")
    parser.add_argument("--agent", default="claude", help="the GM agent (claude, codex, pi)")
    parser.add_argument("--model", help="the GM's model (default: the agent's own default)")
    parser.add_argument("--effort", help="the GM's effort level, e.g. low, medium, high (default: the normal pace's)")
    parser.add_argument("--turns", type=int, help="cap every scenario at this many player turns")
    parser.add_argument("--repeat", type=int, default=1, help="play every scenario this many times: one run says little, and compare.py needs the spread")
    parser.add_argument("--seed", type=int, help="fix the dice (SOLO_SEED), so runs meet the same rolls in the same state")
    parser.add_argument("--no-judge", action="store_true", help="skip the judge's review")
    parser.add_argument("--out", help="the folder for runs (default: tests/gm_eval/runs)")
    args = parser.parse_args()
    names = args.scenarios or sorted(p.stem for p in harness.SCENARIOS.glob("*.toml"))
    base = Path(args.out) if args.out else Path(__file__).resolve().parent / "runs"
    reports = []
    for name, repeat in [(name, repeat) for name in names for repeat in range(1, args.repeat + 1)]:
        scenario = harness.load(name)
        out = base / f"{scenario['name']}-{datetime.now():%Y%m%d-%H%M%S}"
        print(f"{scenario['name']}" + (f" (run {repeat} of {args.repeat})" if args.repeat > 1 else "") + f": playing into {out}")
        report = harness.run(scenario, out, agent=args.agent, model=args.model, effort=args.effort, judge=not args.no_judge, max_turns=args.turns, seed=args.seed)
        report["seed"], report["run"] = args.seed, repeat
        reports.append((out, report))
        record(report)
    print()
    for out, report in reports:
        totals, judge = report["totals"], report.get("judge") or {}
        missed = [e["when"] for e in report["expect"] if not e["ok"]]
        print(f"{report['scenario']}: {totals['turns']} turns, {totals['refused']} refused commands, problems {json.dumps(totals['problems'])}"
              + (f", judge {json.dumps(judge.get('scores'))}" if judge.get("scores") else "")
              + (f", MISSED {missed}" if missed else ", expectations met"))
        print(f"  {out / 'report.md'}")


def record(report):
    """One line in results.tsv for a run: how long a turn took, what it cost, and what the judge said."""
    totals = report["totals"]
    scores = (report.get("judge") or {}).get("scores") or {}
    per_turn = lambda n: "" if n is None or not totals["turns"] else f"{n / totals['turns']:.1f}"
    commit = subprocess.run(["git", "describe", "--always", "--dirty"], cwd=harness.REPO, capture_output=True, text=True).stdout.strip()
    row = {
        "at": report["at"], "scenario": report["scenario"], "commit": commit, "agent": report.get("agent", ""), "model": report["model"], "effort": report.get("effort", ""),
        "seed": "" if report.get("seed") is None else report["seed"], "run": report.get("run", 1),
        "turns": totals["turns"], "median_s": totals["median_seconds"], "commands_per_turn": per_turn(totals["commands"]),
        "model_calls_per_turn": per_turn(totals.get("model_calls")), "refused": totals["refused"],
        "cost_usd": "" if totals.get("cost_usd") is None else f"{totals['cost_usd']:.2f}",
        **{key: "" if scores.get(key) is None else scores[key] for key in harness.SCORES},
        "expectations": f"{sum(e['ok'] for e in report['expect'])}/{len(report['expect'])}",
    }
    new = not RESULTS.exists()
    with open(RESULTS, "a", encoding="utf-8") as results:
        if new:
            results.write("\t".join(COLUMNS) + "\n")
        results.write("\t".join(str(row[key]) for key in COLUMNS) + "\n")


if __name__ == "__main__":
    main()
