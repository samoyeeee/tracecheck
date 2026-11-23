"""Turn one failed run into a regression test, and replay it for real.

    case = create_case("results/runs/bug_dropitem/task_2__trial_1.json")
    run = replay(case["id"], version="v1")          # one real simulation + database check

A case stores everything needed to rerun the failure and judge the rerun:
the tau2 task (its initial database comes from the task definition), a hash of
that initial database, the expected end state of the fields the failure was
about, the failure evidence, and the agent version that failed.

A replay
  1. rebuilds the environment from the task and checks its database hash
     against the one stored in the case (reset check),
  2. runs the chosen agent version against the tau2 user simulator once,
  3. replays the result with triage.verify and checks the case's fields.
Every replay of a case starts from the same initial database; only the
simulator's sampling differs (seed). Results are appended to the case file.
A handful of replays says what those replays did, nothing more: no
significance is claimed (see summarise()).
"""

from __future__ import annotations

import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "results" / "regression_cases"
REPLAYS = ROOT / "results" / "replays"
REPLAY_SEED = 900                       # replays use seeds 900, 901, ... (the batches used 300+)
MAX_REPEATS = 5


class ReplayError(Exception):
    """A replay that could not produce a verifiable result; `kind` says why (shown to the user)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def case_id(file: str) -> str:
    p = Path(file)
    return f"rc_{p.parent.name}__{p.stem}"


def _initial_hash(task_id: str) -> str:
    from triage.verify import _fresh_env, _task
    env = _fresh_env(_task(str(task_id)), [])
    return env.get_db_hash()


def estimate_calls(sim: dict) -> dict:
    """Rough model calls per replay, from the source run: one per agent turn, one per user turn, plus the judge."""
    msgs = sim.get("messages") or []
    agent = sum(m.get("role") == "assistant" for m in msgs)
    user = sum(m.get("role") == "user" for m in msgs)
    judge = 1 if (sim.get("reward_info") or {}).get("nl_assertions") else 0
    return {"agent": agent, "user": user, "judge": judge, "total": agent + user + judge,
            "basis": "turns in the source run; a replay can take more or fewer"}


def create_case(file: str) -> dict:
    """Save a regression case for a failed run (idempotent: the same run gives the same case)."""
    from agent.versions import SPECS
    from triage.pipeline import build_report
    from triage.verify import _task

    path = (ROOT / file).resolve()
    rel = str(path.relative_to(ROOT))
    cid = case_id(rel)
    out = CASES / f"{cid}.json"
    if out.exists():
        return json.loads(out.read_text())
    sim = json.loads(path.read_text())
    report = build_report(path)
    task = _task(str(sim["task_id"]))
    version = path.parent.name
    rows = [r for r in report["comparison"]]
    case = {
        "id": cid, "created": _now(), "source_file": rel,
        "source_version": version if version in SPECS else None,
        "task_id": str(sim["task_id"]), "source_trial": sim.get("trial"),
        "user_goal": report["goal"]["original"],
        "initial_db_hash": _initial_hash(str(sim["task_id"])),
        "expected": [{"entity": r["entity"], "field": r["field"], "field_zh": r["field_zh"], "expected": r["expected"]}
                     for r in rows],
        "reference_actions": [{"name": a.name, "arguments": a.arguments}
                              for a in (task.evaluation_criteria.actions or [])],
        "failure": {"verdict": report["verdict"]["headline"], "kind": report["verdict"]["kind"],
                    "rows": [r for r in rows if not r["match"]], "tau2_reward": report["tau2"]["reward"],
                    "facts": report["facts"]},
        "estimated_calls_per_replay": estimate_calls(sim),
        "replays": [],
    }
    CASES.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(case, indent=1, ensure_ascii=False))
    return case


def load_case(cid: str) -> dict:
    path = CASES / f"{cid}.json"
    if not path.exists() or path.parent != CASES:
        raise ValueError(f"没有这个回归用例：{cid}")
    return json.loads(path.read_text())


def _run_simulation(task_id: str, version: str, seed: int):
    """One tau2 simulation of `version` on the task, through the project's rate-limited gateway."""
    import yaml

    from agent.versions import SPECS, register_all, registered_name
    from runner.gateway import install
    from runner.run_batch import gateway_config
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner import get_tasks, run_single_task

    if version not in SPECS:
        raise ReplayError("bad_version", f"没有这个 agent 版本：{version}")
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    m, run = cfg["models"], cfg["run"]
    gw = install(gateway_config(cfg))
    gw.run_tag = "replay"
    gw.role_by_model = {m["user"]: "user", m["agent"]: "agent"}
    register_all()
    config = TextRunConfig(domain=run["domain"], agent=registered_name(version),
                           llm_agent=m["agent"], llm_args_agent={"temperature": m["temperature"]},
                           llm_user=m["user"], llm_args_user={"temperature": m["temperature"]},
                           max_steps=run["max_steps"], max_errors=run["max_errors"])
    task = get_tasks(run["domain"], task_ids=[str(task_id)])[0]
    return run_single_task(config, task, seed=seed)


def _cost_rows() -> int:
    path = ROOT / "results" / "cost_log.csv"
    return sum(1 for _ in path.open()) if path.exists() else 0


def replay(cid: str, version: str, progress: Optional[Callable[[str], None]] = None) -> dict:
    """One real replay of a case. Always returns a record; failures are recorded with their kind."""
    from runner.gateway import DailyQuotaExhausted
    from triage.pipeline import build_report

    say = progress or (lambda _msg: None)
    case = load_case(cid)
    n = len(case["replays"])
    seed = REPLAY_SEED + n
    rec = {"n": n + 1, "version": version, "seed": seed, "started": _now(), "status": "error"}
    before = _cost_rows()
    t0 = time.time()
    try:
        say("重置测试环境…")
        try:
            h = _initial_hash(case["task_id"])
        except Exception as exc:  # noqa: BLE001
            raise ReplayError("reset_failed", f"无法重建初始数据库：{type(exc).__name__}: {exc}")
        if h != case["initial_db_hash"]:
            raise ReplayError("reset_failed", "重建出的初始数据库和用例保存的不一致，结果没有可比性，已停止。")
        rec["initial_db_hash_ok"] = True

        say(f"用 {version} 运行任务（真实模型调用，约 1–3 分钟）…")
        try:
            sim = _run_simulation(case["task_id"], version, seed)
        except ReplayError:
            raise
        except DailyQuotaExhausted as exc:
            raise ReplayError("quota", f"模型今天的免费额度不够了：{exc}")
        except Exception as exc:  # noqa: BLE001
            text = f"{type(exc).__name__}: {exc}"
            kind = "rate_limited" if "RateLimit" in text or "429" in text else "run_failed"
            raise ReplayError(kind, f"运行失败：{text[:300]}")
        sim.trial = n
        out_dir = REPLAYS / cid
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{version}__task_{case['task_id']}__trial_{n}.json"
        path.write_text(sim.model_dump_json(indent=1))
        rec["file"] = str(path.relative_to(ROOT))
        rec["termination"] = sim.termination_reason.value if sim.termination_reason else None
        rec["tau2_reward"] = sim.reward_info.reward if sim.reward_info else None

        say("核验最终数据库…")
        try:
            report = build_report(path)
        except Exception as exc:  # noqa: BLE001
            raise ReplayError("unverifiable", f"无法核验：{type(exc).__name__}: {exc}")
        by_field = {(r["entity"], r["field"]): r for r in report["comparison"]}
        checks = []
        for e in case["expected"]:
            got = by_field.get((e["entity"], e["field"]))
            # a field missing from the replay's comparison was left untouched and matches the reference
            checks.append({**e, "actual": got["actual"] if got else e["expected"],
                           "ok": True if got is None else got["match"]})
        rec.update({
            "case_fields_ok": all(c["ok"] for c in checks), "checks": checks,
            "db_match": report["tau2"]["db_match"], "false_success": report["tau2"]["false_success"],
            "verdict": report["verdict"]["headline"], "kind": report["verdict"]["kind"],
            "status": "passed" if all(c["ok"] for c in checks) and report["tau2"]["db_match"] else "failed",
        })
    except ReplayError as exc:
        rec.update({"status": "error", "error_kind": exc.kind, "error": str(exc)})
    except Exception as exc:  # noqa: BLE001 - never lose the record
        rec.update({"status": "error", "error_kind": "internal", "error": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc()[-1500:]})
    rec["seconds"] = round(time.time() - t0, 1)
    rec["model_calls"] = max(0, _cost_rows() - before)
    case = load_case(cid)                      # re-read: another replay may have finished meanwhile
    case["replays"].append(rec)
    (CASES / f"{cid}.json").write_text(json.dumps(case, indent=1, ensure_ascii=False))
    return rec


def summarise(case: dict) -> dict:
    """Per version: how many replays passed. Wording never claims a verified fix."""
    out = {}
    for r in case["replays"]:
        s = out.setdefault(r["version"], {"runs": 0, "passed": 0, "failed": 0, "errors": 0, "task_passed": 0})
        s["runs"] += 1
        s[{"passed": "passed", "failed": "failed"}.get(r["status"], "errors")] += 1
        s["task_passed"] += 1 if r.get("tau2_reward") == 1 else 0
    for v, s in out.items():
        done = s["passed"] + s["failed"]
        s["statement"] = (f"{done} 次可核验的重放中，用例字段 {s['passed']} 次全部正确，"
                          f"整个任务（τ² 判定）{s['task_passed']} 次通过" if done else "还没有可核验的重放") + \
            ("；次数太少，不能说明修复已被充分验证，也不代表统计显著" if done else "")
    return out
