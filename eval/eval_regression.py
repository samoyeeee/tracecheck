"""Phase-4 regression analysis, following results/regression_plan.json exactly.

    python -m eval.eval_regression          # triages missing batches, then analyses

For every comparison (variant vs v1) and every metric - success, and each
layer-1/2 rule "fired in this run" - the per-task mean over k trials is
compared with a paired sign-flip permutation test over tasks, Holm-corrected
across the metrics of that comparison. The same procedure on v1_rerun vs v1
gives the false-alarm count. Writes results/eval_regression.json.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from collections import defaultdict
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PERMUTATIONS = 20_000
ALPHA = 0.05
WRITES = {"cancel_pending_order": "cancel", "return_delivered_order_items": "return",
          "exchange_delivered_order_items": "exchange", "modify_pending_order_items": "modify_items",
          "modify_pending_order_address": "modify_order_address", "modify_user_address": "modify_user_address",
          "modify_pending_order_payment": "modify_payment"}


# --- loading -------------------------------------------------------------------

def triage(tag: str) -> list[dict]:
    path = ROOT / "results" / "triage" / f"{tag}.json"
    run_dir = ROOT / "results" / "runs" / tag
    n_runs = len(list(run_dir.glob("task_*__trial_*.json")))
    if not path.exists() or len(json.loads(path.read_text())) != n_runs:
        subprocess.run([sys.executable, "-m", "eval.eval_verify", "--tag", tag, "--triage-only"],
                       cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return json.loads(path.read_text())


def per_task(reports: list[dict], tasks: list[str] | None = None) -> dict[str, dict[str, list[float]]]:
    """{task_id: {metric: [value per trial]}}; metric 'success' plus one per rule id."""
    out: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    rules = {f["rule_id"] for r in reports for f in r["findings"]}
    for r in reports:
        if tasks is not None and r["task_id"] not in tasks:
            continue
        fired = {f["rule_id"] for f in r["findings"]}
        out[r["task_id"]]["success"].append(1.0 if r["tau2_success"] else 0.0)
        for rule in rules:
            out[r["task_id"]][rule].append(1.0 if rule in fired else 0.0)
    return out


def pass_hat(reports: list[dict], k: int = 4) -> dict:
    by = defaultdict(list)
    for r in reports:
        by[r["task_id"]].append(r["tau2_success"])
    full = [v for v in by.values() if len(v) >= k]
    res = {}
    for j in range(1, k + 1):
        vals = [comb(sum(v), j) / comb(len(v), j) for v in full]
        res[f"pass^{j}"] = round(sum(vals) / len(vals), 4) if vals else None
    return {"tasks": len(by), "tasks_with_k_trials": len(full), "runs": len(reports), **res}


# --- statistics ----------------------------------------------------------------

def sign_flip_p(diffs: list[float], rng: random.Random) -> float:
    """Two-sided paired permutation test of mean(diffs) == 0."""
    if not diffs or all(d == 0 for d in diffs):
        return 1.0
    obs = abs(sum(diffs) / len(diffs))
    hits = 0
    for _ in range(PERMUTATIONS):
        s = sum(d if rng.random() < 0.5 else -d for d in diffs) / len(diffs)
        hits += abs(s) >= obs - 1e-12
    return (hits + 1) / (PERMUTATIONS + 1)


def holm(pvals: dict[str, float]) -> dict[str, float]:
    order = sorted(pvals, key=pvals.get)
    m, adj, running = len(order), {}, 0.0
    for i, key in enumerate(order):
        running = max(running, min(1.0, (m - i) * pvals[key]))
        adj[key] = running
    return adj


def compare(base: list[dict], other: list[dict], tasks: list[str] | None, seed: int) -> dict:
    """other vs base, per metric. 'worse' = success down or a rule up."""
    a, b = per_task(base, tasks), per_task(other, tasks)
    common = sorted(set(a) & set(b), key=int)
    metrics = sorted({m for t in common for m in a[t]} | {m for t in common for m in b[t]})
    rng = random.Random(seed)
    rows, pvals = {}, {}
    for m in metrics:
        diffs = []
        for t in common:
            va, vb = a[t].get(m) or [0.0], b[t].get(m) or [0.0]
            diffs.append(sum(vb) / len(vb) - sum(va) / len(va))
        mean_a = sum(sum(a[t].get(m) or [0]) / max(1, len(a[t].get(m) or [0])) for t in common) / len(common)
        mean_b = sum(sum(b[t].get(m) or [0]) / max(1, len(b[t].get(m) or [0])) for t in common) / len(common)
        p = sign_flip_p(diffs, rng)
        pvals[m] = p
        rows[m] = {"base_rate": round(mean_a, 4), "other_rate": round(mean_b, 4),
                   "diff": round(mean_b - mean_a, 4), "p": round(p, 4)}
    adj = holm(pvals)
    for m, row in rows.items():
        row["p_holm"] = round(adj[m], 4)
        row["significant"] = adj[m] < ALPHA
        worse = row["diff"] < 0 if m == "success" else row["diff"] > 0
        row["direction"] = "worse" if worse else ("better" if row["diff"] else "same")
    sig = {m: r for m, r in rows.items() if r["significant"]}
    return {"tasks": len(common), "metrics_tested": len(rows),
            "significant": {m: r for m, r in sorted(sig.items(), key=lambda kv: kv[1]["p_holm"])},
            "success": rows.get("success"), "all_metrics": rows}


# --- per-task change for v2 -----------------------------------------------------

def task_types() -> dict[str, list[str]]:
    tasks = json.loads((ROOT / "vendor/tau2-bench/data/tau2/domains/retail/tasks.json").read_text())
    out = {}
    for t in tasks:
        acts = {WRITES[a["name"]] for a in ((t.get("evaluation_criteria") or {}).get("actions") or [])
                if a["name"] in WRITES}
        out[str(t["id"])] = sorted(acts) or ["no_write"]
    return out


def success_rates(reports: list[dict]) -> dict[str, float]:
    by = defaultdict(list)
    for r in reports:
        by[r["task_id"]].append(1.0 if r["tau2_success"] else 0.0)
    return {t: sum(v) / len(v) for t, v in by.items()}


def v2_by_type(v1: list[dict], rerun: list[dict], v2: list[dict]) -> dict:
    s1, s1b, s2 = success_rates(v1), success_rates(rerun), success_rates(v2)
    noise = sorted(abs(s1b[t] - s1[t]) for t in s1 if t in s1b)
    threshold = noise[min(len(noise) - 1, int(0.95 * len(noise)))] if noise else None
    types = task_types()
    table = defaultdict(lambda: {"tasks": 0, "fixed": [], "worse": [], "unchanged": 0,
                                 "v1_rate": 0.0, "v2_rate": 0.0})
    for t in sorted(set(s1) & set(s2), key=int):
        delta = s2[t] - s1[t]
        for ty in types.get(t, ["unknown"]):
            row = table[ty]
            row["tasks"] += 1
            row["v1_rate"] += s1[t]
            row["v2_rate"] += s2[t]
            if threshold is not None and delta > threshold:
                row["fixed"].append(t)
            elif threshold is not None and delta < -threshold:
                row["worse"].append(t)
            else:
                row["unchanged"] += 1
    for row in table.values():
        row["v1_rate"] = round(row["v1_rate"] / row["tasks"], 4)
        row["v2_rate"] = round(row["v2_rate"] / row["tasks"], 4)
    noise_counts = {"tasks_beyond_threshold_in_v1_vs_v1": sum(n > threshold for n in noise) if noise else None}
    return {"per_task_noise_threshold": threshold,
            "noise_note": "95th percentile of |success-rate change| per task between v1_rerun and v1 (k=4 each)",
            **noise_counts, "by_type": dict(sorted(table.items())),
            "type_note": "a task with several kinds of write appears under each of them"}


def recommendation(v2_vs_v1: dict, by_type: dict, noise_vs: dict) -> dict:
    succ = v2_vs_v1["success"]
    worse_rules = [m for m, r in v2_vs_v1["significant"].items() if r["direction"] == "worse"]
    n_fixed = len({t for r in by_type["by_type"].values() for t in r["fixed"]})
    n_worse = len({t for r in by_type["by_type"].values() for t in r["worse"]})
    facts = [f"overall success {succ['base_rate']} -> {succ['other_rate']} (p_holm={succ['p_holm']})",
             f"tasks beyond per-task noise: {n_fixed} better, {n_worse} worse "
             f"(v1 vs v1 itself: {by_type['tasks_beyond_threshold_in_v1_vs_v1']} beyond threshold)",
             f"significantly worse rule metrics: {worse_rules or 'none'}"]
    if succ["significant"] and succ["direction"] == "better" and not worse_rules:
        verdict = "可以上线"
    elif succ["significant"] and succ["direction"] == "worse":
        verdict = "不建议上线"
    elif worse_rules:
        verdict = "不建议上线" if succ["direction"] != "better" else "需要再查"
    else:
        verdict = "需要再查"
    return {"verdict": verdict, "facts": facts,
            "rule": "可以上线 = success significantly better and no rule significantly worse; "
                    "不建议上线 = success significantly worse, or rules worse without a success gain; "
                    "otherwise 需要再查"}


def main() -> int:
    plan = json.loads((ROOT / "results" / "regression_plan.json").read_text())
    seed = plan["seed"]
    v1 = triage("v1")
    have = {tag for tag in plan["runs"] if (ROOT / "results" / "runs" / tag).exists()}
    rerun = triage("v1_rerun") if "v1_rerun" in have else None
    out = {"plan": "results/regression_plan.json", "alpha": ALPHA, "permutations": PERMUTATIONS,
           "pass_hat": {"v1": pass_hat(v1)}, "bugs": {}, "false_alarms": {}, "complete": True}

    for name, run in plan["runs"].items():
        if not name.startswith("bug_"):
            continue
        if name not in have:
            out["complete"] = False
            continue
        rep = triage(name)
        out["pass_hat"][name] = pass_hat(rep)
        cmp_ = compare(v1, rep, run["tasks"], seed)
        worse = {m: r for m, r in cmp_["significant"].items() if r["direction"] == "worse"}
        sig = run["expected_signature_rule"]
        out["bugs"][name] = {
            "description": run["description"], "tasks": run["tasks"],
            "expected_signature_rule": sig,
            "detected": bool(worse), "localised": sig in worse,
            "worse_metrics": worse,
            "signature_metric": cmp_["all_metrics"].get(sig),
            "success": cmp_["success"],
            "runs": len(rep), "comparison": cmp_,
        }
        if rerun is not None:
            noise = compare(v1, rerun, run["tasks"], seed + 1)
            out["false_alarms"][f"v1_rerun vs v1 on {name} tasks"] = {
                "significant_metrics": list(noise["significant"]), "metrics_tested": noise["metrics_tested"]}

    if rerun is not None:
        out["pass_hat"]["v1_rerun"] = pass_hat(rerun)
        allnoise = compare(v1, rerun, None, seed + 2)
        out["false_alarms"]["v1_rerun vs v1 on all tasks"] = {
            "significant_metrics": list(allnoise["significant"]), "metrics_tested": allnoise["metrics_tested"],
            "success": allnoise["success"]}
        out["false_alarm_total"] = sum(len(v["significant_metrics"]) for v in out["false_alarms"].values())
    else:
        out["complete"] = False

    if "v2" in have and rerun is not None:
        v2 = triage("v2")
        out["pass_hat"]["v2"] = pass_hat(v2)
        v2cmp = compare(v1, v2, None, seed + 3)
        types = v2_by_type(v1, rerun, v2)
        out["v2_vs_v1"] = {"comparison": v2cmp, "by_task_type": types,
                           "release": recommendation(v2cmp, types, out["false_alarms"])}
    else:
        out["complete"] = False

    out["summary"] = {
        "bugs_detected": f"{sum(b['detected'] for b in out['bugs'].values())}/{len(out['bugs'])}",
        "bugs_localised": f"{sum(b['localised'] for b in out['bugs'].values())}/{len(out['bugs'])}",
        "false_alarms_v1_vs_v1": out.get("false_alarm_total"),
        "v2_release": (out.get("v2_vs_v1") or {}).get("release", {}).get("verdict"),
    }
    (ROOT / "results" / "eval_regression.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps({"summary": out["summary"], "pass_hat": out["pass_hat"], "complete": out["complete"]},
                     indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
