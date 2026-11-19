"""Compare two runs of the investigator on the same trajectories.

    python -m eval.diagnosis_stability       # -> results/diagnoses/stability_v1.json

results/diagnoses/v1_prev.json was made before the transfer_to_human rule was
added; results/diagnoses/v1.json after it. The only input that changed is one
extra 'info' rule finding in the prompt (plus sampling randomness, T=0.7), so
the differences show how stable the investigator's verdicts are.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    old = json.loads((ROOT / "results/diagnoses/v1_prev.json").read_text())["diagnoses"]
    new = json.loads((ROOT / "results/diagnoses/v1.json").read_text())["diagnoses"]
    both = sorted(set(old) & set(new))
    usable = [k for k in both if not old[k].get("error") and not new[k].get("error")]
    answered_both = [k for k in usable if not old[k]["abstain"] and not new[k]["abstain"]]
    out = {
        "what": "same trajectories, investigator run twice (prompt differed only by one extra info finding)",
        "files": ["results/diagnoses/v1_prev.json", "results/diagnoses/v1.json"],
        "compared": len(both),
        "without_parse_errors_in_either": len(usable),
        "category_same": sum(old[k]["category"] == new[k]["category"] for k in usable),
        "critical_step_same": sum(old[k]["critical_step"] == new[k]["critical_step"] for k in usable),
        "abstain_decision_same": sum(old[k]["abstain"] == new[k]["abstain"] for k in usable),
        "all_three_same": sum((old[k]["category"], old[k]["critical_step"], old[k]["abstain"]) ==
                              (new[k]["category"], new[k]["critical_step"], new[k]["abstain"]) for k in usable),
        "answered_in_both": len(answered_both),
        "answered_in_both_same_category_and_step": sum(
            (old[k]["category"], old[k]["critical_step"]) == (new[k]["category"], new[k]["critical_step"])
            for k in answered_both),
    }
    path = ROOT / "results/diagnoses/stability_v1.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
