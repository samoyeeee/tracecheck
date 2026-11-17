"""Write the phase-4 plan BEFORE any phase-4 run (pre-registration).

    python -m eval.regression_plan     # -> results/regression_plan.json

Fixes, in advance: which variants run on which tasks, which metrics are
compared, the statistical test, and - for each planted bug - which rule we
expect TraceCheck to point at. eval/eval_regression.py reads this file and
does not change any of it after seeing results.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SEED = 404
SUBSET = 20
WRITES = {"cancel_pending_order", "exchange_delivered_order_items", "modify_pending_order_address",
          "modify_pending_order_items", "modify_pending_order_payment", "modify_user_address",
          "return_delivered_order_items"}


def main() -> int:
    from agent.versions import SPECS

    tasks = json.loads((ROOT / "vendor/tau2-bench/data/tau2/domains/retail/tasks.json").read_text())
    acts = {str(t["id"]): {a["name"] for a in ((t.get("evaluation_criteria") or {}).get("actions") or [])}
            for t in tasks}
    all_ids = sorted(acts, key=int)
    pool = {
        "bug_auth": all_ids,                                    # every task requires authentication
        "bug_transfer": [t for t in all_ids if "transfer_to_human_agents" not in acts[t]],
        "bug_noconfirm": [t for t in all_ids if acts[t] & WRITES],
        "bug_param": [t for t in all_ids if "modify_pending_order_items" in acts[t]],
    }
    signature = {
        "bug_auth": "policy_authenticate_first",
        "bug_transfer": "transfer_to_human",
        "bug_noconfirm": "policy_confirm_before_write",
        "bug_param": "tool_error",
    }
    rng = random.Random(SEED)
    plan = {
        "written_before_runs": True,
        "seed": SEED,
        "k": 4,
        "runs": {
            "v1_rerun": {"agent": "v1", "tasks": "all 114", "purpose": "noise: v1 vs v1"},
            "v2": {"agent": "v2", "tasks": "all 114", "purpose": "fix vs v1"},
            **{name: {"agent": name, "tasks": sorted(rng.sample(pool[name], SUBSET), key=int),
                      "related_pool_size": len(pool[name]),
                      "description": SPECS[name].description,
                      "expected_signature_rule": signature[name]}
               for name in pool},
        },
        "metrics": "per run: success (tau2 reward == 1) and, for every layer-1/2 rule, whether it fired; "
                   "aggregated per task as the mean over its k trials",
        "test": "paired sign-flip permutation test over tasks on the per-task mean difference "
                "(variant - v1), 20,000 permutations, two-sided; Holm correction across the metrics of "
                "one comparison; alpha = 0.05",
        "detected": "a bug is detected if success drops or any rule rises significantly (after Holm)",
        "localised": "the expected signature rule is among the significant worsened rule metrics",
        "false_alarms": "the same procedure applied to v1_rerun vs v1 on each bug's task subset and on all "
                        "114 tasks; every significant metric there is a false alarm",
        "per_task_noise": "per-task |success-rate difference| between v1_rerun and v1; a v2 task change counts "
                          "as fixed/worse only if it exceeds the 95th percentile of that noise",
    }
    out = ROOT / "results" / "regression_plan.json"
    out.write_text(json.dumps(plan, indent=1, ensure_ascii=False))
    print(json.dumps({k: v.get("tasks") if isinstance(v, dict) else v for k, v in plan["runs"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
