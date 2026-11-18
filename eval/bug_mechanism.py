"""Post-hoc (NOT pre-registered) check: did each injected bug change behaviour at all?

    python -m eval.bug_mechanism        # writes results/bug_mechanism_check.json

Reads only saved trajectories; no model calls. For each bug, counts on its
pre-registered task subset (v1 vs the bug variant) the raw behaviour the bug
was meant to cause:
  bug_auth      - a non-auth tool call before any find_user_id_* call
  bug_transfer  - a transfer_to_human_agents call
  bug_noconfirm - a write call whose previous user message has no yes/confirm
  bug_param     - modify_pending_order_items calls that the tool rejected
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRITES = {"cancel_pending_order", "return_delivered_order_items", "exchange_delivered_order_items",
          "modify_pending_order_items", "modify_pending_order_address", "modify_user_address",
          "modify_pending_order_payment"}
YES = re.compile(r"\b(yes|yeah|yep|confirm|go ahead|proceed|please do|sure|correct)\b", re.I)
NOT_AUTH = {"transfer_to_human_agents", "calculate"}


def calls(run: dict) -> list[dict]:
    """Tool calls in order, each with its result message and the last user text before it."""
    out, last_user = [], ""
    msgs = run["messages"]
    for i, m in enumerate(msgs):
        if m.get("role") == "user" and m.get("content"):
            last_user = m["content"]
        for c in m.get("tool_calls") or []:
            res = next((y for y in msgs[i + 1:] if y.get("role") == "tool" and y.get("id") == c["id"]), None)
            out.append({"name": c["name"], "error": bool(res and res.get("error")), "last_user": last_user})
    return out


def behaviour(bug: str, cs: list[dict]) -> int:
    """How many times this run shows the behaviour the bug targets."""
    names = [c["name"] for c in cs]
    if bug == "bug_auth":
        auth = [i for i, n in enumerate(names) if n.startswith("find_user_id")]
        other = [i for i, n in enumerate(names) if not n.startswith("find_user_id") and n not in NOT_AUTH]
        return int(bool(other) and (not auth or auth[0] > other[0]))
    if bug == "bug_transfer":
        return int("transfer_to_human_agents" in names)
    if bug == "bug_noconfirm":
        return sum(1 for c in cs if c["name"] in WRITES and not YES.search(c["last_user"]))
    if bug == "bug_param":
        return sum(1 for c in cs if c["name"] == "modify_pending_order_items" and c["error"])
    raise ValueError(bug)


def summarise(bug: str, tag: str, tasks: set[str]) -> dict:
    runs_with, events, tasks_with, n = 0, 0, set(), 0
    for f in sorted((ROOT / "results" / "runs" / tag).glob("task_*__trial_*.json")):
        tid = re.search(r"task_(\d+)__", f.name).group(1)
        if tid not in tasks:
            continue
        n += 1
        k = behaviour(bug, calls(json.loads(f.read_text())))
        events += k
        if k:
            runs_with += 1
            tasks_with.add(tid)
    return {"runs": n, "runs_with_behaviour": runs_with, "events": events, "tasks_with_behaviour": len(tasks_with)}


def main() -> None:
    plan = json.loads((ROOT / "results" / "regression_plan.json").read_text())["runs"]
    out = {"note": "post-hoc, exploratory; not part of the pre-registered test", "bugs": {}}
    for bug in ("bug_auth", "bug_transfer", "bug_noconfirm", "bug_param"):
        tasks = set(plan[bug]["tasks"])
        out["bugs"][bug] = {"v1": summarise(bug, "v1", tasks), bug: summarise(bug, bug, tasks)}
    path = ROOT / "results" / "bug_mechanism_check.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
