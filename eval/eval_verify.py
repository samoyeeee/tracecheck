"""Run layers 1 + 2 over a batch and evaluate them against tau2's verdicts.

    python -m eval.eval_verify --tag v1                 # triage + metrics + review sheet
    python -m eval.eval_verify --tag v1 --apply-review  # add precision from your labels

Outputs
  results/triage/<tag>.json           one TraceReport per simulation
  results/eval_verify.json            metrics (every number computed from the above)
  results/false_success_review.md     20 sampled false-success cases to check by hand
  results/false_success_review.json   the same cases with an empty ``human_label``
                                      field: fill in "correct" / "incorrect" / "unsure"
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from triage.rules import run_rules  # noqa: E402
from triage.schema import FALSE_SUCCESS_STATUSES, Evidence, Finding  # noqa: E402
from triage.verify import verify_run  # noqa: E402

REVIEW_SEED = 2026
REVIEW_SIZE = 20
LABELS = ("correct", "incorrect", "unsure")


def claim_findings(report) -> list[Finding]:
    """Turn contradicted / unverifiable claims into layer-1 findings."""
    out = []
    for c in report.claims:
        if c.status in FALSE_SUCCESS_STATUSES and not report.tau2_success:
            sev, know = "violation", "observed"
        elif c.status in ("unverifiable", "claimed_before_executed"):
            sev, know = "info", "needs_verification"
        elif c.status in ("unrequested_change", "wrong_action"):
            sev, know = "violation", "observed"
        elif c.status == "not_executed":  # passing run, claim not backed by any write
            sev, know = "warning", "observed"
        else:
            continue
        out.append(Finding(
            rule_id=f"claim_{c.status}", layer="verify", severity=sev, knowledge=know,
            step=c.step, basis="keyword", message=f"agent claimed '{c.action}' on "
            f"{', '.join(c.entity_ids) or 'unnamed order'}: {c.reason}",
            evidence=[Evidence(c.step, "assistant", c.sentence)],
            details={"diff": c.diff[:3]} if c.diff else {}))
    return out


def failure_reason(r) -> str:
    if r.termination_reason not in ("user_stop", "agent_stop"):
        return "terminated"
    if r.tau2_db_match is False:
        return "db_mismatch"
    return "db_ok_nl_assertion_failed"


def rate(num: int, den: int):
    return {"n": num, "of": den, "rate": round(num / den, 4) if den else None}


def metrics(reports: list) -> dict:
    fails = [r for r in reports if not r.tau2_success]
    passes = [r for r in reports if r.tau2_success]
    has_violation = lambda r: any(f.severity == "violation" for f in r.findings)  # noqa: E731
    flagged = lambda r: bool(r.db_diff) or r.false_success or has_violation(r)  # noqa: E731
    explained = lambda r: r.false_success or has_violation(r)  # noqa: E731

    comparable = [r for r in reports if r.tau2_db_match is not None and r.replay_db_match is not None]
    by_reason = defaultdict(list)
    for r in fails:
        by_reason[failure_reason(r)].append(r)

    rule_hits = defaultdict(lambda: {"in_failed_runs": 0, "in_passing_runs": 0, "hits": 0, "severity": set()})
    for r in reports:
        for rid in {f.rule_id for f in r.findings}:
            rule_hits[rid]["in_failed_runs" if not r.tau2_success else "in_passing_runs"] += 1
        for f in r.findings:
            rule_hits[f.rule_id]["hits"] += 1
            rule_hits[f.rule_id]["severity"].add(f.severity)
    rule_table = {
        rid: {**v, "severity": sorted(v["severity"]),
              "share_of_failed_runs": round(v["in_failed_runs"] / len(fails), 4) if fails else None,
              "share_of_passing_runs": round(v["in_passing_runs"] / len(passes), 4) if passes else None}
        for rid, v in sorted(rule_hits.items())}

    claims = [c for r in reports for c in r.claims]
    return {
        "runs": len(reports), "tau2_successes": len(passes), "tau2_failures": len(fails),
        "replay_sanity_check": {
            "what": "our replayed DB comparison vs tau2's own db_check",
            **rate(sum(r.tau2_db_match == r.replay_db_match for r in comparable), len(comparable)),
        },
        "failure_recall": {
            "ground_truth": "tau2 reward < 1 counts as a failure",
            "any_signal": {
                "what": "DB differs from expected, or false success, or a violation-level rule hit",
                **rate(sum(map(flagged, fails)), len(fails)),
                "flagged_passing_runs": rate(sum(map(flagged, passes)), len(passes)),
            },
            "step_level_explanation": {
                "what": "false success or a violation-level rule hit, i.e. a concrete step to look at "
                        "(DB difference alone does not say which step went wrong)",
                **rate(sum(map(explained, fails)), len(fails)),
                "flagged_passing_runs": rate(sum(map(explained, passes)), len(passes)),
            },
            "by_failure_reason": {
                reason: {"any_signal": rate(sum(map(flagged, rs)), len(rs)),
                         "step_level_explanation": rate(sum(map(explained, rs)), len(rs))}
                for reason, rs in sorted(by_reason.items())},
        },
        "false_success": {
            "definition": "tau2 failure AND the agent told the user an action was done, but no "
                          "successful matching write happened before that message (not_executed) "
                          "or the written entity differs from the expected end state "
                          "(executed_but_differs)",
            "runs": rate(sum(r.false_success for r in fails), len(fails)),
            "runs_by_type": dict(Counter(t for r in fails for t in r.false_success_types)),
            "unbacked_claims_in_passing_runs": sum(r.unbacked_claim_in_passing_run for r in passes),
        },
        "claims": {"total": len(claims), "by_status": dict(Counter(c.status for c in claims)),
                   "by_action": dict(Counter(c.action for c in claims))},
        "rules": rule_table,
    }


def user_goal(task_id: str) -> str:
    """What the simulated user was told to ask for (tau2 task definition)."""
    from triage.verify import _task
    instr = _task(task_id).user_scenario.instructions
    return getattr(instr, "reason_for_call", None) or str(instr)


def review_sample(reports: list) -> list[dict]:
    pool = [r for r in reports if r.false_success]
    picked = random.Random(REVIEW_SEED).sample(pool, min(REVIEW_SIZE, len(pool)))
    items = []
    for i, r in enumerate(sorted(picked, key=lambda r: (int(r.task_id), r.trial)), 1):
        bad, seen = [], set()
        for c in r.claims:
            key = (c.status, tuple(sorted({d["id"] for d in c.diff}) or c.entity_ids))
            if c.status in FALSE_SUCCESS_STATUSES and key not in seen:
                seen.add(key)
                bad.append(c)
        items.append({
            "case": i, "file": r.file, "task_id": r.task_id, "trial": r.trial,
            "user_goal": user_goal(r.task_id),
            "claims": [{"step": c.step, "action": c.action, "entity_ids": c.entity_ids,
                        "sentence": c.sentence, "status": c.status, "reason": c.reason,
                        "diff": [{"id": d["id"], "fields": d["fields"][:4]} for d in c.diff]}
                       for c in bad[:3]],
            "human_label": None, "human_note": "",
        })
    return items


def write_review_md(items: list[dict], tag: str, path: Path) -> None:
    lines = [
        f"# 假成功人工抽查（{tag}，随机抽 {len(items)} 条，种子 {REVIEW_SEED}）", "",
        "每条请判断：**agent 是否真的对用户声称完成了某个操作，而数据库里这个操作没发生或做错了？**",
        "在 `results/false_success_review.json` 对应条目的 `human_label` 填 "
        "`correct`（确实是假成功）/ `incorrect`（规则误判）/ `unsure`，可在 `human_note` 写一句理由。",
        "也可以直接在对话里告诉我每条的判断，我来填。", "",
        "状态说明：`not_executed` = 声称完成，但此前没有成功执行对应操作；"
        "`executed_but_differs` = 做的是对的那类操作，但细节和任务期望不一致，比如换错了款式、取消原因不对"
        "（final = 实际结果，expected = 任务期望）。", "",
        "判断标准：只要 agent 对用户说「办好了」，而实际结果和用户要的不一样，就算 `correct`。"
        "如果差异是用户自己中途改口造成的、或差异无关紧要，算 `incorrect`。", "",
    ]
    for it in items:
        lines.append(f"## {it['case']}. 任务 {it['task_id']} 第 {it['trial']} 局  `{it['file']}`")
        lines.append(f"- 用户诉求（任务设定）：{it['user_goal']}")
        for c in it["claims"]:
            lines.append(f"- 第 {c['step']} 步，声称 **{c['action']}** {', '.join(c['entity_ids'])} → `{c['status']}`")
            lines.append(f"  - 原话：> {c['sentence']}")
            lines.append(f"  - 依据：{c['reason']}")
            for d in c["diff"]:
                for f in d["fields"]:
                    lines.append(f"  - 差异 {d['id']} `{f['path']}`：final=`{f['final']}` expected=`{f['expected']}`")
        lines.append("")
    path.write_text("\n".join(lines))


def apply_review(out_path: Path, review_path: Path) -> None:
    items = json.loads(review_path.read_text())
    labels = Counter(it.get("human_label") for it in items)
    labelled = labels["correct"] + labels["incorrect"]
    result = json.loads(out_path.read_text())
    result["false_success"]["precision_human_review"] = {
        "sample": len(items), "correct": labels["correct"], "incorrect": labels["incorrect"],
        "unsure": labels["unsure"], "unlabelled": labels[None],
        "precision": round(labels["correct"] / labelled, 4) if labelled else None,
        "note": "precision = correct / (correct + incorrect); unsure and unlabelled are excluded",
        "source": str(review_path.relative_to(ROOT)),
    }
    out_path.write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(json.dumps(result["false_success"]["precision_human_review"], indent=1))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--apply-review", action="store_true")
    ap.add_argument("--triage-only", action="store_true",
                    help="only write results/triage/<tag>.json (used for phase-4 batches)")
    args = ap.parse_args(argv)
    out_path = ROOT / "results" / "eval_verify.json"
    review_json = ROOT / "results" / "false_success_review.json"
    if args.apply_review:
        apply_review(out_path, review_json)
        return 0

    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="ERROR")

    run_dir = ROOT / "results" / "runs" / args.tag
    reports = []
    for path in sorted(run_dir.glob("task_*__trial_*.json")):
        report = verify_run(path, args.tag, ROOT)
        report.findings = claim_findings(report) + run_rules(json.loads(path.read_text()))
        reports.append(report)

    triage_dir = ROOT / "results" / "triage"
    triage_dir.mkdir(parents=True, exist_ok=True)
    (triage_dir / f"{args.tag}.json").write_text(
        json.dumps([r.to_dict() for r in reports], indent=1, ensure_ascii=False, default=str))
    if args.triage_only:
        print(f"{len(reports)} runs triaged -> results/triage/{args.tag}.json")
        return 0

    result = {"tag": args.tag, "source_files": {
        "runs": f"results/runs/{args.tag}/", "triage": f"results/triage/{args.tag}.json"},
        **metrics(reports)}
    result["false_success"]["precision_human_review"] = {
        "status": "pending", "note": "未测: waiting for the manual check of results/false_success_review.json"}
    out_path.write_text(json.dumps(result, indent=1, ensure_ascii=False))

    items = review_sample(reports)
    if not review_json.exists() or not any(it.get("human_label") for it in json.loads(review_json.read_text())):
        review_json.write_text(json.dumps(items, indent=1, ensure_ascii=False, default=str))
        write_review_md(items, args.tag, ROOT / "results" / "false_success_review.md")
    print(json.dumps({k: v for k, v in result.items() if k != "rules"}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
