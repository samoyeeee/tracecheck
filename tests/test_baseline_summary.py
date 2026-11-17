"""Tests for pass^k and the baseline summary."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.baseline_summary import pass_hat_k, summarize  # noqa: E402


def run(task, trial, ok, db=True, nl=None, term="user_stop"):
    return {"task_id": task, "trial": trial, "success": ok, "reward": 1.0 if ok else 0.0,
            "db_match": db, "nl_all_met": nl, "termination_reason": term}


def test_pass_hat_k_matches_definition():
    assert pass_hat_k(4, 4, 4) == 1.0
    assert pass_hat_k(3, 4, 4) == 0.0
    assert pass_hat_k(2, 4, 1) == 0.5
    assert abs(pass_hat_k(3, 4, 2) - 0.5) < 1e-9  # C(3,2)/C(4,2) = 3/6


def test_summary_counts_and_reasons():
    runs = [run("a", t, True) for t in range(4)]                       # 4/4
    runs += [run("b", 0, True), run("b", 1, True),
             run("b", 2, False, db=False), run("b", 3, False, db=True, nl=False)]  # 2/4
    runs += [run("c", 0, False, db=None, term="max_steps")]             # incomplete task
    s = summarize(runs, k=4, expected_tasks=3)
    assert s["tasks_with_k_trials"] == 2 and s["complete"] is False
    assert s["pass^1"] == 0.75 and s["pass^4"] == 0.5   # only complete tasks count
    assert s["failed_runs"] == 3
    assert s["failed_run_reasons"] == {"db_mismatch": 1, "db_ok_but_nl_assertion_failed": 1,
                                       "terminated: max_steps": 1}
    assert s["tasks_by_successes_out_of_k"] == {"0": 0, "1": 0, "2": 1, "3": 0, "4": 1}


def test_regression_statistics():
    import random
    from eval.eval_regression import holm, sign_flip_p
    rng = random.Random(0)
    assert sign_flip_p([0, 0, 0], rng) == 1.0
    assert sign_flip_p([-1.0] * 12, rng) < 0.01          # consistent drop is significant
    assert sign_flip_p([1, -1] * 6, rng) > 0.5            # balanced changes are not
    adj = holm({"a": 0.01, "b": 0.02, "c": 0.5})
    assert adj == {"a": 0.03, "b": 0.04, "c": 0.5}
