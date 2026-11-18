"""Phase-4b analysis, following results/regression_plan_4b.json exactly.

    python -m eval.eval_regression_4b      # -> results/eval_regression_4b.json

For each code-level bug: per-task false-success rate (bug vs v1) with a paired
sign-flip test, Holm across the two bugs; localisation from the database
diffs of the flagged claims; the same test on v1_rerun vs v1 as the
false-alarm control.
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.eval_regression import ALPHA, PERMUTATIONS, holm, sign_flip_p, triage  # noqa: E402
from triage.schema import FALSE_SUCCESS_STATUSES  # noqa: E402

SIGNATURE = {
    "bug_addr2": re.compile(r"address2$"),
    "bug_dropitem": re.compile(r"^(return_items|exchange_items|exchange_new_items)|^items\[\d+\]\.item_id$"),
}


def rate_by_task(reports: list[dict], tasks: set[str], field: str) -> dict[str, float]:
    by: dict[str, list[float]] = defaultdict(list)
    for r in reports:
        if r["task_id"] in tasks:
            by[r["task_id"]].append(1.0 if r[field] else 0.0)
    return {t: sum(v) / len(v) for t, v in by.items()}


def test(base: list[dict], other: list[dict], tasks: set[str], seed: int, field: str = "false_success") -> dict:
    b, o = rate_by_task(base, tasks, field), rate_by_task(other, tasks, field)
    common = sorted(set(b) & set(o), key=int)
    diffs = [o[t] - b[t] for t in common]
    return {"tasks": len(common),
            "base_rate": round(sum(b[t] for t in common) / len(common), 4),
            "other_rate": round(sum(o[t] for t in common) / len(common), 4),
            "diff": round(sum(diffs) / len(diffs), 4),
            "tasks_up": sum(d > 0 for d in diffs), "tasks_down": sum(d < 0 for d in diffs),
            "p": round(sign_flip_p(diffs, random.Random(seed)), 4)}


def flagged_diff_paths(report: dict) -> list[str]:
    return [f["path"] for c in report["claims"] if c["status"] in FALSE_SUCCESS_STATUSES
            for d in c.get("diff") or [] for f in d.get("fields") or []]


def localisation(reports: list[dict], tasks: set[str], pattern: re.Pattern) -> dict:
    flagged = [r for r in reports if r["task_id"] in tasks and r["false_success"]]
    hits = [r for r in flagged if any(pattern.search(p) for p in flagged_diff_paths(r))]
    share = len(hits) / len(flagged) if flagged else None
    return {"flagged_runs": len(flagged), "flagged_runs_naming_field": len(hits),
            "share": None if share is None else round(share, 4),
            "localised": share is not None and share >= 0.5}


def main() -> int:
    plan = json.loads((ROOT / "results" / "regression_plan_4b.json").read_text())
    v1, rerun = triage("v1"), triage("v1_rerun")
    out: dict = {"plan": "results/regression_plan_4b.json", "alpha": ALPHA, "permutations": PERMUTATIONS,
                 "bugs": {}, "false_alarms": {}}
    for i, (name, run) in enumerate(plan["runs"].items()):
        tasks = set(run["tasks"])
        reports = triage(name)
        expected = len(tasks) * plan["k"]
        primary = test(v1, reports, tasks, seed=i)
        out["bugs"][name] = {
            "description": run["description"], "runs": len(reports), "runs_expected": expected,
            "primary": primary,
            "localisation_bug": localisation(reports, tasks, SIGNATURE[name]),
            "localisation_v1_same_tasks": localisation(v1, tasks, SIGNATURE[name]),
            "context_tau2_success": test(v1, reports, tasks, seed=100 + i, field="tau2_success"),
        }
        out["false_alarms"][name] = test(v1, rerun, tasks, seed=200 + i)
    adj = holm({n: b["primary"]["p"] for n, b in out["bugs"].items()})
    for n, b in out["bugs"].items():
        b["primary"]["p_holm"] = round(adj[n], 4)
        b["detected"] = b["primary"]["diff"] > 0 and adj[n] < ALPHA
        b["localised"] = b["localisation_bug"]["localised"]
    fa = holm({n: r["p"] for n, r in out["false_alarms"].items()})
    for n, r in out["false_alarms"].items():
        r["p_holm"] = round(fa[n], 4)
        r["false_alarm"] = fa[n] < ALPHA
    out["complete"] = all(b["runs"] == b["runs_expected"] for b in out["bugs"].values())
    out["summary"] = {
        "bugs_detected": f"{sum(b['detected'] for b in out['bugs'].values())}/{len(out['bugs'])}",
        "bugs_localised": f"{sum(b['detected'] and b['localised'] for b in out['bugs'].values())}/{len(out['bugs'])}",
        "false_alarms_v1_vs_v1": sum(r["false_alarm"] for r in out["false_alarms"].values()),
    }
    path = ROOT / "results" / "eval_regression_4b.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
