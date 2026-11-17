"""Layer 3: the investigator. An LLM reads one failed trajectory and names the
critical (root-cause) step, the failure category (AgentRx taxonomy) and the
evidence.

Three arms, used for the phase-3 ablation:
  A  trajectory only
  B  A + layer-1/2 results (outcome check, rule findings)
  C  B + every conclusion must cite verbatim evidence + abstain when unsure

    python -m triage.investigator --tag v1      # arm C on v1 failures the rules can't explain

Every call is cached in results/investigator/<experiment>/<traj_id>.json, so
an interrupted run resumes without spending requests twice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from triage.schema import CATEGORIES, Diagnosis  # noqa: E402
from triage.tools import outcome_check, render_steps, rule_findings, same_task_success  # noqa: E402
from triage.trajectory import Trajectory  # noqa: E402

PROMPT_VERSION = "v3"
# Arm C asks the same question SAMPLES times and abstains unless at least
# MIN_AGREE answers name the same step and category (self-consistency). The
# model's self-reported confidence was not usable (0.9-1.0 on most wrong
# answers in tuning), so agreement is the confidence signal.
SAMPLES = 3
MIN_AGREE = 3
SAMPLE_TEMPERATURE = 0.7

CATEGORY_DEFINITIONS = """\
(Definitions from AgentRx, github.com/microsoft/agentrx, MIT licence.)
- Instruction/Plan Adherence Failure: the agent fails to follow the directions, the agreed plan or the domain policy: skips required policy steps, or performs unplanned / unnecessary actions.
- Invention of New Information: the agent introduces, removes or alters information not grounded in any input, context or tool output (hallucinated facts, unjustified omissions).
- Invalid Invocation: a tool call fails because its inputs cannot be parsed or validated (bad / missing arguments). Not wrong logic, just invalid inputs.
- Misinterpretation of Tool Output: the agent reasons incorrectly about a tool's output (e.g. computation or counting errors), or considers only part of it.
- Intent-Plan Misalignment: the agent misreads the user's goal or constraints and pursues the wrong objective or the wrong sequence of steps.
- Underspecified User Intent: the task could not be completed because information was missing or unclear at some point (often the user did not give, or gave wrong, information).
- Intent Not Supported: the user asks for something no available tool can do.
- Guardrails Triggered: execution is blocked by safety / access policies despite a valid plan.
- System Failure: infrastructure problems (timeouts, unreachable tools).
- Inconclusive: the evidence is insufficient to classify."""

BASE_TASK = """\
You are reviewing a FAILED conversation between a customer-service AGENT and a (simulated) USER in an online retail store. The benchmark marked this run as failed.

Find the critical failure step: the single step whose mistake is the root cause of the failure - the decisive error that, had it not happened, would most likely have let the task succeed. Earlier mistakes that were later corrected are NOT the root cause. The mistake can be made by the agent or by the simulated user (e.g. the user gives wrong or incomplete information).

Steps are numbered as shown in [step N]. Use exactly those numbers.

How to pick the step: walk forward through the conversation and take the FIRST mistake from which the run never recovered. Later errors that follow from it (failed retries, wrong summaries, the final wrong write) are symptoms, not the root cause.

How to pick the category (conventions of the annotation scheme):
- A plan with the wrong order or wrong structure (e.g. modifying items first, which locks the order so the address can no longer be changed) is Intent-Plan Misalignment.
- A tool call that the tool rejects because of invalid arguments or an invalid precondition (wrong order status, missing replacement items) is Invalid Invocation.
- A user request that the policy or the tools do not allow is Intent Not Supported.
- Use Instruction/Plan Adherence Failure for skipping a procedure the policy requires (authentication, confirmation, status check) or doing actions nobody asked for.
- If the simulated user gave wrong, incomplete or contradictory information, or made an unsupported assumption, use Underspecified User Intent with failed_agent "user".
- Reading a tool result wrongly (counting, availability, status) is Misinterpretation of Tool Output; stating facts no tool returned is Invention of New Information."""

ARM_C_RULES = """\
Strict rules for your answer:
1. Every conclusion must be backed by evidence: cite the step number and copy a short VERBATIM quote (5-25 words) from that step. Quotes are checked automatically; a quote that does not appear in the cited step is discarded.
2. The critical step must be among your evidence steps.
3. Separate three kinds of statements: observed_facts (directly visible in the trajectory or the checks), inference (your judgement), needs_verification (what a human should double-check).
4. confidence is your probability (0-1) that BOTH the critical step and the category are right. Be calibrated: in this task even careful analysts are right only about half of the time. Use 0.8 or more only when one clear mistake directly explains the failure and no other step competes; use 0.5 or less when two steps or two categories are plausible. If you cannot tell, set "abstain": true. Abstaining is better than guessing."""

SCHEMA_SIMPLE = """\
Answer with JSON only:
{"critical_step": <int>, "failed_agent": "assistant"|"user", "category": "<one category name>",
 "confidence": <0-1>, "summary": "<one sentence>"}"""

SCHEMA_C = """\
Answer with JSON only:
{"critical_step": <int>, "failed_agent": "assistant"|"user", "category": "<one category name>",
 "evidence": [{"step": <int>, "quote": "<verbatim text from that step>"}],
 "observed_facts": ["..."], "inference": ["..."], "needs_verification": ["..."],
 "confidence": <0-1>, "abstain": <true|false>, "summary": "<one sentence>"}"""


def build_prompt(t: Trajectory, arm: str, policy: str, db_diff=None, use_reference=False) -> str:
    parts = [BASE_TASK, "## Failure categories\n" + CATEGORY_DEFINITIONS,
             "## Agent policy\n" + policy.strip(),
             "## What the simulated user wanted\n" + (t.user_goal or "(not available)"),
             "## Trajectory\n" + render_steps(t)]
    if arm in ("B", "C"):
        parts.append("## Automatic checks (deterministic, no LLM)\n### Outcome vs expected\n"
                     + outcome_check(t, db_diff) + "\n### Rule findings\n" + rule_findings(t)[0])
        if use_reference:
            ref = same_task_success(t)
            if ref:
                parts.append("## Reference\n" + ref)
    if arm == "C":
        parts += [ARM_C_RULES, SCHEMA_C]
    else:
        parts.append(SCHEMA_SIMPLE)
    return "\n\n".join(parts)


# --- answer checking ---------------------------------------------------------

def parse_reply(raw: str) -> tuple[dict, str]:
    """Parse the model's JSON. Repairs one known model bug deterministically:
    a list closed with '}' instead of ']' (or the reverse). Returns (parsed, note)."""
    try:
        return json.loads(raw), ""
    except json.JSONDecodeError:
        pass
    out, stack, in_str, esc = [], [], False, False
    for ch in raw:
        if in_str:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "[{":
            stack.append(ch)
        elif ch in "]}":
            if stack:
                ch = "]" if stack.pop() == "[" else "}"
        out.append(ch)
    try:
        return json.loads("".join(out)), "repaired mismatched brackets"
    except json.JSONDecodeError:
        return {}, "model reply was not valid JSON"




def _norm(text: str) -> str:
    text = re.sub(r"[\"'“”‘’`*…]|\.\.\.", " ", text.lower())
    return " ".join(text.split())


def step_text(t: Trajectory, step: int) -> str:
    return render_steps(t, start=step, end=step)


def check_evidence(t: Trajectory, evidence: list) -> list[dict]:
    out = []
    for e in evidence or []:
        try:
            step = int(e.get("step"))
        except (TypeError, ValueError, AttributeError):
            continue
        quote = str(e.get("quote", ""))
        valid = bool(_norm(quote)) and _norm(quote) in _norm(step_text(t, step))
        out.append({"step": step, "quote": quote, "valid": valid})
    return out


def _category(raw) -> str | None:
    if not raw:
        return None
    key = re.sub(r"[^a-z]", "", str(raw).lower())
    for c in CATEGORIES:
        if re.sub(r"[^a-z]", "", c.lower()) == key:
            return c
    return None


def to_diagnosis(t: Trajectory, arm: str, parsed: dict, model: str) -> Diagnosis:
    def as_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def as_float(v):
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return None

    d = Diagnosis(
        traj_id=t.traj_id, arm=arm, prompt_version=PROMPT_VERSION,
        critical_step=as_int(parsed.get("critical_step")),
        failed_agent=str(parsed.get("failed_agent", "")).lower() or None,
        category=_category(parsed.get("category")),
        evidence=check_evidence(t, parsed.get("evidence")) if arm == "C" else [],
        observed_facts=list(parsed.get("observed_facts") or []),
        inference=list(parsed.get("inference") or []),
        needs_verification=list(parsed.get("needs_verification") or []),
        confidence=as_float(parsed.get("confidence")),
        abstain=False, summary=str(parsed.get("summary", "")), model=model,
    )
    if parsed.get("category") and d.category is None:
        d.error = f"unknown category {parsed.get('category')!r}"
    # Arm C abstention is decided in vote(), across samples.
    return d


# --- calling the model -------------------------------------------------------

def call_model(prompt: str, model: str, run_tag: str, temperature: float = 0.0) -> tuple[str, dict]:
    import litellm

    from runner.gateway import extract_json, install
    from runner.run_batch import gateway_config, load_config

    gw = install(gateway_config(load_config(ROOT / "config.yaml")))
    gw.run_tag = run_tag
    resp = litellm.completion(model=model, messages=[{"role": "user", "content": prompt}],
                              temperature=temperature, tracecheck_role="investigator",
                              response_format={"type": "json_object"})
    text = resp.choices[0].message.content or ""
    usage = getattr(resp, "usage", None)
    return extract_json(text), {"prompt_tokens": getattr(usage, "prompt_tokens", None),
                                "completion_tokens": getattr(usage, "completion_tokens", None)}


def investigate(t: Trajectory, arm: str, policy: str, model: str, cache_dir: Path,
                run_tag: str, db_diff=None, use_reference=False) -> Diagnosis:
    """Diagnose one trajectory. Arm C = SAMPLES answers combined by vote."""
    if arm != "C":
        return _ask(t, arm, policy, model, cache_dir, run_tag, db_diff, use_reference)
    answers = [_ask(t, arm, policy, model, cache_dir / f"s{i}", run_tag, db_diff, use_reference,
                    temperature=SAMPLE_TEMPERATURE, sample=i) for i in range(SAMPLES)]
    return vote(t, answers)


def vote(t: Trajectory, answers: list[Diagnosis]) -> Diagnosis:
    from collections import Counter

    usable = [a for a in answers if a.critical_step is not None and a.category]
    if not usable:
        d = answers[0]
        d.abstain, d.abstain_reason = True, "no usable answer in any sample"
        return d
    steps = Counter(a.critical_step for a in usable)
    top = max(steps.values())
    step = min(s for s, n in steps.items() if n == top)  # tie -> earliest step
    cats = Counter(a.category for a in usable if a.critical_step == step)
    category = cats.most_common(1)[0][0]
    agree = [a for a in usable if a.critical_step == step and a.category == category]
    best = next((a for a in agree if any(e["valid"] and e["step"] == step for e in a.evidence)), agree[0])
    d = Diagnosis(**{**best.__dict__})
    d.confidence = round(len(agree) / len(answers), 3)
    reasons = []
    if len(agree) < MIN_AGREE:
        reasons.append(f"only {len(agree)}/{len(answers)} samples agree on step {step} + {category}")
    if not any(e["valid"] and e["step"] == step for a in agree for e in a.evidence):
        reasons.append("no verbatim evidence found at the critical step")
    if category == "Inconclusive":
        reasons.append("category inconclusive")
    d.abstain, d.abstain_reason = bool(reasons), "; ".join(reasons)
    d.summary = best.summary
    d.error = "; ".join(sorted({a.error for a in answers if a.error}))
    d.samples = [{"critical_step": a.critical_step, "category": a.category, "failed_agent": a.failed_agent,
                  "self_confidence": a.confidence} for a in answers]
    return d


def _ask(t: Trajectory, arm: str, policy: str, model: str, cache_dir: Path, run_tag: str,
         db_diff=None, use_reference=False, temperature: float = 0.0, sample: int = 0) -> Diagnosis:
    """One model call, reusing a cached answer for the identical prompt."""
    prompt = build_prompt(t, arm, policy, db_diff, use_reference)
    key = hashlib.sha256(f"{model}\n{temperature}\n{sample}\n{prompt}".encode()).hexdigest()[:16]
    cache = cache_dir / f"{t.traj_id}.json"
    if cache.exists():
        saved = json.loads(cache.read_text())
        if saved.get("prompt_hash") == key and not saved.get("api_error"):
            parsed, note = parse_reply(saved.get("raw", "")) if "raw" in saved else (saved["parsed"], "")
            return _finish(to_diagnosis(t, arm, parsed, model), parsed, note)
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        raw, usage = call_model(prompt, model, run_tag, temperature)
    except Exception as exc:  # noqa: BLE001 - quota stops propagate; others are recorded
        from runner.gateway import DailyQuotaExhausted
        if isinstance(exc, DailyQuotaExhausted):
            raise
        cache.write_text(json.dumps({"prompt_hash": key, "api_error": f"{type(exc).__name__}: {exc}"[:2000]}))
        d = to_diagnosis(t, arm, {}, model)
        d.error, d.abstain, d.abstain_reason = f"API error: {type(exc).__name__}", True, "API error"
        return d
    parsed, note = parse_reply(raw)
    cache.write_text(json.dumps({"prompt_hash": key, "prompt_version": PROMPT_VERSION, "arm": arm,
                                 "raw": raw, "parsed": parsed, "usage": usage}, indent=1, ensure_ascii=False))
    return _finish(to_diagnosis(t, arm, parsed, model), parsed, note)


def _finish(d: Diagnosis, parsed: dict, note: str) -> Diagnosis:
    if not parsed:
        d.error, d.abstain, d.abstain_reason = note, True, note
    elif note:
        d.error = note  # recorded, not fatal
    return d


# --- CLI: diagnose our own failed runs ------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--one-per-task", action="store_true",
                    help="diagnose only the first unexplained failed trial of each task (saves quota)")
    args = ap.parse_args(argv)
    import yaml
    from loguru import logger

    from runner.gateway import DailyQuotaExhausted
    from triage.trajectory import from_tau2

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    model = yaml.safe_load((ROOT / "config.yaml").read_text())["models"]["investigator"]
    triage = json.loads((ROOT / "results" / "triage" / f"{args.tag}.json").read_text())
    # Only failures layers 1-2 cannot pin to a step (no false success, no violation).
    todo = [r for r in triage if not r["tau2_success"] and not r["false_success"]
            and not any(f["severity"] == "violation" for f in r["findings"])]
    if args.one_per_task:
        seen, first = set(), []
        for r in sorted(todo, key=lambda r: (int(r["task_id"]), r["trial"])):
            if r["task_id"] not in seen:
                seen.add(r["task_id"])
                first.append(r)
        todo = first
    todo = todo[: args.limit] if args.limit else todo
    out_path = ROOT / "results" / "diagnoses" / f"{args.tag}.json"
    results = {}
    try:
        for i, r in enumerate(todo, 1):
            t = from_tau2(ROOT / r["file"])
            policy = json.loads((ROOT / r["file"]).read_text()).get("policy") or ""
            d = investigate(t, "C", policy, model, ROOT / "results" / "investigator" / f"tau2_{args.tag}",
                            run_tag=f"investigator_{args.tag}", db_diff=r["db_diff"], use_reference=True)
            results[t.traj_id] = {"file": r["file"], **asdict(d)}
            print(f"[{i}/{len(todo)}] {t.traj_id}: step={d.critical_step} {d.category} "
                  f"conf={d.confidence} abstain={d.abstain}", flush=True)
    except DailyQuotaExhausted as exc:
        print(f"Stopped: {exc}. Re-run the same command tomorrow to continue.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"tag": args.tag, "selection": "one unexplained failed trial per task"
                                    if args.one_per_task else "all unexplained failed runs",
                                    "candidates": len(todo), "diagnosed": len(results),
                                    "diagnoses": results}, indent=1, ensure_ascii=False))
    print(f"{len(results)}/{len(todo)} diagnosed -> {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
