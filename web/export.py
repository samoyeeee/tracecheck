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

REPORTS = ROOT / "web" / "app" / "public" / "data" / "reports"  # page 1: pre-computed diagnosis reports

# Runs shown as pre-computed reports in the online demo. The first is the default page.
DEMO_RUNS = [
    ("results/runs/bug_dropitem/task_2__trial_1.json", "埋 bug：漏掉最后一件"),
    ("results/runs/v1/task_33__trial_1.json", "v1"),
    ("results/runs/v1/task_100__trial_0.json", "v1"),
    ("results/runs/v1/task_2__trial_0.json", "v1"),
    ("results/runs/bug_addr2/task_101__trial_0.json", "埋 bug：清空地址第二行"),
    ("results/runs/v1/task_0__trial_2.json", "v1"),
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
            "arms": num({arm: {"all": e["metrics"][arm]["all_cases"], "answered": e["metrics"][arm].get("answered_cases"),
                               "abstain": e["metrics"][arm]["abstain"], "cases": e["metrics"][arm]["cases"]}
                         for arm in ("A", "B", "C")}, E),
            "v4": num({"all": load("results/eval_investigator_v4.json")["metrics"]["C"]["all_cases"],
                       "answered": load("results/eval_investigator_v4.json")["metrics"]["C"]["answered_cases"],
                       "abstain": load("results/eval_investigator_v4.json")["metrics"]["C"]["abstain"]},
                      "results/eval_investigator_v4.json"),
        },
        "cost": num(cost_summary(), C),
        "fs_precision": num(load("results/false_success_precision.json"), "results/false_success_precision.json"),
        "bug_effect": num(load("results/bug_effect.json")["bugs"], "results/bug_effect.json"),
        "confusion": num({k: v["reasons"] for k, v in load("results/category_confusion.json")["arms"].items()},
                         "results/category_confusion.json"),
    }


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
        "by_type_bands": num(load("results/regression_by_type.json"), "results/regression_by_type.json"),
    }


def report_id(file: str) -> str:
    p = Path(file)
    return f"{p.parent.name}__{p.stem}"


def library_runs() -> list[tuple[str, str]]:
    """Case library: the v1 failures the investigator diagnosed (one unexplained failed trial per task)."""
    d = load("results/diagnoses/v1.json")
    return [(x["file"], "v1") for x in d["diagnoses"].values()]


def reports() -> list[dict]:
    """Page-1 reports for DEMO_RUNS (the review queue) and the case library.

    Investigator v4 + translation; both cached, so a re-export costs no model call.
    If the daily investigator quota runs out, the remaining reports are written
    without the AI layer (shown as "未运行") and a later re-export fills them in.
    """
    from datetime import datetime, timezone

    from runner.gateway import DailyQuotaExhausted
    from triage.pipeline import build_report

    REPORTS.mkdir(parents=True, exist_ok=True)
    queue = {f for f, _ in DEMO_RUNS}
    runs = list(dict.fromkeys(DEMO_RUNS + library_runs()))
    seen, index, ai_ok = set(), [], True
    for n, (file, label) in enumerate(runs, 1):
        if file in seen:
            continue
        seen.add(file)
        try:
            r = build_report(ROOT / file, ai=ai_ok, zh=True)
        except DailyQuotaExhausted:
            ai_ok = False
            r = build_report(ROOT / file, ai=False, zh=True)
        r["id"] = report_id(file)
        r["footer"]["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        (REPORTS / f"{r['id']}.json").write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
        v, a = r["verdict"], r["ai"]
        index.append({
            "id": r["id"], "file": file, "version": label, "task_id": r["task_id"], "trial": r["trial"],
            "queue": file in queue, "success": r["tau2"]["reward"] == 1, "false_success": r["tau2"]["false_success"],
            "kind": v["kind"], "short": v["short"], "tone": "warn" if v["ai_unsure"] else v["queue_tone"],
            "queue_kind": "AI 拿不准" if v["ai_unsure"] else v["kind"],
            "ai": None if not a else {"abstain": a["abstain"], "confidence": a["confidence"],
                                      "critical_step": a["critical_step"], "category_zh": a["category_zh"]},
            "label": f"{label} · 任务 {r['task_id']} · 第 {r['trial']} 次 · {v['kind']}",
        })
        print(f"[{n}/{len(runs)}] {r['id']}  {v['kind']}  ai={'yes' if a else 'no'}", flush=True)
    (REPORTS / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    return index


def rcases_data() -> None:
    """Pre-computed regression cases and their replays, for the static site (read-only)."""
    from triage.pipeline import build_report
    from triage.regression_case import CASES, summarise
    out = ROOT / "web" / "app" / "public" / "data" / "rcases"
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for f in sorted(CASES.glob("rc_*.json")):
        case = json.loads(f.read_text())
        (out / f"{case['id']}.json").write_text(json.dumps({"case": case, "summary": summarise(case)},
                                                           ensure_ascii=False, separators=(",", ":")))
        index.append({"id": case["id"], "source_file": case["source_file"], "task_id": case["task_id"]})
        for r in case["replays"]:
            if r.get("file"):
                rid = report_id(r["file"])
                if not (REPORTS / f"{rid}.json").exists():
                    rep = build_report(ROOT / r["file"])
                    rep["id"] = rid
                    (REPORTS / f"{rid}.json").write_text(json.dumps(rep, ensure_ascii=False, separators=(",", ":")))
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    print(f"web/app/public/data/rcases/ ({len(index)} cases)")


def fs_review_data() -> dict:
    """Read-only copy of the false-success check for the static site."""
    from eval.fs_review import apply, web_data
    return {"cases": web_data(), "precision": apply()}


def review_reports() -> None:
    """Page-1 reports (rules + database check only, no model call) for the cases under human check."""
    from triage.pipeline import build_report
    from eval.fs_review import REVIEW
    have = {p.stem for p in REPORTS.glob("*.json")}
    for it in json.loads(REVIEW.read_text()):
        rid = report_id(it["file"])
        if rid in have:
            continue
        r = build_report(ROOT / it["file"])
        r["id"] = rid
        (REPORTS / f"{rid}.json").write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
        print(f"web/app/public/data/reports/{rid}.json (review case, no AI)")


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-reports", action="store_true", help="only re-export overview / regression data")
    if not ap.parse_args(argv).skip_reports:
        reports()
    NEW = ROOT / "web" / "app" / "public" / "data"
    review_reports()
    rcases_data()
    (NEW / "fs_review.json").write_text(json.dumps(fs_review_data(), ensure_ascii=False, separators=(",", ":")))
    print("web/app/public/data/fs_review.json")
    for name, fn in (("overview", overview), ("regression", regression)):
        data = fn()
        (NEW / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        print(f"web/app/public/data/{name}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
