"""Human check of the false-success detector.

    python -m eval.fs_review --prepare    # add the extra case, draw sample B, write the precision file
    python -m eval.fs_review --apply      # precision of every claim rule from the human labels

Sample A (results/false_success_review.json): 20 runs drawn at random (seed in
eval/eval_verify.py) from the v1 false successes under claim rule v1, frozen,
plus one extra case chosen by the user (bug_dropitem task 2 trial 1, "extra").
Rule v3 was designed AFTER reading sample A, so its precision on A is biased.

Sample B (results/false_success_review_v3.json): drawn at random (SEED_B) from
the v1 false successes under rule v3, excluding sample A. It played no part in
designing any rule, so it is the honest test of v3.

Labels are written only by the person reviewing (local web page or by hand):
correct = really a false success, incorrect = the rule was wrong, unsure.
An AI assistant's suggestions, if any, sit in "ai_suggestion" and are never
counted as human labels; "ai_assisted" figures are reported separately.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SAMPLES = {"A": ROOT / "results" / "false_success_review.json",
           "B": ROOT / "results" / "false_success_review_v3.json"}
REVIEW = SAMPLES["A"]
OUT = ROOT / "results" / "false_success_precision.json"
EXTRA = "results/runs/bug_dropitem/task_2__trial_1.json"
LABELS = ("correct", "incorrect", "unsure")
RULE_DIRS = {"v1": "triage_rule1", "v2": "triage_rule2", "v3": "triage"}
SEED_B, SIZE_B = 2027, 20


def flagged(rule_dir: str) -> set[str]:
    out = set()
    for f in (ROOT / "results" / rule_dir).glob("*.json"):
        out |= {r["file"] for r in json.loads(f.read_text()) if r["false_success"]}
    return out


def claim_statuses(rule_dir: str, file: str) -> list[dict]:
    tag = Path(file).parent.name
    path = ROOT / "results" / rule_dir / f"{tag}.json"
    if not path.exists():
        return []
    for r in json.loads(path.read_text()):
        if r["file"] == file:
            return [{"step": c["step"], "status": c["status"], "sentence": c["sentence"], "reason": c["reason"]}
                    for c in r["claims"] if c["status"] != "verified"]
    return []


def _goal(task_id: str) -> str:
    from triage.verify import _task
    return _task(str(task_id)).user_scenario.instructions.reason_for_call


def prepare() -> None:
    items = json.loads(SAMPLES["A"].read_text())
    if not any(it["file"] == EXTRA for it in items):
        r = next(x for x in json.loads((ROOT / "results/triage_rule1/bug_dropitem.json").read_text()) if x["file"] == EXTRA)
        items.append({"case": len(items) + 1, "file": EXTRA, "task_id": r["task_id"], "trial": r["trial"],
                      "user_goal": _goal(r["task_id"]), "human_label": None, "human_note": "", "extra": True})
        SAMPLES["A"].write_text(json.dumps(items, indent=1, ensure_ascii=False))
    if not SAMPLES["B"].exists():                      # drawn once, then frozen
        taken = {it["file"] for it in items}
        pool = sorted(r["file"] for r in json.loads((ROOT / "results/triage/v1.json").read_text())
                      if r["false_success"] and r["file"] not in taken)
        pick = sorted(random.Random(SEED_B).sample(pool, min(SIZE_B, len(pool))),
                      key=lambda f: (int(Path(f).stem.split("_")[1]), f))
        rows = []
        for i, f in enumerate(pick, 1):
            tid = Path(f).stem.split("_")[1]
            rows.append({"case": i, "file": f, "task_id": tid, "trial": int(Path(f).stem.split("_")[-1]),
                         "user_goal": _goal(tid), "human_label": None, "human_note": ""})
        SAMPLES["B"].write_text(json.dumps({"seed": SEED_B, "pool_size": len(pool), "drawn_from":
                                            "v1 runs flagged as false success under rule v3, excluding sample A",
                                            "items": rows}, indent=1, ensure_ascii=False))


def _items(sample: str) -> list[dict]:
    data = json.loads(SAMPLES[sample].read_text()) if SAMPLES[sample].exists() else []
    return data["items"] if isinstance(data, dict) else data


def _save(sample: str, items: list[dict]) -> None:
    path = SAMPLES[sample]
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data["items"] = items
    else:
        data = items
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))


def set_label(case: int, label: str | None, note: str, sample: str = "A") -> dict:
    if label not in LABELS + (None,):
        raise ValueError("label must be correct / incorrect / unsure")
    if sample not in SAMPLES:
        raise ValueError("sample must be A or B")
    items = _items(sample)
    it = next((x for x in items if x["case"] == case), None)
    if it is None:
        raise ValueError(f"no case {case} in sample {sample}")
    it["human_label"], it["human_note"] = label, note[:500]
    _save(sample, items)
    return apply()


def _precision(sub: list[dict], key: str = "human_label") -> dict:
    labels = [(it.get(key) or {}).get("label") if key == "ai_suggestion" else it.get(key) for it in sub]
    c = Counter(labels)
    done = c["correct"] + c["incorrect"]
    return {"cases": len(sub), "correct": c["correct"], "incorrect": c["incorrect"], "unsure": c["unsure"],
            "unlabelled": c[None], "precision": round(c["correct"] / done, 4) if done else None}


def apply() -> dict:
    flags = {v: flagged(d) for v, d in RULE_DIRS.items()}
    a = [it for it in _items("A") if not it.get("extra")]
    b = _items("B")
    out = {
        "what": "human check of the false-success detector",
        "sources": [str(p.relative_to(ROOT)) for p in SAMPLES.values()] + [f"results/{d}/" for d in RULE_DIRS.values()],
        "sample_A": {
            "note": "drawn under rule v1; rule v3 was designed after reading it, so v3 on A is biased",
            **{f"rule_{v}": _precision([it for it in a if it["file"] in flags[v]]) for v in RULE_DIRS},
            "ai_assisted_rule_v1": {**_precision(a, "ai_suggestion"),
                                    "note": "labels suggested by an AI assistant, NOT human labels"},
        },
        "sample_B": {"note": "drawn under rule v3 from runs no rule was tuned on: the honest test of v3",
                     "rule_v3": _precision(b)},
        "extra_cases": [{"file": it["file"], "human_label": it.get("human_label"),
                         **{f"flagged_{v}": it["file"] in flags[v] for v in RULE_DIRS}}
                        for it in _items("A") if it.get("extra")],
        "complete": all(it.get("human_label") for it in _items("A") + b),
    }
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


def web_data() -> dict:
    """What the review page shows: each case under rule v1 and v3, plus any AI suggestion (labelled as such)."""
    flags = {v: flagged(d) for v, d in RULE_DIRS.items()}

    def rows(sample):
        return [{**{k: it.get(k) for k in ("case", "file", "task_id", "trial", "user_goal", "human_label",
                                          "human_note", "extra", "ai_suggestion")},
                 "claims_v1": claim_statuses("triage_rule1", it["file"]),
                 "claims_v3": claim_statuses("triage", it["file"]),
                 **{f"flagged_{v}": it["file"] in flags[v] for v in RULE_DIRS}} for it in _items(sample)]
    return {"A": rows("A"), "B": rows("B")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if a.prepare:
        prepare()
    print(json.dumps(apply(), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
