"""Resumable batch runner for tau2 retail simulations.

One file per (task, trial) is written to results/runs/<tag>/. Re-running the
same command skips everything that is already finished, so a run can be
stopped (Ctrl-C, daily quota exhausted, laptop closed) and continued later:

    python -m runner.run_batch --tag v1                 # run / resume
    python -m runner.run_batch --tag v1 --status        # progress only
    python -m runner.run_batch --tag smoke --task-ids 0 1 2 --k 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runner.gateway import (  # noqa: E402
    DailyQuotaExhausted, GatewayConfig, ModelLimit, Provider, install,
)

INFRA = "infrastructure_error"
MAX_CRASHES = 3


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def parse_shard(text: str | None) -> tuple[int, int]:
    """'1/2' -> (1, 2): this process is worker 1 of 2. None -> (0, 1), i.e. everything."""
    if not text:
        return 0, 1
    i, n = (int(x) for x in text.split("/"))
    if not 0 <= i < n:
        raise ValueError(f"bad --shard {text!r}: need 0 <= i < n")
    return i, n


def shard_tasks(task_ids: list[str], shard: tuple[int, int]) -> list[str]:
    """Tasks owned by this worker: every n-th task, so workers never overlap."""
    i, n = shard
    return [t for idx, t in enumerate(task_ids) if idx % n == i]


def gateway_config(cfg: dict, shard: tuple[int, int] = (0, 1)) -> GatewayConfig:
    # Each parallel worker keeps its own request counter file (no write races).
    state = "quota_state.json" if shard[1] == 1 else f"quota_state.shard{shard[0]}.json"
    return GatewayConfig(
        default_model=cfg["models"]["agent"],
        judge_model=cfg["models"]["judge"],
        limits={m: ModelLimit(**v) for m, v in cfg["rate_limits"].items()},
        providers={n: Provider(**v) for n, v in cfg["providers"].items()},
        list_prices=cfg.get("list_prices") or {},
        state_path=ROOT / "results" / state,
        cost_log_path=ROOT / "results" / "cost_log.csv",
    )


def sim_path(run_dir: Path, task_id: str, trial: int) -> Path:
    return run_dir / f"task_{task_id}__trial_{trial}.json"


def is_done(path: Path) -> bool:
    """Finished = file exists and the simulation was not an infra failure."""
    if not path.exists():
        return False
    try:
        return json.loads(path.read_text()).get("termination_reason") != INFRA
    except json.JSONDecodeError:
        return False


def record_crash(path: Path, task_id: str, trial: int, exc: Exception) -> None:
    """Keep a record of a crashed simulation.

    It is stored as an infrastructure error, so a later run retries it. After
    MAX_CRASHES attempts we stop retrying and keep it as ``agent_crash``: it is
    then counted as a failed run (reward 0) and reported separately - it is
    never silently dropped from the denominator.
    """
    crashes = 1
    if path.exists():
        try:
            crashes = json.loads(path.read_text()).get("crashes", 0) + 1
        except json.JSONDecodeError:
            pass
    reason = "agent_crash" if crashes >= MAX_CRASHES else INFRA
    path.write_text(json.dumps({
        "task_id": task_id, "trial": trial, "termination_reason": reason,
        "crashes": crashes, "reward_info": {"reward": 0.0} if reason == "agent_crash" else None,
        "info": {"error_type": type(exc).__name__, "error": str(exc)[:2000]}, "messages": [],
    }, indent=1))


def plan(task_ids: list[str], k: int, run_dir: Path) -> list[tuple[str, int]]:
    """Pending (task, trial) pairs, trial-major so every task gets trial 0 first."""
    return [(t, trial) for trial in range(k) for t in task_ids
            if not is_done(sim_path(run_dir, t, trial))]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True, help="run name, e.g. v1")
    ap.add_argument("--agent", default="v1",
                    help="agent version from agent/versions.py (v1, ...) or a built-in tau2 agent name")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--task-ids", nargs="*", help="override config task selection")
    ap.add_argument("--k", type=int, help="override trials per task")
    ap.add_argument("--shard", help="i/n: run only every n-th task starting at i, so n "
                    "processes can work on the same tag in parallel")
    ap.add_argument("--status", action="store_true", help="print progress and exit")
    for role in ("agent", "user", "judge"):
        ap.add_argument(f"--{role}-model", help=f"override models.{role} from the config")
    args = ap.parse_args(argv)

    cfg = load_config(Path(args.config))
    for role in ("agent", "user", "judge"):
        if getattr(args, f"{role}_model"):
            cfg["models"][role] = getattr(args, f"{role}_model")
    run = cfg["run"]
    k = args.k or run["k"]
    run_dir = ROOT / "results" / "runs" / args.tag
    run_dir.mkdir(parents=True, exist_ok=True)

    # Every provider used by the configured models needs its key in the environment.
    used = {cfg["rate_limits"][cfg["models"][r]]["provider"] for r in ("agent", "user", "judge")}
    missing = [cfg["providers"][n]["key_env"] for n in used if not os.environ.get(cfg["providers"][n]["key_env"])]
    if missing:
        sys.exit(f"Missing environment variable(s): {', '.join(missing)} (see .env.example).")

    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner import get_tasks, run_single_task

    task_ids = args.task_ids or run.get("task_ids")
    tasks = get_tasks(run["domain"], task_split_name=None if task_ids else run["task_split"],
                      task_ids=[str(t) for t in task_ids] if task_ids else None)
    by_id = {t.id: t for t in tasks}
    shard = parse_shard(args.shard)
    mine = shard_tasks(list(by_id), shard)
    pending = plan(mine, k, run_dir)
    total = len(mine) * k
    print(f"[{args.tag}] {total - len(pending)}/{total} simulations done, {len(pending)} pending "
          f"({len(mine)} tasks x k={k}).")
    if args.status or not pending:
        return 0

    from loguru import logger
    logger.remove()  # tau2 logs every step at DEBUG; keep only problems
    logger.add(sys.stderr, level="ERROR")

    gw = install(gateway_config(cfg, shard))
    gw.run_tag = args.tag
    m = cfg["models"]
    gw.role_by_model = {m["user"]: "user", m["agent"]: "agent"}  # for the usage log

    from agent.versions import SPECS, register_all, registered_name
    spec = SPECS.get(args.agent)
    agent_name = registered_name(args.agent) if spec else args.agent
    if spec:
        register_all()
    llm_args = {"temperature": m["temperature"]}
    config = TextRunConfig(
        domain=run["domain"], agent=agent_name,
        llm_agent=m["agent"], llm_args_agent=dict(llm_args),
        llm_user=m["user"], llm_args_user=dict(llm_args),
        max_steps=run["max_steps"], max_errors=run["max_errors"],
    )
    meta = {"tag": args.tag, "agent": args.agent, "models": m, "k": k,
            "task_ids": list(by_id), "run": run,
            "agent_description": spec.description if spec else "tau2 built-in agent",
            "tau2_commit": "c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4"}
    (run_dir / "_run_meta.json").write_text(json.dumps(meta, indent=1))

    done_now = 0
    try:
        for task_id, trial in pending:
            for model in {m["agent"], m["user"]}:
                left = gw.limiter.remaining_today(model)
                if left < run["min_requests_to_start"]:
                    raise DailyQuotaExhausted(
                        f"{model}: only {left} requests left today, not starting a new simulation.")
            t0 = time.time()
            path = sim_path(run_dir, task_id, trial)
            try:
                sim = run_single_task(config, by_id[task_id], seed=run["base_seed"] + trial)
            except Exception as exc:  # noqa: BLE001 - one bad simulation must not kill the batch
                record_crash(path, task_id, trial, exc)
                print(f"  task {task_id} trial {trial}: CRASHED {type(exc).__name__}: {str(exc)[:150]}", flush=True)
                continue
            sim.trial = trial
            tmp = path.with_suffix(".tmp")
            tmp.write_text(sim.model_dump_json(indent=1))
            tmp.replace(path)  # atomic: a killed run never leaves a half file
            reward = sim.reward_info.reward if sim.reward_info else None
            done_now += 1
            print(f"  task {task_id} trial {trial}: reward={reward} "
                  f"termination={sim.termination_reason.value} "
                  f"msgs={len(sim.messages or [])} {time.time() - t0:.0f}s", flush=True)
    except DailyQuotaExhausted as exc:
        print(f"\nStopped: {exc}\nRe-run the same command after the quota resets "
              f"(midnight Pacific time) to continue.")
    except KeyboardInterrupt:
        print("\nInterrupted. Re-run the same command to continue.")
    left = len(plan(mine, k, run_dir))
    print(f"[{args.tag}] finished {done_now} this session, {left} still pending. "
          f"Requests used today: " + ", ".join(
              f"{mod}={gw.limiter.used_today(mod)}" for mod in cfg["rate_limits"]))
    if gw.observed_limits:
        print(f"Limits reported by the server in 429s: {gw.observed_limits}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
