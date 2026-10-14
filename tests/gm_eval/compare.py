"""Did a change to the GM's instructions help? python3 tests/gm_eval/compare.py <commit A> <commit B> [options]

Reads results.tsv (every run adds a line) and, scenario by scenario, sets the runs of one commit beside the
runs of another, for each score and each cost. A difference only counts when a permutation test says runs
that differ this much would rarely come from commits that play alike: the judge and the GM both vary, so
one run of each says nothing, and three of each say little. The level is 0.05 shared out over every
comparison made (Bonferroni), so that among a dozen scores one isn't called better by chance. Play each
commit with --repeat 3 or more (and a fixed --seed) before comparing, and commit before you measure: a
"-dirty" commit is whatever the tree was that day, so its runs are left out unless --dirty asks for them.
"""

import argparse
import csv
import itertools
import math
import random
import statistics
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results.tsv"
# (column, higher is better)
METRICS = [("rules", True), ("adventure", True), ("state", True), ("secrecy", True), ("narration", True), ("agency", True), ("table", True),
           ("expectations", True), ("refused", False), ("median_s", False), ("commands_per_turn", False), ("model_calls_per_turn", False), ("cost_usd", False)]
# The chance of calling one comparison better or worse by luck, before it is shared out over all of them.
ALPHA = 0.05
# Fewer runs than this on either side, and a comparison says so instead of a verdict.
FEWEST = 3
# Every way of splitting the runs is tried while there are no more than this many; past it, this many
# random splits, drawn with a fixed seed, so the same results always give the same answer.
SPLITS = 20_000
SEED = 1


def load(path=RESULTS):
    with open(path, encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file, delimiter="\t"))


def number(row, column):
    """A cell as a number: "3/4" expectations are 0.75, a blank is missing."""
    text = (row.get(column) or "").strip()
    if not text:
        return None
    try:
        if "/" in text:
            met, total = text.split("/")
            return int(met) / int(total) if int(total) else None
        return float(text)
    except ValueError:
        return None


def runs(rows, commit, scenario=None, model=None, effort=None, dirty=False):
    """The rows of one commit (a prefix of it is enough), optionally of one scenario, model and effort.
    The model is the one a run asked for ("sonnet", "default") or the one the agent named ("claude-sonnet-5-5").
    A "-dirty" commit's rows only with `dirty`."""
    return [r for r in rows if r["commit"].startswith(commit) and (dirty or not r["commit"].endswith("-dirty"))
            and (not scenario or r["scenario"] == scenario) and (not effort or r["effort"] == effort)
            and (not model or r["model"] == model or model in (r.get("resolved_model") or "").split(", "))]


def permutation_p(groups, seed=SEED):
    """(p, floor) for the gap between the B runs' mean and the A runs', each group being (A values, B values)
    of one scenario. p is the share of the ways of relabelling the runs, within each group, that give a gap at
    least as wide either way; floor is the smallest p this many runs could give at all, whatever their values."""
    pooled = [(xs + ys, len(xs)) for xs, ys in groups]
    size_a = sum(k for _, k in pooled)
    size_b = sum(len(values) - k for values, k in pooled)
    total = sum(sum(values) for values, _ in pooled)

    def gap(chosen):
        sum_a = sum(values[i] for (values, _), picks in zip(pooled, chosen) for i in picks)
        return (total - sum_a) / size_b - sum_a / size_a

    observed = abs(gap([range(k) for _, k in pooled]))
    ways = math.prod(math.comb(len(values), k) for values, k in pooled)
    if ways <= SPLITS:
        gaps = [abs(gap(c)) for c in itertools.product(*(itertools.combinations(range(len(values)), k) for values, k in pooled))]
        # At best only the runs as they fell give the widest gap, and their mirror (every label swapped) when each
        # scenario has as many runs of A as of B. Not the widest gap of these values: a score every run gave alike
        # (refused 0, a fixed cost), or all but one, gives the same gap every way, and that isn't too few runs.
        mirrored = all(len(values) == 2 * k for values, k in pooled)
        return sum(g >= observed - 1e-9 for g in gaps) / ways, (2 if mirrored else 1) / ways
    rng = random.Random(seed)
    hits = sum(abs(gap([rng.sample(range(len(values)), k) for values, k in pooled])) >= observed - 1e-9 for _ in range(SPLITS))
    return (hits + 1) / (SPLITS + 1), 1 / (SPLITS + 1)


def compare(a, b, comparisons=None, alpha=ALPHA):
    """{metric: line} for two lists of runs. A run is only set against runs of its own scenario: two lists that
    hold several scenarios are compared within each (pooled). The verdict is `better` or `worse` (for B against
    A) when the permutation test's p is below `alpha` shared out over `comparisons` (default: the metrics with
    enough runs here), `same` when it isn't, and `too few runs` with fewer than FEWEST of either."""
    lines, groups = {}, {}
    scenarios = sorted({r["scenario"] for r in a} & {r["scenario"] for r in b})
    for column, higher in METRICS:
        found = [([v for v in (number(r, column) for r in a if r["scenario"] == s) if v is not None],
                  [v for v in (number(r, column) for r in b if r["scenario"] == s) if v is not None]) for s in scenarios]
        found = [(xs, ys) for xs, ys in found if xs and ys]
        if found:
            xs, ys = [v for g in found for v in g[0]], [v for g in found for v in g[1]]
            lines[column] = {"a": xs, "b": ys, "mean_a": statistics.mean(xs), "mean_b": statistics.mean(ys), "higher": higher}
            groups[column] = found
    tested = [column for column, line in lines.items() if len(line["a"]) >= FEWEST and len(line["b"]) >= FEWEST]
    level = alpha / (comparisons or len(tested) or 1)
    for column, line in lines.items():
        line["level"] = level
        if column not in tested:
            line["verdict"] = "too few runs"
            continue
        line["p"], line["floor"] = permutation_p(groups[column])
        if line["p"] >= level:
            line["verdict"] = "same"
        else:
            line["verdict"] = "better" if (line["mean_b"] > line["mean_a"]) == line["higher"] else "worse"
    return lines


def render(a_name, b_name, sections):
    """sections: [(title, A runs, B runs, result)]."""
    lines = []
    level = next((line["level"] for _, _, _, result in sections for line in result.values()), None)
    for title, a, b, result in sections:
        lines += [f"## {title}: {len(a)} runs of {a_name}, {len(b)} of {b_name}", ""]
        if not result:
            lines += ["Nothing to compare: no run of either has these columns filled.", ""]
            continue
        width = max(len(m) for m in result)
        lines.append(f"{'':{width}}  {a_name:>12}  {b_name:>12}  {'p':>7}  verdict")
        for column, line in result.items():
            p = f"{line['p']:.4f}" if "p" in line else "-"
            lines.append(f"{column:{width}}  {line['mean_a']:>12.2f}  {line['mean_b']:>12.2f}  {p:>7}  {line['verdict']}")
        lines.append("")
    every = [line for _, _, _, result in sections for line in result.values()]
    # Only when a comparison was made: with none, there is no level to give.
    if level is not None and any(line["verdict"] != "too few runs" for line in every):
        made = round(ALPHA / level)
        lines.append(f"better and worse are for {b_name} against {a_name}, and count only when a permutation test gives p below "
                     f"{level:.4g}: {ALPHA:g} shared out over the {made} comparison{'s' if made != 1 else ''} made (Bonferroni).")
    if any(line["verdict"] == "too few runs" for line in every):
        lines.append(f"Some have too few runs to say anything: play each commit with --repeat {FEWEST} or more.")
    if any(line.get("floor", 0) >= line["level"] for line in every):
        lines.append("Some have too few runs for any difference to count, however large: same there means not shown, not equal. "
                     "Play more runs of each commit.")
    return "\n".join(lines).rstrip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("a", help="the commit to compare from (a prefix is enough)")
    parser.add_argument("b", help="the commit to compare to")
    parser.add_argument("--scenario", help="only this scenario's runs")
    parser.add_argument("--pool", action="store_true", help="one comparison over every scenario both commits played, instead of one each")
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument("--dirty", action="store_true", help="count runs of a -dirty commit too")
    parser.add_argument("--results", default=str(RESULTS))
    args = parser.parse_args(argv)
    rows = load(args.results) if Path(args.results).exists() else []
    a = runs(rows, args.a, args.scenario, args.model, args.effort, args.dirty)
    b = runs(rows, args.b, args.scenario, args.model, args.effort, args.dirty)
    if not a or not b:
        print(f"no runs for {args.a if not a else args.b} in {args.results}: play it first (python3 tests/gm_eval/run.py --repeat 3 --seed 1)"
              + ("" if args.dirty else "; runs of a -dirty commit count only with --dirty"), file=sys.stderr)
        return 1
    only_a = sorted({r["scenario"] for r in a} - {r["scenario"] for r in b})
    only_b = sorted({r["scenario"] for r in b} - {r["scenario"] for r in a})
    scenarios = sorted({r["scenario"] for r in a} & {r["scenario"] for r in b})
    if only_a or only_b:
        missing = "; ".join(filter(None, [f"only {args.a} played {', '.join(only_a)}" if only_a else "",
                                          f"only {args.b} played {', '.join(only_b)}" if only_b else ""]))
        if args.pool or not scenarios:
            print(f"the two commits didn't play the same scenarios ({missing}): play them, or compare one with --scenario", file=sys.stderr)
            return 1
        print(f"Left out, since only one commit played them: {missing}.\n")
    if args.pool:
        sections = [(f"{len(scenarios)} scenarios pooled", a, b)]
    else:
        sections = [(s, [r for r in a if r["scenario"] == s], [r for r in b if r["scenario"] == s]) for s in scenarios]
    # The level is shared out over every comparison that gets a verdict, in every section.
    comparisons = sum(1 for _, x, y in sections for line in compare(x, y).values() if line["verdict"] != "too few runs")
    print(render(args.a, args.b, [(title, x, y, compare(x, y, comparisons or 1)) for title, x, y in sections]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
