"""Tests for the investigator's deterministic parts. No model calls."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.eval_investigator import score, wilson  # noqa: E402
from triage.investigator import check_evidence, parse_reply, to_diagnosis, vote  # noqa: E402
from triage.trajectory import Trajectory, from_agentrx  # noqa: E402

TRAJ = Trajectory(
    source="agentrx", traj_id="x", task_id="x", steps=[1, 2, 3, 4],
    messages=[{"role": "system", "content": "policy"},
              {"role": "user", "content": "How many t-shirts are available?"},
              {"role": "assistant", "content": "", "tool_calls": [
                  {"id": "a", "name": "get_product_details", "arguments": {"product_id": "1"}}]},
              {"role": "assistant", "content": "There are 11 available T-shirt options."}])


def test_parse_reply_repairs_mismatched_brackets_only_outside_strings():
    parsed, note = parse_reply('{"evidence": [{"quote": "a } b ]"} }, "x": 1}')
    assert parsed == {"evidence": [{"quote": "a } b ]"}], "x": 1} and note
    assert parse_reply("not json")[0] == {}


def test_evidence_must_be_verbatim_in_the_cited_step():
    ev = check_evidence(TRAJ, [{"step": 4, "quote": "there are 11 available t-shirt options"},
                               {"step": 2, "quote": "There are 11 available"},
                               {"step": 3, "quote": "get_product_details"}])
    assert [e["valid"] for e in ev] == [True, False, True]


def _answer(step, category, quote_ok=True):
    parsed = {"critical_step": step, "category": category, "failed_agent": "assistant",
              "evidence": [{"step": step, "quote": "11 available T-shirt" if quote_ok else "made up"}],
              "confidence": 0.9}
    return to_diagnosis(TRAJ, "C", parsed, "m")


def test_vote_requires_agreement_and_evidence():
    cat = "Misinterpretation of Tool Output"
    d = vote(TRAJ, [_answer(4, cat), _answer(4, cat), _answer(4, cat)])
    assert not d.abstain and d.critical_step == 4 and d.confidence == 1.0
    d = vote(TRAJ, [_answer(4, cat), _answer(4, cat), _answer(3, "Invalid Invocation")])
    assert d.abstain and "2/3" in d.abstain_reason  # MIN_AGREE = 3
    d = vote(TRAJ, [_answer(4, cat, quote_ok=False)] * 3)
    assert d.abstain and "evidence" in d.abstain_reason


def test_category_names_are_normalised():
    d = to_diagnosis(TRAJ, "A", {"category": "intent plan misalignment"}, "m")
    assert d.category == "Intent-Plan Misalignment"


def test_score_counts_abstentions_as_misses_in_all_cases():
    rows = [{"abstain": False, "confidence": 0.9, "step_exact": True, "step_within_1": True,
             "category": True, "step_and_category": True, "failed_agent": True, "step_any_failure": True},
            {"abstain": True, "confidence": 0.3, "step_exact": True, "step_within_1": True,
             "category": True, "step_and_category": True, "failed_agent": True, "step_any_failure": True}]
    m = score(rows)
    assert m["all_cases"]["step_exact"]["n"] == 1 and m["answered_cases"]["step_exact"]["of"] == 1
    assert wilson(0, 0) == [None, None] and wilson(5, 10)[0] < 0.5 < wilson(5, 10)[1]


def test_agentrx_conversion_keeps_annotation_step_numbers():
    item = {"task_id": 9, "reward": 0.0, "info": {"task": {"actions": [], "instruction": "x"}},
            "traj": [{"role": "system", "content": "p", "index": 1},
                     {"role": "assistant", "content": None, "index": 2, "tool_calls": [
                         {"id": "c", "type": "function",
                          "function": {"name": "get_order_details", "arguments": '{"order_id": "#W1"}'}}]},
                     {"role": "tool", "content": "Error: order not found", "tool_call_id": "c", "index": 3}]}
    t = from_agentrx(item)
    assert t.steps == [1, 2, 3] and t.messages[2]["error"] is True
    assert t.messages[1]["tool_calls"][0]["arguments"] == {"order_id": "#W1"}
