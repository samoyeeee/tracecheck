"""The investigator's tools: deterministic views of one trajectory.

They are plain functions (no LLM). To fit the free tier's 15 requests/minute,
the investigator does not call them in a multi-turn function-calling loop;
each arm runs the tools it is allowed to use up front and puts their output
in a single prompt:

- ``render_steps``       read the trajectory step by step       (arms A, B, C)
- ``outcome_check``      final outcome vs the expected one      (arms B, C)
- ``rule_findings``      layer-1/2 rule hits                     (arms B, C)
- ``same_task_success``  a successful run of the same task       (tau2 runs only)
"""

from __future__ import annotations

import json
from pathlib import Path

from triage.trajectory import ROOT, WRITE_TOOLS, Trajectory

MAX_TOOL_RESULT = 6000  # characters of one tool result shown to the model


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + f" …[{len(text) - n} more chars]"


def render_steps(t: Trajectory, start: int | None = None, end: int | None = None) -> str:
    lines = []
    for msg, step in zip(t.messages, t.steps):
        if (start is not None and step < start) or (end is not None and step > end):
            continue
        role = msg.get("role")
        text = (msg.get("content") or "").strip()
        if role == "system":
            lines.append(f"[step {step}] SYSTEM: (agent policy, shown above)")
        elif role == "tool":
            flag = " (ERROR)" if msg.get("error") else ""
            lines.append(f"[step {step}] TOOL RESULT{flag}: {_clip(text, MAX_TOOL_RESULT)}")
        elif role == "assistant":
            parts = [text] if text else []
            for tc in msg.get("tool_calls") or []:
                parts.append(f"CALL {tc['name']}({json.dumps(tc['arguments'], ensure_ascii=False)})")
            lines.append(f"[step {step}] AGENT: " + " | ".join(parts))
        else:
            lines.append(f"[step {step}] USER: {text}")
    return "\n".join(lines)


def _agent_writes(t: Trajectory) -> list[dict]:
    results = {m.get("id"): m for m in t.messages if m.get("role") == "tool"}
    out = []
    for msg, step in zip(t.messages, t.steps):
        for tc in (msg.get("tool_calls") or []) if msg.get("role") == "assistant" else []:
            if tc["name"] in WRITE_TOOLS:
                res = results.get(tc["id"], {})
                out.append({"step": step, "name": tc["name"], "args": tc["arguments"],
                            "ok": bool(res) and not res.get("error")})
    return out


def outcome_check(t: Trajectory, db_diff: list | None = None) -> str:
    """Expected vs actual writes, required outputs, and the benchmark's own checks."""
    lines = []
    expected = [a for a in t.expected_actions if a["name"] in WRITE_TOOLS]
    done = _agent_writes(t)
    lines.append("Reference solution's database-changing actions:" if expected
                 else "Reference solution makes NO database-changing action.")
    for a in expected:
        exact = [w for w in done if w["ok"] and w["name"] == a["name"] and w["args"] == a["args"]]
        near = [w for w in done if w["name"] == a["name"] and w not in exact]
        if exact:
            status = f"done exactly at step {exact[0]['step']}"
        elif near:
            w = near[0]
            diff = {k: {"agent": w["args"].get(k), "expected": v}
                    for k, v in a["args"].items() if w["args"].get(k) != v}
            status = (f"agent called it at step {w['step']} "
                      f"({'succeeded' if w['ok'] else 'FAILED'}) with different arguments: "
                      f"{json.dumps(diff, ensure_ascii=False)}")
        else:
            status = "NOT done by the agent"
        lines.append(f"- {a['name']}({json.dumps(a['args'], ensure_ascii=False)}): {status}")
    extra = [w for w in done if w["ok"] and not any(w["name"] == a["name"] for a in expected)]
    for w in extra:
        lines.append(f"- agent also did {w['name']} at step {w['step']}, which the reference never does")
    for out in t.expected_outputs:
        said = any(out.lower() in (m.get("content") or "").lower()
                   for m in t.messages if m.get("role") == "assistant")
        lines.append(f"- required answer '{out}' {'appears' if said else 'does NOT appear'} in the agent's messages")
    checks = {k: v for k, v in t.benchmark_checks.items() if k != "nl_assertions" and v is not None}
    lines.append(f"Benchmark checks: {json.dumps(checks, ensure_ascii=False)}")
    for a in t.benchmark_checks.get("nl_assertions") or []:
        lines.append(f"- requirement on what the agent says: '{a['assertion']}' -> {'met' if a['met'] else 'NOT met'}")
    for d in db_diff or []:
        fields = "; ".join(f"{f['path']}: agent={f['final']} expected={f['expected']}" for f in d["fields"][:5])
        lines.append(f"- final database differs for {d['id']}: {fields}")
    return "\n".join(lines)


def rule_findings(t: Trajectory) -> tuple[str, list[dict]]:
    """Run layer-2 rules on the trajectory; steps mapped to this trajectory's numbering."""
    from triage.rules import run_rules

    sim = {"messages": t.messages, "termination_reason": t.benchmark_checks.get("termination_reason")}
    hits = []
    for f in run_rules(sim):
        if f.rule_id == "policy_one_action_per_turn":
            continue  # fires on most runs, passing or failing; no diagnostic value (phase 2)
        step = t.step_of(f.step) if f.step is not None and f.step < len(t.steps) else f.step
        hits.append({"rule": f.rule_id, "severity": f.severity, "step": step, "message": f.message})
    text = "\n".join(f"- [{h['severity']}] step {h['step']}: {h['rule']} - {h['message']}" for h in hits)
    return text or "(no rule fired)", hits


def same_task_success(t: Trajectory, run_dir: Path | None = None) -> str:
    """Tool calls of a successful trial of the same task (tau2 runs only)."""
    if t.source != "tau2":
        return ""
    run_dir = run_dir or (ROOT / Path(t.file).parent)
    for path in sorted(run_dir.glob(f"task_{t.task_id}__trial_*.json")):
        sim = json.loads(path.read_text())
        if (sim.get("reward_info") or {}).get("reward") == 1.0:
            calls = [f"step {i}: {tc['name']}({json.dumps(tc.get('arguments') or {}, ensure_ascii=False)})"
                     for i, m in enumerate(sim.get("messages") or []) for tc in (m.get("tool_calls") or [])]
            return f"A successful trial of the same task ({path.name}) made these tool calls:\n" + "\n".join(calls)
    return ""
