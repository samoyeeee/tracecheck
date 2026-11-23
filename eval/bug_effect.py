"""Did each planted bug make the agent worse at all? (post-hoc, no model calls)

    python -m eval.bug_effect        # -> results/bug_effect.json

For every bug, on its own 20 pre-registered tasks: tau2 success rate of the bug
version vs v1, and the noise band of that difference taken from v1 vs v1_rerun
(same method as eval/regression_by_type.py: pool the 8 trials per task, split
4/4 at random). If the bug's change is inside the band, the bug did not make
the agent measurably worse, so "not detected" is the right answer for that bug;
if it is outside, a detector that missed it really missed something.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.regression_by_type import band, outcomes, pass_k  # noqa: E402

SEED = 2027


def main() -> int:
    v1, rerun = outcomes("v1"), outcomes("v1_rerun")
    plans = {**json.loads((ROOT / "results/regression_plan.json").read_text())["runs"],
             **json.loads((ROOT / "results/regression_plan_4b.json").read_text())["runs"]}
    mech = json.loads((ROOT / "results/bug_mechanism_check.json").read_text())["bugs"]
    det = {**json.loads((ROOT / "results/eval_regression.json").read_text())["bugs"],
           **json.loads((ROOT / "results/eval_regression_4b.json").read_text())["bugs"]}
    rng = random.Random(SEED)
    out = {}
    for name in ("bug_auth", "bug_transfer", "bug_noconfirm", "bug_param", "bug_addr2", "bug_dropitem"):
        tasks = plans[name]["tasks"]
        bug = outcomes(name)
        old, new = pass_k([v1[t] for t in tasks], 1), pass_k([bug[t] for t in tasks], 1)
        lo, hi = band(v1, rerun, tasks, 1, rng)
        diff = new - old
        worse = diff < lo - 1e-9
        out[name] = {
            "tasks": len(tasks), "success_v1": round(old, 4), "success_bug": round(new, 4),
            "diff": round(diff, 4), "noise_band": [round(lo, 4), round(hi, 4)],
            "agent_measurably_worse": worse,
            "behaviour_targeted": mech.get(name),
            "detected_by_tracecheck": det[name]["detected"],
            "reading": ("worse and detected" if worse and det[name]["detected"] else
                        "worse but NOT detected: a TraceCheck miss" if worse else
                        "not measurably worse; detected anyway" if det[name]["detected"] else
                        "not measurably worse, not detected: the bug, not the detector, was too weak"),
        }
    res = {"post_hoc": True, "seed": SEED, "metric": "tau2 success (pass^1) on the bug's 20 tasks",
           "sources": ["results/triage/v1.json", "results/triage/v1_rerun.json", "results/regression_plan.json",
                       "results/regression_plan_4b.json", "results/bug_mechanism_check.json"],
           "bugs": out}
    (ROOT / "results/bug_effect.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    for n, r in out.items():
        print(f"{n:14s} v1 {r['success_v1']:.3f} -> bug {r['success_bug']:.3f}  diff {r['diff']:+.3f}  "
              f"band [{r['noise_band'][0]:+.3f},{r['noise_band'][1]:+.3f}]  -> {r['reading']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
