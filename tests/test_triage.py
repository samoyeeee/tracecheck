"""Tests for layer 1 (claims) and layer 2 (rules) on small synthetic trajectories."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from triage.rules import (  # noqa: E402
    check_authentication, check_confirmation, check_one_call_at_a_time,
    check_refund_and_payment, check_repeated_calls, run_rules,
)
from triage.verify import check_claim, classify_sentence, db_diff, extract_claims, tool_calls  # noqa: E402


def A(text="", calls=()):
    return {"role": "assistant", "content": text,
            "tool_calls": [{"id": f"c{n}_{i}", "name": n, "arguments": a} for i, (n, a) in enumerate(calls)] or None}


def T(call_id, content, error=False):
    return {"role": "tool", "id": call_id, "content": content, "error": error}


def U(text):
    return {"role": "user", "content": text}


ORDER = '{"order_id": "#W0000001", "user_id": "u1", "status": "pending", ' \
        '"payment_history": [{"transaction_type": "payment", "payment_method_id": "credit_card_1"}]}'


def convo(write=("cancel_pending_order", {"order_id": "#W0000001", "reason": "no longer needed"}),
          confirm="Yes, please cancel it.", ok=True, claim="Your order #W0000001 has been successfully cancelled."):
    return [
        A("Hi! How can I help?"), U("Cancel my order #W0000001. Email a@b.c"),
        A("", [("find_user_id_by_email", {"email": "a@b.c"})]), T("cfind_user_id_by_email_0", "u1"),
        A("", [("get_order_details", {"order_id": "#W0000001"})]), T("cget_order_details_0", ORDER),
        A("I will cancel order #W0000001 (reason: no longer needed). Confirm?"), U(confirm),
        A("", [write]), T(f"c{write[0]}_0", "{}" if ok else "Error: nope", error=not ok),
        A(claim),
    ]


# --- claim detection ---------------------------------------------------------

def test_claim_sentences():
    assert classify_sentence("Your order #W0000001 has been successfully cancelled.") == "cancel"
    assert classify_sentence("✅ Exchange processed for order #W0000001") == "exchange"
    assert classify_sentence("Your order modification has been successfully completed.") == "modify_items"
    assert classify_sentence("I've successfully processed all your requests.") == "all_requests"
    # not claims: future, question, negation, non-write steps, refunds, availability
    for s in ["Your order will be cancelled once you confirm.",
              "Should I cancel the order?",
              "You won't be able to cancel this order since it has been modified.",
              "I've successfully authenticated your identity.",
              "The refund has been processed to your gift card.",
              "- Status: ✅ Available"]:
        assert classify_sentence(s) is None, s


def test_extract_claims_takes_ids_from_the_sentence_only():
    msgs = [A("Order #W0000002 summary:\nYour exchange has been successfully processed.")]
    (claim,) = extract_claims(msgs)
    assert claim["action"] == "exchange" and claim["entity_ids"] == []


def _dbs(initial, final, expected):
    return {"initial": {"orders": initial, "users": {}}, "final": {"orders": final, "users": {}},
            "expected": {"orders": expected, "users": {}}}


def test_claim_statuses():
    pending = {"#W0000001": {"status": "pending"}}
    cancelled = {"#W0000001": {"status": "cancelled", "cancel_reason": "no longer needed"}}
    wrong = {"#W0000001": {"status": "cancelled", "cancel_reason": "ordered by mistake"}}

    msgs = convo()
    claim = extract_claims(msgs)[-1]
    calls = tool_calls(msgs)
    assert check_claim(claim, calls, _dbs(pending, cancelled, cancelled)).status == "verified"
    assert check_claim(claim, calls, _dbs(pending, wrong, cancelled)).status == "executed_but_differs"
    # the task never wanted this order touched: true claim, wrong decision
    assert check_claim(claim, calls, _dbs(pending, cancelled, pending)).status == "unrequested_change"

    # the task wanted the items changed, the agent cancelled instead: claim true, action wrong
    modified = {"#W0000001": {"status": "pending (item modified)", "items": [2]}}
    assert check_claim(claim, calls, _dbs({"#W0000001": {"status": "pending", "items": [1]}},
                                          cancelled, modified)).status == "wrong_action"

    failed = convo(ok=False)
    status = check_claim(extract_claims(failed)[-1], tool_calls(failed), _dbs(pending, pending, cancelled))
    assert status.status == "not_executed"

    ghost = dict(extract_claims(msgs)[-1], entity_ids=["#W9999999"])
    assert check_claim(ghost, calls, _dbs(pending, cancelled, cancelled)).status == "unverifiable"


def test_db_diff_reports_field_paths():
    d = db_diff({"orders": {"#W1": {"status": "pending", "items": [1, 2]}}},
                {"orders": {"#W1": {"status": "cancelled", "items": [1, 3]}}})
    assert d[0]["id"] == "#W1"
    assert {f["path"] for f in d[0]["fields"]} == {"status", "items[1]"}


# --- rules -------------------------------------------------------------------

def test_confirmation_rule():
    msgs = convo()
    assert check_confirmation(msgs, tool_calls(msgs)) == []
    msgs = convo(confirm="Hmm, what about my other order")
    (f,) = check_confirmation(msgs, tool_calls(msgs))
    assert f.severity == "violation" and f.step == 8 and f.evidence[0].step == 7
    msgs = convo(confirm="ok")
    (f,) = check_confirmation(msgs, tool_calls(msgs))
    assert f.knowledge == "needs_verification"


def test_authentication_rule():
    msgs = [A("", [("get_order_details", {"order_id": "#W0000001"})]), T("cget_order_details_0", ORDER)]
    (f,) = check_authentication(msgs, tool_calls(msgs))
    assert f.rule_id == "policy_authenticate_first" and f.policy_quote
    assert check_authentication(convo(), tool_calls(convo())) == []


def test_repeated_and_one_action_rules():
    call = ("get_order_details", {"order_id": "#W0000001"})
    msgs = [A("", [call]), T("cget_order_details_0", ORDER), A("", [call]), T("cget_order_details_0", ORDER)]
    assert check_repeated_calls(msgs, tool_calls(msgs))[0].rule_id == "repeated_call"
    msgs = [A("Let me look that up.", [call])]
    assert check_one_call_at_a_time(msgs, tool_calls(msgs))[0].severity == "warning"


def test_refund_rule_downgrades_rejected_calls():
    ret = ("return_delivered_order_items", {"order_id": "#W0000001", "item_ids": ["1"],
                                            "payment_method_id": "paypal_1"})
    msgs = convo(write=ret, ok=True)
    (f,) = check_refund_and_payment(msgs, tool_calls(msgs))
    assert f.severity == "violation"
    msgs = convo(write=ret, ok=False)
    (f,) = check_refund_and_payment(msgs, tool_calls(msgs))
    assert f.severity == "warning" and "rejected" in f.message


def test_run_rules_flags_abnormal_termination():
    sim = {"termination_reason": "max_steps", "messages": convo()}
    assert any(f.rule_id == "abnormal_termination" for f in run_rules(sim))


def test_rule_v2_partial_claim_that_discloses_the_failure_is_not_false_success():
    from pathlib import Path
    from triage.verify import verify_run
    root = Path(__file__).resolve().parent.parent
    r = verify_run(root / "results/runs/bug_dropitem/task_2__trial_1.json", "t", root)
    assert not r.false_success
    assert {c.status for c in r.claims} == {"partial_disclosed"}
