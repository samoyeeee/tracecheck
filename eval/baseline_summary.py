"""Baseline summary for one run: pass^1 .. pass^k, failures, usage.

    python -m eval.baseline_summary --tag v1

Writes results/baseline_<tag>.json. Every number is computed from the files in
results/runs/<tag>/ and results/cost_log.csv, nothing is hand-entered.

pass^k follows tau-bench: for a task with n trials and c successes, the chance
that k trials drawn without replacement all succeed is C(c,k)/C(n,k); pass^k is
the mean over tasks. pass^1 is therefore the plain average success rate, and
with n == k, pass^k is the share of tasks that succeeded in every trial.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INFRA = "infrastructure_error"


def is_success(reward) -> bool:
    return reward is not None and abs(reward - 1.0) < 1e-6


def pass_hat_k(successes: int, trials: int, k: int) -> float:
    return comb(successes, k) / comb(trials, k)


def load_runs(run_dir: Path) -> list[dict]:
    """Finished simulations only (infra errors are pending, not results)."""
    runs = []
    for path in sorted(run_dir.glob("task_*__trial_*.json")):
        sim = json.loads(path.read_text())
        if sim.get("termination_reason") == INFRA:
            continue
        reward_info = sim.get("reward_info") or {}
        db = reward_info.get("db_check") or {}
        nl = reward_info.get("nl_assertions") or []
        runs.append({
            "file": str(path.relative_to(ROOT)),
            "task_id": str(sim["task_id"]),
            "trial": sim.get("trial"),
            "reward": reward_info.get("reward"),
            "success": is_success(reward_info.get("reward")),
            "db_match": db.get("db_match"),
            "nl_all_met": all(c.get("met") for c in nl) if nl else None,
            "termination_reason": sim.get("termination_reason"),
            "num_messages": len(sim.get("messages") or []),
        })
    return runs


def summarize(runs: list[dict], k: int, expected_tasks: int | None = None) -> dict:
    by_task: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        by_task[run["task_id"]].append(run)
    complete = {t: rs for t, rs in by_task.items() if len(rs) >= k}

    pass_hat = {}
    for j in range(1, k + 1):
        vals = [pass_hat_k(sum(r["success"] for r in rs), len(rs), j) for rs in complete.values()]
        pass_hat[f"pass^{j}"] = round(sum(vals) / len(vals), 4) if vals else None

    failures = [r for r in runs if not r["success"]]
    # Why a failed run failed, from tau2's own reward breakdown (observed facts only).
    reasons = Counter()
    for r in failures:
        if r["termination_reason"] not in ("user_stop", "agent_stop"):
            reasons[f"terminated: {r['termination_reason']}"] += 1
        elif r["db_match"] is False:
            reasons["db_mismatch"] += 1
        elif r["nl_all_met"] is False:
            reasons["db_ok_but_nl_assertion_failed"] += 1
        else:
            reasons["other"] += 1

    successes_per_task = Counter(sum(r["success"] for r in rs) for rs in complete.values())
    return {
        "k": k,
        "tasks_expected": expected_tasks,
        "tasks_with_k_trials": len(complete),
        "tasks_with_any_trial": len(by_task),
        "simulations_finished": len(runs),
        "simulations_expected": expected_tasks * k if expected_tasks else None,
        "complete": bool(expected_tasks) and len(complete) == expected_tasks,
        **pass_hat,
        "successful_runs": len(runs) - len(failures),
        "failed_runs": len(failures),
        "failed_run_reasons": dict(reasons.most_common()),
        "tasks_by_successes_out_of_k": {str(n): successes_per_task.get(n, 0) for n in range(k + 1)},
    }


def usage(tag: str, cost_log: Path) -> dict:
    """Requests and tokens logged for this run tag, split by role."""
    by_role: dict[str, dict] = defaultdict(lambda: Counter())
    models = defaultdict(set)
    if cost_log.exists():
        with cost_log.open() as f:
            for row in csv.DictReader(f):
                if row["run_tag"] != tag:
                    continue
                role = row["role"] or "unknown"
                c = by_role[role]
                c["requests"] += int(row["attempts"] or 1) if row["status"] == "ok" else 1
                c["prompt_tokens"] += int(row["prompt_tokens"] or 0)
                c["completion_tokens"] += int(row["completion_tokens"] or 0)
                models[role].add(row["model"])
    out = {role: {**dict(c), "models": sorted(models[role])} for role, c in by_role.items()}
    return {
        "by_role": out,
        "billed_cost_usd": 0.0,
        "billed_cost_note": "All calls used free-tier models; nothing was billed.",
        "list_price_cost_usd": None,
        "list_price_note": "Not measured: no verified per-token prices are configured.",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    args = ap.parse_args(argv)
    run_dir = ROOT / "results" / "runs" / args.tag
    meta = json.loads((run_dir / "_run_meta.json").read_text())
    runs = load_runs(run_dir)
    summary = {
        "tag": args.tag,
        "agent": meta["agent"],
        "models": meta["models"],
        "source_files": {"runs": f"results/runs/{args.tag}/", "cost_log": "results/cost_log.csv"},
        "judge_note": "NL assertions are judged by a substitute model, not tau2's default judge; "
                      "scores are not comparable with the official leaderboard.",
        **summarize(runs, meta["k"], len(meta["task_ids"])),
        "usage": usage(args.tag, ROOT / "results" / "cost_log.csv"),
        "per_run": runs,
    }
    out = ROOT / "results" / f"baseline_{args.tag}.json"
    out.write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k != "per_run"}, indent=1, ensure_ascii=False))
    print(f"\nWritten to {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
