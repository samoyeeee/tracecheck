"""Write the phase-4b plan BEFORE any phase-4b run (pre-registration).

    python -m eval.regression_plan_4b     # -> results/regression_plan_4b.json

Phase 4 found 0/4 planted bugs (results/eval_regression.json). The post-hoc
check (results/bug_mechanism_check.json) showed two of those bugs barely
changed behaviour, and testing 20 metrics with Holm correction on 20 tasks
could not reach significance when an effect sits in a few tasks. Phase 4b
fixes both, in advance:
  - two bugs in the agent's tool-calling code that always take effect
    whenever the affected tool is called with the affected argument;
  - ONE primary metric per bug, named here before any run;
  - tasks drawn only from those where the bug can take effect.
eval/eval_regression_4b.py reads this file and changes none of it.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SEED = 405
SUBSET = 20


def eligible() -> dict[str, list[str]]:
    """Tasks whose reference actions include the argument each bug corrupts."""
    from agent.versions import ADDRESS_TOOLS, ITEM_TOOLS

    tasks = json.loads((ROOT / "vendor/tau2-bench/data/tau2/domains/retail/tasks.json").read_text())
    pools: dict[str, set[str]] = {"bug_addr2": set(), "bug_dropitem": set()}
    for t in tasks:
        for a in (t.get("evaluation_criteria") or {}).get("actions") or []:
            args = a.get("arguments") or {}
            if a["name"] in ADDRESS_TOOLS and args.get("address2"):
                pools["bug_addr2"].add(str(t["id"]))
            if a["name"] in ITEM_TOOLS and len(args.get("item_ids") or []) >= 2:
                pools["bug_dropitem"].add(str(t["id"]))
    return {k: sorted(v, key=int) for k, v in pools.items()}


def main() -> int:
    from agent.versions import SPECS

    pools = eligible()
    rng = random.Random(SEED)
    plan = {
        "written_before_runs": True,
        "seed": SEED,
        "k": 4,
        "baseline": "existing v1 runs (results/runs/v1); noise control: existing v1_rerun runs",
        "runs": {
            name: {"agent": name, "tasks": sorted(rng.sample(pool, min(SUBSET, len(pool))), key=int),
                   "eligible_pool_size": len(pool), "description": SPECS[name].description}
            for name, pool in pools.items()
        },
        "primary_metric": "false_success: per run, TraceCheck flags a claim of completion that the database "
                          "does not back (claim status not_executed or executed_but_differs); aggregated per "
                          "task as the mean over its k trials",
        "test": "paired sign-flip permutation test over tasks on the per-task mean difference (bug - v1), "
                "20,000 permutations, two-sided; Holm correction across the two bugs; alpha = 0.05",
        "detected": "the primary metric rises significantly (after Holm)",
        "localised": "in at least half of the bug runs flagged false_success, a flagged claim's database diff "
                     "names the corrupted field (bug_addr2: a path ending in 'address2'; bug_dropitem: a path "
                     "in return_items / exchange_items / exchange_new_items or an items[i].item_id)",
        "false_alarms": "the same test on v1_rerun vs v1 on each bug's tasks; a significant result is a "
                        "false alarm",
        "reported_not_tested": "tau2 success rate per arm (context only)",
    }
    out = ROOT / "results" / "regression_plan_4b.json"
    out.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: (v["eligible_pool_size"], v["tasks"]) for k, v in plan["runs"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
