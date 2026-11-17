"""One trajectory format for both sources the investigator reads.

- tau2 simulations (our own runs): step = index in ``messages`` (0-based)
- AgentRx tau-bench trajectories: step = the ``index`` field AgentRx's
  annotations refer to (1-based, the system prompt is step 1)

``messages`` holds the trajectory in the dict shape triage/rules.py expects
(assistant tool_calls as {id, name, arguments}, tool results as {id, content,
error}); ``steps[i]`` is the step number of ``messages[i]``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
AGENTRX = ROOT / "vendor" / "agentrx" / "data"

WRITE_TOOLS = {
    "cancel_pending_order", "exchange_delivered_order_items", "modify_pending_order_address",
    "modify_pending_order_items", "modify_pending_order_payment", "modify_user_address",
    "return_delivered_order_items",
}


@dataclass
class Trajectory:
    source: str                      # "tau2" or "agentrx"
    traj_id: str
    task_id: str
    messages: list[dict]
    steps: list[int]
    user_goal: str = ""
    expected_actions: list[dict] = field(default_factory=list)  # [{name, args}]
    expected_outputs: list[str] = field(default_factory=list)
    benchmark_checks: dict = field(default_factory=dict)        # what the benchmark itself reported
    file: Optional[str] = None

    def step_of(self, i: int) -> int:
        return self.steps[i]


def from_tau2(path: Path) -> Trajectory:
    from triage.verify import _task

    sim = json.loads(path.read_text())
    task = _task(str(sim["task_id"]))
    crit = task.evaluation_criteria
    ri = sim.get("reward_info") or {}
    instr = task.user_scenario.instructions
    return Trajectory(
        source="tau2", traj_id=path.stem, task_id=str(sim["task_id"]),
        messages=sim.get("messages") or [], steps=list(range(len(sim.get("messages") or []))),
        user_goal=getattr(instr, "reason_for_call", "") or str(instr),
        expected_actions=[{"name": a.name, "args": a.arguments} for a in (crit.actions or [])] if crit else [],
        benchmark_checks={
            "reward": ri.get("reward"),
            "termination_reason": sim.get("termination_reason"),
            "db_match": (ri.get("db_check") or {}).get("db_match"),
            "nl_assertions": [{"assertion": a.get("nl_assertion"), "met": a.get("met")}
                              for a in (ri.get("nl_assertions") or [])],
        },
        file=str(path.relative_to(ROOT)),
    )


def from_agentrx(item: dict) -> Trajectory:
    """Convert an original tau-bench (OpenAI chat format) trajectory."""
    messages, steps = [], []
    for m in item["traj"]:
        role = m["role"]
        if role == "assistant":
            calls = [{"id": tc["id"], "name": tc["function"]["name"],
                      "arguments": _args(tc["function"]["arguments"])}
                     for tc in (m.get("tool_calls") or [])]
            messages.append({"role": "assistant", "content": m.get("content") or "",
                             "tool_calls": calls or None})
        elif role == "tool":
            content = m.get("content") or ""
            messages.append({"role": "tool", "id": m.get("tool_call_id"), "content": content,
                             "error": content.strip().lower().startswith("error")})
        else:
            messages.append({"role": role, "content": m.get("content") or ""})
        steps.append(int(m["index"]))
    task = item["info"]["task"]
    ri = item["info"].get("reward_info") or {}
    return Trajectory(
        source="agentrx", traj_id=str(item["task_id"]), task_id=str(item["task_id"]),
        messages=messages, steps=steps, user_goal=task.get("instruction", ""),
        expected_actions=[{"name": a["name"], "args": a["kwargs"]} for a in task.get("actions", [])],
        expected_outputs=list(task.get("outputs") or []),
        benchmark_checks={"reward": item.get("reward"), **(ri.get("info") or {})},
        file=f"vendor/agentrx/data/tau_retail/tau_dataset_failed.json#task_id={item['task_id']}",
    )


def _args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"_unparsed": raw}


# AgentRx's annotation file uses slightly different category names from its README.
CATEGORY_ALIASES = {
    "Instruction Adherence Failure": "Instruction/Plan Adherence Failure",
    "Intent Plan Misalignment": "Intent-Plan Misalignment",
}


def load_agentrx() -> list[tuple[Trajectory, dict]]:
    """(trajectory, ground truth) for the 29 annotated tau-bench failures."""
    trajs = {str(x["task_id"]): x for x in json.loads((AGENTRX / "tau_retail" / "tau_dataset_failed.json").read_text())}
    out = []
    for gt in json.loads((AGENTRX / "ground_truth" / "tau_ground_truth.json").read_text()):
        root = next(f for f in gt["failures"] if f["failure_id"] == gt["root_cause"]["failure_id"])
        label = {
            "critical_step": root["step_number"],
            "category": CATEGORY_ALIASES.get(root["failure_category"], root["failure_category"]),
            "failed_agent": root["failed_agent"].lower(),
            "all_failure_steps": [f["step_number"] for f in gt["failures"]],
            "summary": gt["failure_summary"],
        }
        out.append((from_agentrx(trajs[str(gt["trajectory_id"])]), label))
    return out
