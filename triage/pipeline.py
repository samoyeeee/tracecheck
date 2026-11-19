"""Analyse ONE agent run end to end - what the interactive web page calls.

    analyze_layers(path)          -> layers 1-2 (rules + database check), no model call
    add_diagnosis(case, path)     -> layer 3 (investigator agent), 3 model calls

Both return / fill the same "case" dict the audit card renders, so the
pre-computed demo (web/export.py) and live analysis (web/serve.py) show
exactly the same thing.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_TEXT = 1500          # clip long tool results in the timeline
DIAGNOSIS_FIELDS = ("critical_step", "failed_agent", "category", "evidence", "observed_facts", "inference",
                    "needs_verification", "confidence", "abstain", "abstain_reason", "summary", "model",
                    "prompt_version", "error")


class InputError(ValueError):
    """The uploaded run cannot be analysed (message is shown to the user, in Chinese)."""


def validate_run(sim: dict) -> None:
    """A tau2 retail simulation: messages plus a known task id (needed to replay the database)."""
    from triage.verify import _task

    if not isinstance(sim, dict) or not isinstance(sim.get("messages"), list) or not sim["messages"]:
        raise InputError("不是 τ²-bench 运行记录：缺少 messages 列表。")
    if "task_id" not in sim:
        raise InputError("缺少 task_id：需要它找到任务的初始数据库和标准答案。")
    try:
        _task(str(sim["task_id"]))
    except Exception:
        raise InputError(f"task_id = {sim['task_id']!r} 不是 τ²-bench retail 里的任务（0–113）。")


def timeline(sim: dict) -> list[dict]:
    out = []
    for i, m in enumerate(sim.get("messages") or []):
        text = (m.get("content") or "").strip()
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + f" …（已截断，原文 {len(text)} 字符）"
        out.append({"step": i, "role": m.get("role"), "text": text, "error": bool(m.get("error")),
                    "calls": [{"name": c["name"], "args": c.get("arguments")} for c in m.get("tool_calls") or []]})
    return out


def case_from_report(report: dict, sim: dict, user_goal: str) -> dict:
    """The audit-card dict from a triage report (as stored in results/triage/<tag>.json)."""
    findings = [f for f in report["findings"] if f["rule_id"] != "policy_one_action_per_turn"]
    return {
        "id": Path(report["file"]).stem, "file": report["file"], "task_id": report["task_id"],
        "trial": report["trial"], "user_goal": user_goal,
        "tau2": {"reward": report["tau2_reward"], "termination": report["termination_reason"],
                 "db_match": report["tau2_db_match"], "false_success": report["false_success"]},
        "timeline": timeline(sim),
        "findings": [{"rule": f["rule_id"], "severity": f["severity"], "step": f["step"],
                      "message": f["message"], "policy": f.get("policy_quote")} for f in findings],
        "claims": [c for c in report["claims"] if c["status"] != "verified"],
        "db_diff": report["db_diff"],
        "diagnosis": None,
    }


def analyze_layers(path: Path) -> tuple[dict, dict]:
    """Layers 1-2 on a run file under ROOT. Returns (case, raw triage report)."""
    from eval.eval_verify import claim_findings
    from triage.rules import run_rules
    from triage.trajectory import from_tau2
    from triage.verify import verify_run

    sim = json.loads(path.read_text())
    validate_run(sim)
    report = verify_run(path, "web", ROOT)
    report.findings = claim_findings(report) + run_rules(sim)
    raw = json.loads(json.dumps(asdict(report), default=str))
    return case_from_report(raw, sim, from_tau2(path).user_goal), raw


def add_diagnosis(case: dict, path: Path, db_diff: list) -> dict:
    """Layer 3: the investigator agent (3 samples, vote, abstain). Needs the model key."""
    import yaml

    from triage.investigator import investigate
    from triage.trajectory import from_tau2

    model = yaml.safe_load((ROOT / "config.yaml").read_text())["models"]["investigator"]
    sim = json.loads(path.read_text())
    d = investigate(from_tau2(path), "C", sim.get("policy") or "", model,
                    ROOT / "results" / "investigator" / "web", run_tag="investigator_web",
                    db_diff=db_diff, use_reference=True)
    case["diagnosis"] = {k: getattr(d, k) for k in DIAGNOSIS_FIELDS}
    return case
