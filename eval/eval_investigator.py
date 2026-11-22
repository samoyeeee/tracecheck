"""Evaluate the investigator against AgentRx's human annotations (tau-bench retail).

    python -m eval.eval_investigator --split tune --arms C --note "what changed"
    python -m eval.eval_investigator --split test --arms A B C      # once, after tuning

The 29 annotated failures are split once (fixed seed) into a tuning set used
to iterate on the prompt and a test set that is only scored with the frozen
prompt. Every tuning run appends a line to results/iteration_log.md; the test
run writes results/eval_investigator.json.

Ground truth = AgentRx's root-cause failure (step number and category).
Metrics: exact step, step within +-1, category accuracy, abstain rate, and
accuracy by confidence band. For arm C, abstentions count as misses in the
"all cases" numbers and are excluded in the "answered cases" numbers.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import triage.investigator as inv  # noqa: E402
from triage.trajectory import load_agentrx  # noqa: E402

SPLIT_SEED = 7
TUNE_SIZE = 9
BANDS = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 1.01)]


def split(items):
    ids = sorted(t.traj_id for t, _ in items)
    tune = set(random.Random(SPLIT_SEED).sample(ids, TUNE_SIZE))
    return ([x for x in items if x[0].traj_id in tune], [x for x in items if x[0].traj_id not in tune])


def wilson(k: int, n: int) -> list:
    if not n:
        return [None, None]
    p, z = k / n, 1.96
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(centre - half, 3), round(centre + half, 3)]


def rate(k: int, n: int) -> dict:
    return {"n": k, "of": n, "rate": round(k / n, 4) if n else None, "ci95": wilson(k, n)}


def score(rows: list[dict]) -> dict:
    n = len(rows)
    answered = [r for r in rows if not r["abstain"]]
    ok = lambda r, key: r[key] and not r["abstain"]  # noqa: E731
    out = {
        "cases": n,
        "abstain": rate(n - len(answered), n),
        "all_cases": {k: rate(sum(ok(r, k) for r in rows), n)
                      for k in ("step_exact", "step_within_1", "category", "step_and_category", "failed_agent")},
        "answered_cases": {k: rate(sum(r[k] for r in answered), len(answered))
                           for k in ("step_exact", "step_within_1", "category", "step_and_category")},
        "step_hits_any_annotated_failure": rate(sum(r["step_any_failure"] and not r["abstain"] for r in rows), n),
        "by_confidence": {},
    }
    for lo, hi in BANDS:
        band = [r for r in answered if r["confidence"] is not None and lo <= r["confidence"] < hi]
        out["by_confidence"][f"{lo:.2f}-{min(hi, 1):.2f}"] = {
            "cases": len(band), "step_and_category": rate(sum(r["step_and_category"] for r in band), len(band))}
    return out


def run_arm(items, arm: str, model: str, policy_of, experiment: str, version: str = inv.PROMPT_VERSION) -> list[dict]:
    rows = []
    for t, gt in items:
        d = inv.investigate(t, arm, policy_of(t), model,
                            ROOT / "results" / "investigator" / f"agentrx_{experiment}_{arm}",
                            run_tag=f"investigator_agentrx_{arm}", version=version)
        step_ok = d.critical_step == gt["critical_step"]
        cat_ok = d.category == gt["category"]
        rows.append({
            "traj_id": t.traj_id, "arm": arm, "source": t.file,
            "truth": gt, "diagnosis": asdict(d),
            "abstain": d.abstain, "confidence": d.confidence,
            "step_exact": step_ok,
            "step_within_1": d.critical_step is not None and abs(d.critical_step - gt["critical_step"]) <= 1,
            "category": cat_ok, "step_and_category": step_ok and cat_ok,
            "failed_agent": d.failed_agent == gt["failed_agent"],
            "step_any_failure": d.critical_step in gt["all_failure_steps"],
        })
        print(f"  {arm} traj {t.traj_id}: step {d.critical_step} (truth {gt['critical_step']}) "
              f"{d.category} (truth {gt['category']}) conf={d.confidence} abstain={d.abstain}"
              f"{' ERR ' + d.error if d.error else ''}", flush=True)
    return rows


def badcases(rows: list[dict], n: int = 10) -> list[dict]:
    wrong = [r for r in rows if not r["step_and_category"]]
    return [{"traj_id": r["traj_id"], "source": r["source"],
             "truth": {k: r["truth"][k] for k in ("critical_step", "category", "failed_agent", "summary")},
             "predicted": {k: r["diagnosis"][k] for k in
                           ("critical_step", "category", "failed_agent", "confidence", "abstain",
                            "abstain_reason", "summary", "evidence")},
             "what_was_wrong": ", ".join(k for k in ("step_exact", "category") if not r[k])
                               + (" (abstained)" if r["abstain"] else "")}
            for r in wrong[:n]]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["tune", "test"], required=True)
    ap.add_argument("--arms", nargs="+", default=["A", "B", "C"])
    ap.add_argument("--prompt-version", default=inv.PROMPT_VERSION, choices=["v3", inv.WEB_PROMPT_VERSION],
                    help="v4 (web report prompt) writes results/eval_investigator_v4.json and leaves v3 files alone")
    ap.add_argument("--note", default="", help="what changed in this iteration (tuning log)")
    ap.add_argument("--repeat", type=int, default=0,
                    help="re-run the same prompt with a fresh cache (measures run-to-run noise)")
    args = ap.parse_args(argv)
    import yaml
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    model = yaml.safe_load((ROOT / "config.yaml").read_text())["models"]["investigator"]
    tune, test = split(load_agentrx())
    items = tune if args.split == "tune" else test
    policy_of = lambda t: t.messages[0]["content"] if t.messages and t.messages[0]["role"] == "system" else ""  # noqa: E731
    version = args.prompt_version
    experiment = f"{args.split}_{version}" + (f"_r{args.repeat}" if args.repeat else "")

    results = {}
    for arm in args.arms:
        rows = run_arm(items, arm, model, policy_of, experiment, version)
        results[arm] = {"metrics": score(rows), "rows": rows}
        m = results[arm]["metrics"]
        print(f"{arm}: step exact {m['all_cases']['step_exact']['rate']}, +-1 {m['all_cases']['step_within_1']['rate']}, "
              f"category {m['all_cases']['category']['rate']}, abstain {m['abstain']['rate']}")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if args.split == "tune":
        log = ROOT / "results" / "iteration_log.md"
        if not log.exists():
            log.write_text("# 调查 Agent 调参记录（只用调参集，测试集不参与）\n\n"
                           f"调参集：AgentRx tau-bench 29 条中按种子 {SPLIT_SEED} 抽出的 {TUNE_SIZE} 条 "
                           f"({', '.join(sorted((t.traj_id for t, _ in tune), key=int))})。"
                           "每行指标均为调参集上的结果。\n\n"
                           "| 时间 | prompt 版本 | 组 | 改动 | 步骤完全命中 | ±1 步 | 类别 | 步骤+类别 | 弃权率 |\n"
                           "|---|---|---|---|---|---|---|---|---|\n")
        with log.open("a") as f:
            for arm, res in results.items():
                m = res["metrics"]
                cell = lambda k: f"{m['all_cases'][k]['n']}/{m['cases']}"  # noqa: E731
                f.write(f"| {stamp} | {version}{f' (重复 {args.repeat})' if args.repeat else ''} | {arm} | {args.note} | {cell('step_exact')} | "
                        f"{cell('step_within_1')} | {cell('category')} | {cell('step_and_category')} | "
                        f"{m['abstain']['n']}/{m['cases']} |\n")
        (ROOT / "results" / "investigator" / f"{experiment}_rows.json").write_text(
            json.dumps({a: r["rows"] for a, r in results.items()}, indent=1, ensure_ascii=False))
        return 0

    out = {
        "what": "Investigator vs AgentRx human annotations, tau-bench retail, held-out test split",
        "ground_truth": "vendor/agentrx/data/ground_truth/tau_ground_truth.json (root-cause failure)",
        "model": model, "prompt_version": version, "abstain_rule": f"arm C: {inv.SAMPLES} samples at temperature {inv.SAMPLE_TEMPERATURE}; abstain unless {inv.MIN_AGREE} agree on step+category and a verbatim quote is found at that step",
        "split": {"seed": SPLIT_SEED, "tune_ids": sorted((t.traj_id for t, _ in tune), key=int),
                  "test_ids": sorted((t.traj_id for t, _ in test), key=int)},
        "arms": {"A": "trajectory only", "B": "A + outcome check + rule findings",
                 "C": "B + verbatim evidence requirement + abstain"},
        "run_at": stamp,
        "metrics": {a: r["metrics"] for a, r in results.items()},
        "badcases": {a: badcases(r["rows"]) for a, r in results.items()},
        "rows": {a: r["rows"] for a, r in results.items()},
    }
    if version != inv.PROMPT_VERSION:
        path = ROOT / "results" / f"eval_investigator_{version}.json"
        path.write_text(json.dumps(out, indent=1, ensure_ascii=False))
        print(f"written {path.relative_to(ROOT)}")
        return 0
    (ROOT / "results" / "eval_investigator.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    write_badcase_md(ROOT / "results" / "eval_investigator.json", ROOT / "results" / "investigator_badcases.md")
    print("written results/eval_investigator.json and results/investigator_badcases.md")
    return 0


if __name__ == "__main__" and "--badcase-md" not in sys.argv:
    raise SystemExit(main())


def write_badcase_md(path_in: Path, path_out: Path) -> None:
    """Readable sheet of the 10 wrong test cases per arm, for manual badcase analysis."""
    d = json.loads(path_in.read_text())
    gt = {str(g["trajectory_id"]): g for g in json.loads(
        (ROOT / "vendor/agentrx/data/ground_truth/tau_ground_truth.json").read_text())}
    lines = ["# 调查 Agent 判错案例（测试集，每组最多 10 条）", "",
             f"来源：`results/eval_investigator.json`（prompt {d['prompt_version']}，{d['run_at']}）。"
             "「真值」是 AgentRx 人工标注的根因；「判断」是调查 Agent 的输出。", "",
             "建议做法：通读后归纳 2-3 类判错原因（例如：选了后面的症状步骤而不是最早的错误；"
             "把用户造成的问题算到 agent 头上；类别边界不清），并决定下一轮改什么。", ""]
    for arm, cases in d["badcases"].items():
        lines += [f"## {arm} 组：{d['arms'][arm]}", "",
                  "| 轨迹 | 真值步骤 | 真值类别 | 判断步骤 | 判断类别 | 错在 |", "|---|---|---|---|---|---|"]
        for c in cases:
            t, p = c["truth"], c["predicted"]
            lines.append(f"| {c['traj_id']} | {t['critical_step']} | {t['category']} ({t['failed_agent']}) | "
                         f"{p['critical_step']} | {p['category']} ({p['failed_agent']}) | "
                         f"{c['what_was_wrong'].replace('step_exact', '步骤').replace('category', '类别').replace('(abstained)', '（已弃权）')} |")
        lines.append("")
    lines += ["## C 组判错案例详情", ""]
    for c in d["badcases"].get("C", []):
        g = gt.get(c["traj_id"], {})
        root = next((f for f in g.get("failures", []) if f["failure_id"] == g.get("root_cause", {}).get("failure_id")), {})
        p = c["predicted"]
        lines += [f"### 轨迹 {c['traj_id']}  （`{c['source']}`）",
                  f"- 标注者：第 {root.get('step_number')} 步 · {root.get('failure_category')} — {root.get('step_reason', '')}",
                  f"- 调查 Agent：第 {p['critical_step']} 步 · {p['category']} · 置信度 {p['confidence']}"
                  f"{' · 已弃权（' + p['abstain_reason'] + '）' if p['abstain'] else ''} — {p['summary']}",
                  ""]
    path_out.write_text("\n".join(lines))


if __name__ == "__main__" and "--badcase-md" in sys.argv:
    write_badcase_md(ROOT / "results" / "eval_investigator.json", ROOT / "results" / "investigator_badcases.md")
