"""Human check of the false-success detector.

    python -m eval.fs_review --prepare    # add the extra case, write web data
    python -m eval.fs_review --apply      # precision of claim rule v1 and v2 from the labels

The sample in results/false_success_review.json was drawn at random (seed in
eval/eval_verify.py) from the v1 false successes under claim rule v1, then
frozen. One extra case chosen by the user (bug_dropitem task 2 trial 1) is
added with "extra": true; it is reported on its own and never counted in the
precision of the random sample.

Labels (written only by the person reviewing, through the local web page or by
hand): correct = really a false success, incorrect = the rule was wrong,
unsure. Precision = correct / (correct + incorrect).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REVIEW = ROOT / "results" / "false_success_review.json"
OUT = ROOT / "results" / "false_success_precision.json"
EXTRA = "results/runs/bug_dropitem/task_2__trial_1.json"
LABELS = ("correct", "incorrect", "unsure")


def flagged(rule_dir: str) -> set[str]:
    """Files flagged as false success by a rule version (results/triage = current = v2)."""
    out = set()
    for f in (ROOT / "results" / rule_dir).glob("*.json"):
        out |= {r["file"] for r in json.loads(f.read_text()) if r["false_success"]}
    return out


def claim_statuses(rule_dir: str, file: str) -> list[dict]:
    tag = Path(file).parent.name
    for r in json.loads((ROOT / "results" / rule_dir / f"{tag}.json").read_text()):
        if r["file"] == file:
            return [{"step": c["step"], "status": c["status"], "sentence": c["sentence"]} for c in r["claims"]
                    if c["status"] != "verified"]
    return []


def prepare() -> list[dict]:
    items = json.loads(REVIEW.read_text())
    if not any(it["file"] == EXTRA for it in items):
        from triage.verify import _task
        tag_runs = json.loads((ROOT / "results/triage_rule1/bug_dropitem.json").read_text())
        r = next(x for x in tag_runs if x["file"] == EXTRA)
        items.append({"case": len(items) + 1, "file": EXTRA, "task_id": r["task_id"], "trial": r["trial"],
                      "user_goal": _task(r["task_id"]).user_scenario.instructions.reason_for_call,
                      "claims": [c for c in r["claims"] if c["status"] != "verified"],
                      "human_label": None, "human_note": "", "extra": True})
        REVIEW.write_text(json.dumps(items, indent=1, ensure_ascii=False))
    return items


def set_label(case: int, label: str | None, note: str) -> dict:
    if label not in LABELS + (None,):
        raise ValueError("label must be correct / incorrect / unsure")
    items = json.loads(REVIEW.read_text())
    it = next((x for x in items if x["case"] == case), None)
    if it is None:
        raise ValueError(f"no case {case}")
    it["human_label"], it["human_note"] = label, note[:500]
    REVIEW.write_text(json.dumps(items, indent=1, ensure_ascii=False))
    return apply()


def apply() -> dict:
    items = json.loads(REVIEW.read_text())
    sample = [it for it in items if not it.get("extra")]
    v1, v2 = flagged("triage_rule1"), flagged("triage")

    def precision(sub):
        c = Counter(it.get("human_label") for it in sub)
        done = c["correct"] + c["incorrect"]
        return {"cases": len(sub), "correct": c["correct"], "incorrect": c["incorrect"], "unsure": c["unsure"],
                "unlabelled": c[None], "precision": round(c["correct"] / done, 4) if done else None}

    still = [it for it in sample if it["file"] in v2]
    dropped = [it for it in sample if it["file"] not in v2]
    out = {
        "what": "human check of the false-success detector on the frozen random sample",
        "sources": ["results/false_success_review.json", "results/triage_rule1/", "results/triage/"],
        "rule_v1": precision([it for it in sample if it["file"] in v1]),
        "rule_v2": precision(still),
        "dropped_by_v2": {**precision(dropped), "files": [it["file"] for it in dropped]},
        "extra_cases": [{"file": it["file"], "human_label": it.get("human_label"), "human_note": it.get("human_note"),
                         "flagged_v1": it["file"] in v1, "flagged_v2": it["file"] in v2}
                        for it in items if it.get("extra")],
        "complete": all(it.get("human_label") for it in items),
    }
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


def web_data() -> list[dict]:
    """What the review page shows: claims under both rules, nothing else invented."""
    from triage.verify import _task  # noqa: F401
    rows = []
    for it in json.loads(REVIEW.read_text()):
        rows.append({**{k: it.get(k) for k in ("case", "file", "task_id", "trial", "user_goal", "human_label",
                                              "human_note", "extra")},
                     "claims_v1": claim_statuses("triage_rule1", it["file"]),
                     "claims_v2": claim_statuses("triage", it["file"]),
                     "flagged_v1": it["file"] in flagged("triage_rule1"),
                     "flagged_v2": it["file"] in flagged("triage")})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if a.prepare:
        print(len(prepare()), "cases in", REVIEW.relative_to(ROOT))
    print(json.dumps(apply(), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
