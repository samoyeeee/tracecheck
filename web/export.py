"""Export the numbers the web UI shows from results/ into web/data/*.json.

    python -m web.export

The UI only reads these files; it never calls a model. Every number carries
the repo path of the file it was read from ("src"), so the page can link it.
Nothing here computes a new metric except plain sums of results/cost_log.csv
and per-type success rates from the triage files (both listed as sources).
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "web" / "app" / "public" / "legacy" / "data"     # earlier pages 2-4 (until redone)
REPORTS = ROOT / "web" / "app" / "public" / "data" / "reports"  # page 1: pre-computed diagnosis reports

# Runs shown as pre-computed reports in the online demo. The first is the default page.
DEMO_RUNS = [
    ("results/runs/bug_dropitem/task_2__trial_1.json", "埋 bug（漏掉最后一件）· 任务 2 · 第 1 次 · 假成功"),
]


def load(path: str):
    return json.loads((ROOT / path).read_text())


def num(value, src: str, note: str = "") -> dict:
    """A number shown in the UI, with the file it came from."""
    return {"v": value, "src": src, **({"note": note} if note else {})}


# --- overview ------------------------------------------------------------------

def cost_summary() -> dict:
    by_model: dict[str, Counter] = defaultdict(Counter)
    billed = 0.0
    with open(ROOT / "results" / "cost_log.csv") as f:
        for r in csv.DictReader(f):
            c = by_model[r["model"]]
            c["calls"] += 1
            c["ok"] += r["status"] == "ok"
            c["tokens"] += int(r["total_tokens"] or 0)
            billed += float(r["billed_cost_usd"] or 0)
    return {"billed_usd": round(billed, 4),
            "calls": sum(c["calls"] for c in by_model.values()),
            "tokens": sum(c["tokens"] for c in by_model.values()),
            "by_model": {m: dict(c) for m, c in sorted(by_model.items(), key=lambda x: -x[1]["calls"])}}


def overview() -> dict:
    b, v = load("results/baseline_v1.json"), load("results/eval_verify.json")
    d, e = load("results/diagnoses/v1.json"), load("results/eval_investigator.json")
    B, V, D, E, C = ("results/baseline_v1.json", "results/eval_verify.json", "results/diagnoses/v1.json",
                     "results/eval_investigator.json", "results/cost_log.csv")
    diags = list(d["diagnoses"].values())
    answered = [x for x in diags if not x["abstain"]]
    fr, fs = v["failure_recall"], v["false_success"]
    prec = fs["precision_human_review"]
    return {
        "models": b["models"],
        "baseline": {
            "runs": num(b["simulations_finished"], B), "tasks": num(b["tasks_expected"], B), "k": num(b["k"], B),
            "pass1": num(b["pass^1"], B), "pass4": num(b["pass^4"], B),
            "pass_k": num({k: b[f"pass^{k}"] for k in (1, 2, 3, 4)}, B),
            "successful_runs": num(b["successful_runs"], B), "failed_runs": num(b["failed_runs"], B),
            "failed_reasons": num(b["failed_run_reasons"], B),
        },
        "verify": {
            "any_signal": num(fr["any_signal"], V), "step_level": num(fr["step_level_explanation"], V),
            "false_success": num(fs["runs"], V), "false_success_types": num(fs["runs_by_type"], V),
            "precision": num(prec.get("rate") if prec.get("status") != "pending" else None, V,
                             prec.get("note", "")),
            "replay_sanity": num(v["replay_sanity_check"], V),
        },
        "categories": {
            "candidates": num(d["candidates"], D), "diagnosed": num(d["diagnosed"], D),
            "answered": num(len(answered), D), "abstained": num(sum(x["abstain"] for x in diags), D),
            "errors": num(sum(bool(x.get("error")) for x in diags), D),
            "answered_by_category": num(dict(Counter(x["category"] for x in answered).most_common()), D),
            "all_by_category": num(dict(Counter(x["category"] or "(无)" for x in diags).most_common()), D),
            "investigator_accuracy": num({"category_answered": e["metrics"]["C"]["answered_cases"]["category"],
                                          "abstain": e["metrics"]["C"]["abstain"],
                                          "step_within_1_answered":
                                              e["metrics"]["C"]["answered_cases"]["step_within_1"]}, E,
                                         "AgentRx 测试集 20 条，C 组"),
            "stability": num(load("results/diagnoses/stability_v1.json"), "results/diagnoses/stability_v1.json"),
        },
        "cost": num(cost_summary(), C),
    }


# --- audit cards -----------------------------------------------------------------

def audit() -> dict:
    """Pre-computed demo: the v1 failures the investigator diagnosed (same card as live analysis)."""
    from triage.pipeline import DIAGNOSIS_FIELDS, case_from_report
    from triage.trajectory import from_tau2

    d = load("results/diagnoses/v1.json")
    triage = {r["file"]: r for r in load("results/triage/v1.json")}
    cases = []
    for key, x in sorted(d["diagnoses"].items(), key=lambda kv: int(kv[0].split("_")[1])):
        case = case_from_report(triage[x["file"]], load(x["file"]), from_tau2(ROOT / x["file"]).user_goal)
        case["id"] = key
        case["diagnosis"] = {k: x.get(k) for k in DIAGNOSIS_FIELDS}
        cases.append(case)
    return {"src_diagnoses": "results/diagnoses/v1.json", "src_triage": "results/triage/v1.json",
            "selection": d["selection"], "cases": cases}


# --- regression ------------------------------------------------------------------

def success_by_task(tag: str) -> dict[str, float]:
    by = defaultdict(list)
    for r in load(f"results/triage/{tag}.json"):
        by[r["task_id"]].append(1.0 if r["tau2_success"] else 0.0)
    return {t: sum(v) / len(v) for t, v in by.items()}


def regression() -> dict:
    from eval.eval_regression import task_types

    R, R4b = "results/eval_regression.json", "results/eval_regression_4b.json"
    r, r4 = load(R), load(R4b)
    v2 = r["v2_vs_v1"]
    rerun = success_by_task("v1_rerun")
    types = task_types()
    by_type = {}
    for name, row in v2["by_task_type"]["by_type"].items():
        ids = [t for t, ts in types.items() if name in ts]
        by_type[name] = {**row, "v1_rerun_rate": round(sum(rerun[t] for t in ids) / len(ids), 4)}
    bugs = []
    for name, b in r["bugs"].items():
        bugs.append({"name": name, "round": "4", "description": b["description"], "detected": b["detected"],
                     "localised": b["localised"], "metric": b["expected_signature_rule"],
                     "base_rate": b["signature_metric"]["base_rate"], "other_rate": b["signature_metric"]["other_rate"],
                     "p": b["signature_metric"]["p"], "p_holm": b["signature_metric"]["p_holm"],
                     "success": [b["success"]["base_rate"], b["success"]["other_rate"]], "src": R})
    for name, b in r4["bugs"].items():
        bugs.append({"name": name, "round": "4b", "description": b["description"], "detected": b["detected"],
                     "localised": b["localised"], "metric": "false_success",
                     "base_rate": b["primary"]["base_rate"], "other_rate": b["primary"]["other_rate"],
                     "p": b["primary"]["p"], "p_holm": b["primary"]["p_holm"],
                     "success": [b["context_tau2_success"]["base_rate"], b["context_tau2_success"]["other_rate"]],
                     "localisation": [b["localisation_bug"]["share"], b["localisation_v1_same_tasks"]["share"]],
                     "src": R4b})
    return {
        "release": num(v2["release"], R),
        "success": num({"v1": v2["comparison"]["success"]["base_rate"], "v2": v2["comparison"]["success"]["other_rate"],
                        "p": v2["comparison"]["success"]["p"], "p_holm": v2["comparison"]["success"]["p_holm"]}, R),
        "pass_hat": num(r["pass_hat"], R),
        "noise": num({k: v2["by_task_type"][k] for k in ("per_task_noise_threshold", "noise_note",
                                                         "tasks_beyond_threshold_in_v1_vs_v1")}, R),
        "false_alarms": num({"phase4": r["false_alarm_total"], "phase4b": r4["summary"]["false_alarms_v1_vs_v1"]},
                            R + " · " + R4b),
        "by_type": num(by_type, R, "v1_rerun 一列按 results/triage/v1_rerun.json 计算"),
        "type_note": v2["by_task_type"].get("type_note", ""),
        "bugs": bugs,
        "summary": num({"phase4": r["summary"], "phase4b": r4["summary"]}, R + " · " + R4b),
        "mechanism_src": "results/bug_mechanism_check.json",
        "plans": ["results/regression_plan.json", "results/regression_plan_4b.json"],
    }


def report_id(file: str) -> str:
    p = Path(file)
    return f"{p.parent.name}__{p.stem}"


def reports() -> list[dict]:
    """Page-1 reports for DEMO_RUNS (investigator v4 + translation; cached, so re-export is free)."""
    from datetime import datetime, timezone

    from triage.pipeline import build_report

    REPORTS.mkdir(parents=True, exist_ok=True)
    index = []
    for file, label in DEMO_RUNS:
        r = build_report(ROOT / file, ai=True, zh=True)
        r["id"] = report_id(file)
        r["footer"]["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        (REPORTS / f"{r['id']}.json").write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
        index.append({"id": r["id"], "file": file, "label": label})
        print(f"web/app/public/data/reports/{r['id']}.json")
    (REPORTS / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    return index


def main() -> int:
    reports()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (("overview", overview), ("audit", audit), ("regression", regression)):
        data = fn()
        (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        print(f"web/app/public/legacy/data/{name}.json  {(OUT / f'{name}.json').stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
