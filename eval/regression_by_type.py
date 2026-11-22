"""Per task type: v1 vs v2 pass^k, with a noise band taken from v1 vs v1.

    python -m eval.regression_by_type      # -> results/regression_by_type.json

POST-HOC (not in results/regression_plan.json): the pre-registered test is the
per-task noise threshold in results/eval_regression.json. This adds a band per
task type for the comparison table: for every task, the 8 trials of v1 and
v1_rerun are pooled and randomly split 4/4 many times; the 2.5-97.5 percentile
of the resulting pass^k difference is what the same agent produces by chance.
A v2 change outside that band is marked "beyond noise".
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.eval_regression import task_types  # noqa: E402

DRAWS = 5000
SEED = 2026
K = (1, 4)


def outcomes(tag: str) -> dict[str, list[int]]:
    by = defaultdict(list)
    for r in json.loads((ROOT / "results" / "triage" / f"{tag}.json").read_text()):
        by[r["task_id"]].append(1 if r["tau2_success"] else 0)
    return by


def pass_k(trials: list[list[int]], k: int) -> float:
    vals = [comb(sum(t), k) / comb(len(t), k) for t in trials if len(t) >= k]
    return sum(vals) / len(vals) if vals else 0.0


def band(v1: dict, rerun: dict, tasks: list[str], k: int, rng: random.Random) -> list[float]:
    diffs = []
    for _ in range(DRAWS):
        a, b = [], []
        for t in tasks:
            pool = v1[t] + rerun[t]
            rng.shuffle(pool)
            a.append(pool[:4]); b.append(pool[4:8])
        diffs.append(pass_k(b, k) - pass_k(a, k))
    diffs.sort()
    return [diffs[int(0.025 * DRAWS)], diffs[int(0.975 * DRAWS) - 1]]   # unrounded: compared before display


def main() -> int:
    v1, rerun, v2 = outcomes("v1"), outcomes("v1_rerun"), outcomes("v2")
    types = task_types()
    groups = defaultdict(list)
    for t, ts in types.items():
        for name in ts:
            groups[name].append(t)
    groups["all"] = sorted(types, key=int)
    rng = random.Random(SEED)
    rows = {}
    for name, tasks in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        row = {"tasks": len(tasks)}
        for k in K:
            old, new = pass_k([v1[t] for t in tasks], k), pass_k([v2[t] for t in tasks], k)
            lo, hi = band(v1, rerun, tasks, k, rng)
            diff = new - old
            eps = 1e-9   # a change exactly on the band edge is inside the band
            row[f"pass{k}"] = {"v1": round(old, 4), "v2": round(new, 4), "diff": round(diff, 4),
                               "v1_rerun": round(pass_k([rerun[t] for t in tasks], k), 4),
                               "noise_band": [round(lo, 4), round(hi, 4)],
                               "verdict": "better" if diff > hi + eps else "worse" if diff < lo - eps else "noise"}
        rows[name] = row
    out = {"what": __doc__.strip().splitlines()[0], "post_hoc": True, "draws": DRAWS, "seed": SEED,
           "sources": ["results/triage/v1.json", "results/triage/v1_rerun.json", "results/triage/v2.json"],
           "type_note": "a task with several kinds of write counts under each of them", "by_type": rows}
    path = ROOT / "results" / "regression_by_type.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    for n, r in rows.items():
        print(n, r["tasks"], {k: (r[k]["v1"], r[k]["v2"], r[k]["noise_band"], r[k]["verdict"]) for k in ("pass1", "pass4")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
