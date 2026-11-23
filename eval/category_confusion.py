"""Investigator category vs AgentRx reference label, case by case (no model calls).

    python -m eval.category_confusion     # -> results/category_confusion.json

For every test-split case of each arm: the reference category (AgentRx root
cause), the model's category, and why they differ:
  same_step_other_category  model picked the annotated root-cause step but named another category
  other_annotated_failure   model picked a step AgentRx also annotated as a failure (not the root
                            cause) - and its category matches that failure's label
  other_step                model picked a step AgentRx did not annotate
  abstained                 no answer
The taxonomy is the same on both sides (AgentRx's 10 categories); the only
mapping is spelling (e.g. "Instruction Adherence Failure" -> "Instruction/Plan
Adherence Failure"), applied when the reference is loaded.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from triage.investigator import _category  # noqa: E402

FILES = {"v3": "results/eval_investigator.json", "v4": "results/eval_investigator_v4.json"}


def main() -> int:
    gt = {str(t["trajectory_id"]): t for t in json.loads(
        (ROOT / "vendor/agentrx/data/ground_truth/tau_ground_truth.json").read_text())}
    out = {"sources": list(FILES.values()) + ["vendor/agentrx/data/ground_truth/tau_ground_truth.json"], "arms": {}}
    for version, path in FILES.items():
        e = json.loads((ROOT / path).read_text())
        for arm, rows in e["rows"].items():
            cases, reasons, pairs = [], Counter(), Counter()
            for r in rows:
                truth, d = r["truth"], r["diagnosis"]
                others = {f["step_number"]: _category(f["failure_category"])
                          for f in gt[r["traj_id"]]["failures"]}
                if r["abstain"]:
                    why = "abstained"
                elif r["category"]:
                    why = "match"
                elif d["critical_step"] == truth["critical_step"]:
                    why = "same_step_other_category"
                elif d["critical_step"] in others:
                    why = ("other_annotated_failure" if others[d["critical_step"]] == d["category"]
                           else "other_annotated_failure_other_category")
                else:
                    why = "other_step"
                reasons[why] += 1
                if not r["abstain"]:
                    pairs[(truth["category"], d["category"])] += 1
                cases.append({"traj_id": r["traj_id"], "truth_step": truth["critical_step"],
                              "truth_category": truth["category"], "model_step": d["critical_step"],
                              "model_category": d["category"], "abstain": r["abstain"], "why": why})
            out["arms"][f"{version}_{arm}"] = {
                "reasons": dict(reasons),
                "confusion": [{"truth": t, "model": m, "n": n} for (t, m), n in pairs.most_common()],
                "cases": cases}
    (ROOT / "results/category_confusion.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    for k, v in out["arms"].items():
        print(k, v["reasons"])
    print("\nv3 arm C, answered cases (truth -> model):")
    for c in out["arms"]["v3_C"]["confusion"]:
        print(f"  {c['n']}  {c['truth']}  ->  {c['model']}")
    by_truth = defaultdict(Counter)
    for k in ("v3_A", "v3_B", "v3_C"):
        for c in out["arms"][k]["cases"]:
            if not c["abstain"]:
                by_truth[c["truth_category"]][c["why"] == "match"] += 1
    print("\nA+B+C answered, by reference category (right/answered):")
    for t, c in sorted(by_truth.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"  {c[True]}/{c[True] + c[False]}  {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
