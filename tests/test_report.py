"""Page-1 report builder: deterministic parts, no model calls."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from triage import report as R  # noqa: E402

DB = {"products": {"p": {"name": "Smart Watch", "variants": {"9": {"item_id": "9", "options": {"color": "gold"}}}},
                   "q": {"name": "Headphones", "variants": {"4": {"item_id": "4", "options": {}}}}},
      "users": {"u": {"payment_methods": {"credit_card_1": {"id": "credit_card_1", "source": "credit_card", "last_four": "2478"}}}}}


def _dbs(final_items):
    order = lambda items, status: {"orders": {"#W1": {"status": status, "return_items": items}}, **DB}  # noqa: E731
    return {"initial": order(None, "delivered"), "final": order(final_items, "return requested"),
            "expected": order(["4", "9"], "return requested")}


def test_comparison_marks_missing_items_and_unexplained_rows():
    names = R.Names(DB)
    calls = [{"name": "return_delivered_order_items", "ok": True, "args": {"order_id": "#W1"}}]
    rows = {r["field"]: r for r in R.comparison(_dbs(["4"]), calls, names)}
    assert rows["status"]["status"] == "ok"
    assert rows["return_items"]["status"] == "bad" and rows["return_items"]["missing_short"] == ["Smart Watch"]
    # same difference but the agent never wrote the order -> cause unknown -> "check"
    assert {r["field"]: r for r in R.comparison(_dbs(["4"]), [], names)}["return_items"]["status"] == "check"


def test_verdict_and_facts_do_not_repeat_and_name_the_difference():
    names = R.Names(DB)
    rows = R.comparison(_dbs(["4"]), [{"name": "return_delivered_order_items", "ok": True, "args": {"order_id": "#W1"}}], names)
    claim = {"step": 5, "action": "return", "status": "executed_but_differs", "sentence": "done"}
    rep = {"tau2_success": False, "false_success": True, "claims": [claim, dict(claim)],
           "findings": [{"rule_id": "claim_executed_but_differs", "severity": "violation", "step": 5, "message": "x"}]}
    v = R.verdict(rep, rows, None)
    assert v["labels"]["kind"]["text"] == "假成功" and "少了 Smart Watch" in v["sentence"]
    facts = R.facts(rep)
    assert len(facts) == 1 and len(facts[0]["items"]) == 1          # merged, no repeat of the claim_* finding


def test_tool_summaries_are_plain_chinese():
    names = R.Names(DB)
    s = R.call_summary("return_delivered_order_items", {"order_id": "#W1", "item_ids": ["4", "9"],
                                                        "payment_method_id": "credit_card_1"}, names)
    assert s == "订单 #W1，2 件商品（Headphones、Smart Watch），退款到 信用卡 ····2478"
    assert R.result_summary("return_delivered_order_items", False, "Error: Non-delivered order cannot be returned", names) \
        == "报错：订单不是“已送达”状态，不能退货"
