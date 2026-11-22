"""Build the single-run diagnosis report the web page shows (page 1).

Everything here is deterministic: it only re-words what layers 1-3 found, in
Chinese, and lays it out conclusion-first:

  verdict      one plain sentence + three labels (task result, failure type, AI location)
  comparison   expected vs actual database state, only task-relevant fields
  chain        causal chain (from the investigator, v4 prompt)
  facts / ai / checks   the three columns; one entry per step, no repeats
  timeline     messages + one-line tool-call summaries (raw JSON kept for "expand")

Model calls happen elsewhere (triage.investigator, triage.translate).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from triage.verify import WRITE_TOOLS, tool_calls

# --- wording -----------------------------------------------------------------------

TOOL_ZH = {
    "calculate": "计算", "cancel_pending_order": "取消订单", "exchange_delivered_order_items": "换货",
    "find_user_id_by_name_zip": "按姓名和邮编查用户", "find_user_id_by_email": "按邮箱查用户",
    "get_order_details": "查订单", "get_product_details": "查商品", "get_item_details": "查商品款式",
    "get_user_details": "查用户", "list_all_product_types": "列出商品类别",
    "modify_pending_order_address": "改订单地址", "modify_pending_order_items": "改订单商品",
    "modify_pending_order_payment": "改支付方式", "modify_user_address": "改用户地址",
    "return_delivered_order_items": "退货", "transfer_to_human_agents": "转人工",
}
ACTION_ZH = {"cancel": "取消订单", "return": "退货", "exchange": "换货", "modify_items": "修改订单",
             "modify_address": "修改地址",
             "modify_order_address": "修改订单地址", "modify_user_address": "修改用户地址",
             "modify_payment": "修改支付方式", "all_requests": "处理请求"}
STATUS_ZH = {"pending": "待发货", "processed": "已处理", "delivered": "已送达", "cancelled": "已取消",
             "return requested": "已申请退货", "exchange requested": "已申请换货",
             "pending (item modified)": "待发货（商品已修改）"}
FIELD_ZH = {
    "status": "订单状态", "items": "订单商品", "return_items": "退货商品", "return_payment_method_id": "退款方式",
    "exchange_items": "换出的商品", "exchange_new_items": "换入的商品",
    "exchange_payment_method_id": "换货差价支付方式", "exchange_price_difference": "换货差价",
    "cancel_reason": "取消原因", "payment_history": "支付记录",
    "address.address1": "地址第一行", "address.address2": "地址第二行", "address.city": "城市",
    "address.state": "州", "address.zip": "邮编", "address.country": "国家",
}
CATEGORY_ZH = {
    "Instruction/Plan Adherence Failure": "未遵循指令或流程", "Invention of New Information": "编造信息",
    "Invalid Invocation": "无效的工具调用", "Misinterpretation of Tool Output": "误读工具结果",
    "Intent-Plan Misalignment": "理解错用户意图", "Underspecified User Intent": "用户信息不足或有误",
    "Intent Not Supported": "请求超出能力范围", "Guardrails Triggered": "触发安全限制",
    "System Failure": "系统故障", "Inconclusive": "无法判断",
}
CLAIM_PHRASE = {
    "executed_but_differs": "但数据库里的结果与期望不一致",
    "not_executed": "但在这之前并没有成功执行对应操作",
    "unrequested_change": "但改动了用户没有要求的内容",
    "wrong_action": "但实际执行的操作类型不对",
    "claimed_before_executed": "但说这句话时操作还没执行",
}
RULE_TEXT = {
    "tool_error": "{tool}被系统拒绝",
    "repeated_call": "用相同参数重复调用{tool}",
    "abnormal_termination": "对话被系统异常终止",
    "policy_authenticate_first": "还没验证用户身份就{tool}",
    "policy_other_users_order": "操作了不属于当前用户的订单",
    "policy_check_status_first": "{tool}之前没有先查询订单",
    "policy_wrong_order_status": "订单当前状态不允许{tool}",
    "policy_once_per_order": "同一订单重复{tool}",
    "policy_cancel_reason": "取消原因不是政策允许的选项",
    "policy_return_refund_method": "退款方式不符合政策",
    "policy_payment_must_differ": "新支付方式与原支付方式相同",
    "policy_confirm_before_write": "{tool}之前没有得到用户明确的“是”",
    "policy_list_details_before_write": "{tool}之前没有向用户列明改动细节",
    "policy_transfer_message": "转人工后没有按要求告知用户",
    "transfer_to_human": "Agent 把用户转给了人工客服",
}
SEVERITY_ZH = {"violation": "违规", "warning": "提醒", "info": "观察"}
SKIP_RULES = {"policy_one_action_per_turn"}   # fires in 85% of passing runs too (phase 2), not informative


def tool_zh(name: str) -> str:
    return TOOL_ZH.get(name, name)


# --- ids -> readable names ------------------------------------------------------------

class Names:
    """Item ids -> product names, payment method ids -> '信用卡 ····3926', from the initial database."""

    def __init__(self, db: dict):
        self.items: dict[str, dict] = {}
        for p in (db.get("products") or {}).values():
            for v in (p.get("variants") or {}).values():
                self.items[str(v["item_id"])] = {"name": p["name"], "options": v.get("options") or {}}
        self.payments: dict[str, str] = {}
        for u in (db.get("users") or {}).values():
            for pm in (u.get("payment_methods") or {}).values():
                src = pm.get("source")
                label = {"credit_card": "信用卡", "paypal": "PayPal", "gift_card": "礼品卡"}.get(src, src or "支付方式")
                if pm.get("last_four"):
                    label += f" ····{pm['last_four']}"
                self.payments[pm["id"]] = label

    def item(self, item_id: str, options: bool = True) -> str:
        it = self.items.get(str(item_id))
        if not it:
            return str(item_id)
        if not options or not it["options"]:
            return it["name"]
        return f"{it['name']}（{' · '.join(str(v) for v in it['options'].values())}）"

    def value(self, field: str, v: Any) -> str:
        if v is None or v == [] or v == "":
            return "（空）"
        if field == "status":
            return STATUS_ZH.get(v, str(v))
        if isinstance(v, list) and all(isinstance(x, str) and x in self.items for x in v):
            return "、".join(self.item(x) for x in v)
        if isinstance(v, str) and v in self.payments:
            return self.payments[v]
        if isinstance(v, str) and v in self.items:
            return self.item(v)
        if isinstance(v, (int, float)):
            return f"{v:g}"
        if isinstance(v, (list, dict)):
            return json.dumps(v, ensure_ascii=False)
        return str(v)


# --- expected vs actual -----------------------------------------------------------------

def _fields(record: dict) -> dict[str, Any]:
    """Comparable fields of an order / user record (nested address split, items as item ids)."""
    out = {}
    for k, v in (record or {}).items():
        if k in ("fulfillments", "name", "email", "orders", "payment_methods", "user_id", "order_id"):
            continue
        if k == "address" and isinstance(v, dict):
            out.update({f"address.{a}": b for a, b in v.items()})
        elif k == "items" and isinstance(v, list):
            out["items"] = [i.get("item_id") for i in v]
        elif k == "payment_history" and isinstance(v, list):
            out["payment_history"] = [f"{p.get('transaction_type')} {p.get('amount')} {p.get('payment_method_id')}" for p in v]
        else:
            out[k] = v
    return out


def comparison(dbs: dict, calls: list[dict], names: Names) -> list[dict]:
    """Rows for every field the task should change or the agent did change.

    status: ok (matches) / bad (differs, the agent wrote this record) /
    check (differs, but no successful agent write touched it - cause unknown).
    """
    written = {str(c["args"].get("order_id") or c["args"].get("user_id"))
               for c in calls if c["name"] in WRITE_TOOLS and c["ok"]}
    rows = []
    for table, label in (("orders", "订单"), ("users", "用户")):
        init_t, fin_t, exp_t = (dbs[k].get(table) or {} for k in ("initial", "final", "expected"))
        for eid in sorted(set(fin_t) | set(exp_t)):
            i, f, e = (_fields(t.get(eid)) for t in (init_t, fin_t, exp_t))
            if f == e == i:
                continue
            for key in sorted(set(i) | set(f) | set(e), key=lambda k: (k not in FIELD_ZH, k)):
                iv, fv, ev = i.get(key), f.get(key), e.get(key)
                if iv == fv == ev:
                    continue
                match = fv == ev
                row = {"entity": f"{label} {eid}", "field": key, "field_zh": FIELD_ZH.get(key, key),
                       "initial": names.value(key, iv), "expected": names.value(key, ev),
                       "actual": names.value(key, fv), "match": match,
                       "status": "ok" if match else ("bad" if eid in written else "check")}
                if isinstance(ev, list) and isinstance(fv, list):
                    row["missing"] = [names.value(key, [x]) for x in ev if x not in fv]
                    row["extra"] = [names.value(key, [x]) for x in fv if x not in ev]
                    # short names (no options) for the one-line verdict
                    row["missing_short"] = [names.item(x, options=False) if x in names.items else str(x) for x in ev if x not in fv]
                    row["extra_short"] = [names.item(x, options=False) if x in names.items else str(x) for x in fv if x not in ev]
                rows.append(row)
    return rows


# --- one-line tool summaries ----------------------------------------------------------------

def _items(names: Names, ids) -> str:
    ids = list(ids or [])
    return f"{len(ids)} 件商品（{'、'.join(names.item(x, options=False) for x in ids)}）" if ids else "0 件商品"


def call_summary(name: str, args: dict, names: Names) -> str:
    a = args or {}
    oid = a.get("order_id", "")
    pm = names.payments.get(a.get("payment_method_id"), a.get("payment_method_id"))
    if name == "return_delivered_order_items":
        return f"订单 {oid}，{_items(names, a.get('item_ids'))}，退款到 {pm}"
    if name == "exchange_delivered_order_items":
        return (f"订单 {oid}，{_items(names, a.get('item_ids'))} 换成 "
                f"{'、'.join(names.item(x) for x in a.get('new_item_ids') or [])}，差价用 {pm}")
    if name == "modify_pending_order_items":
        return (f"订单 {oid}，{_items(names, a.get('item_ids'))} 改成 "
                f"{'、'.join(names.item(x) for x in a.get('new_item_ids') or [])}，差价用 {pm}")
    if name == "cancel_pending_order":
        return f"订单 {oid}，原因：{a.get('reason')}"
    if name in ("modify_pending_order_address", "modify_user_address"):
        target = oid or a.get("user_id", "")
        addr = "，".join(str(a.get(k)) for k in ("address1", "address2", "city", "state", "zip") if a.get(k))
        return f"{target} → {addr}" + ("（地址第二行为空）" if not a.get("address2") else "")
    if name == "modify_pending_order_payment":
        return f"订单 {oid}，改用 {pm}"
    if name == "get_order_details":
        return f"订单 {oid}"
    if name == "get_user_details":
        return f"用户 {a.get('user_id')}"
    if name == "get_product_details":
        return f"商品 {a.get('product_id')}"
    if name == "get_item_details":
        return f"款式 {names.item(a.get('item_id', ''))}"
    if name == "find_user_id_by_email":
        return f"邮箱 {a.get('email')}"
    if name == "find_user_id_by_name_zip":
        return f"{a.get('first_name')} {a.get('last_name')}，邮编 {a.get('zip')}"
    if name == "transfer_to_human_agents":
        return "附上问题摘要"
    if name == "calculate":
        return str(a.get("expression"))
    return "，".join(f"{k}={v}" for k, v in a.items())


# tau2 retail tool errors, worded for a reader; anything else is shown as is.
ERROR_ZH = {
    "Non-delivered order cannot be returned": "订单不是“已送达”状态，不能退货",
    "Non-delivered order cannot be exchanged": "订单不是“已送达”状态，不能换货",
    "Non-pending order cannot be modified": "订单不是“待发货”状态，不能修改",
    "Non-pending order cannot be cancelled": "订单不是“待发货”状态，不能取消",
    "Order not found": "找不到这个订单", "User not found": "找不到这个用户",
    "Product not found": "找不到这个商品", "Item not found": "找不到这个款式",
    "Payment method not found": "找不到这个支付方式",
    "Some item not found": "有商品不在订单里",
    "New item not found or not available": "新款式不存在或无货",
    "Payment method should be the original payment method": "退款只能退回原支付方式",
    "The new item id should be different from the old item id": "新款式必须和原款式不同",
    "The number of items to be exchanged should match": "换出和换入的商品数量必须一致",
    "Insufficient gift card balance": "礼品卡余额不足以支付差价",
    "Variant not found": "找不到这个款式",
    "There should be exactly one payment for a pending order": "待发货订单应当只有一笔支付",
}


def result_summary(name: str, ok: bool, content: str, names: Names) -> str:
    if not ok:
        text = (content or "").strip().removeprefix("Error:").strip()
        zh = next((v for k, v in ERROR_ZH.items() if text.lower().startswith(k.lower())), None)
        return f"报错：{zh}" if zh else f"报错：{text[:120]}"
    data = None
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        pass
    if isinstance(data, dict):
        if name == "get_order_details":
            return (f"成功：{STATUS_ZH.get(data.get('status'), data.get('status'))}，"
                    f"{_items(names, [i.get('item_id') for i in data.get('items') or []])}")
        if name == "get_user_details":
            return f"成功：{len(data.get('orders') or [])} 个订单，{len(data.get('payment_methods') or {})} 种支付方式"
        if name == "get_product_details":
            variants = (data.get("variants") or {}).values()
            return f"成功：{data.get('name')}，{len(variants)} 个款式，其中 {sum(bool(v.get('available')) for v in variants)} 个有货"
        if name in WRITE_TOOLS:
            return f"成功：订单状态变为「{STATUS_ZH.get(data.get('status'), data.get('status'))}」" if data.get("status") else "成功"
    if isinstance(data, str) or (content and len(content) < 60):
        return f"成功：{content.strip()}"
    return "成功"


# --- the three columns -------------------------------------------------------------------------

def facts(report: dict) -> list[dict]:
    """Observed facts, merged per step: [{step, items: [{text, severity}]}]. Claims and rules, no repeats."""
    by_step: dict[Optional[int], list[dict]] = {}

    def add(step, text, severity):
        items = by_step.setdefault(step, [])
        if not any(x["text"] == text for x in items):
            items.append({"text": text, "severity": severity})

    for c in report["claims"]:
        if c["status"] in CLAIM_PHRASE:
            add(c["step"], f"Agent 告诉用户{ACTION_ZH.get(c['action'], '操作')}已完成，{CLAIM_PHRASE[c['status']]}", "violation")
    for f in report["findings"]:
        if f["rule_id"].startswith("claim_") or f["rule_id"] in SKIP_RULES:
            continue
        tool = next((tool_zh(n) for n in TOOL_ZH if f["message"].startswith(n)), "这次操作")
        text = RULE_TEXT.get(f["rule_id"], f["rule_id"]).format(tool=tool)
        add(f["step"], text, f["severity"])
    return [{"step": s, "items": v} for s, v in sorted(by_step.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))]


def ai_column(diag: Optional[dict]) -> Optional[dict]:
    if not diag:
        return None
    agree = round((diag.get("confidence") or 0) * 3)
    return {
        "critical_step": diag.get("critical_step"), "category": diag.get("category"),
        "category_zh": CATEGORY_ZH.get(diag.get("category"), diag.get("category") or "—"),
        "failed_agent_zh": {"assistant": "Agent", "user": "用户（模拟）"}.get(diag.get("failed_agent"), "—"),
        "confidence": diag.get("confidence"), "agree": f"{agree}/3",
        "abstain": diag.get("abstain"), "summary": diag.get("summary") or "",
        "inference": diag.get("inference") or [], "evidence": [e for e in diag.get("evidence") or [] if e.get("valid")],
        "model": diag.get("model"), "prompt_version": diag.get("prompt_version"),
    }


def abstain_reason_zh(diag: dict) -> str:
    """Our own vote() reasons, re-worded (they are generated by code, not by the model)."""
    out = []
    reason = diag.get("abstain_reason") or ""
    if "samples agree" in reason:
        out.append(f"3 次独立判断里只有 {round((diag.get('confidence') or 0) * 3)} 次一致")
    if "no verbatim evidence" in reason:
        out.append("关键步骤上找不到能逐字核对的原文证据")
    if "inconclusive" in reason:
        out.append("模型自己判断为“无法判断”")
    if "API error" in reason or "no usable answer" in reason:
        out.append("模型没有给出可用的回答")
    return "；".join(out) or reason


def checks(report: dict, diag: Optional[dict], rows: list[dict]) -> list[dict]:
    out = []
    if diag and diag.get("abstain"):
        out.append({"step": diag.get("critical_step"), "text": f"调查 agent 拿不准，已弃权：{abstain_reason_zh(diag)}"})
    for e in (diag or {}).get("evidence") or []:
        if not e.get("valid"):
            out.append({"step": e.get("step"), "text": "调查 agent 引用的一段原文在该步骤里找不到，不能当证据"})
    for s in (diag or {}).get("needs_verification") or []:
        out.append({"step": None, "text": s})
    for c in report["claims"]:
        if c["status"] == "unverifiable":
            out.append({"step": c["step"], "text": "Agent 的一句“已完成”无法用数据库核验（找不到对应订单或操作类型）"})
    for r in rows:
        if r["status"] == "check":
            out.append({"step": None, "text": f"{r['entity']} 的{r['field_zh']}与期望不同，但 Agent 没有成功写过这条记录，原因待核实"})
    return out


# --- verdict -------------------------------------------------------------------------------------

def _diff_phrase(r: dict) -> str:
    if r.get("missing") and not r.get("extra"):
        return f"{r['field_zh']}少了 {'、'.join(r.get('missing_short') or r['missing'])}"
    if r.get("extra") and not r.get("missing"):
        return f"{r['field_zh']}多了 {'、'.join(r.get('extra_short') or r['extra'])}"
    return f"{r['field_zh']}应为「{r['expected']}」，实际是「{r['actual']}」"


def verdict(report: dict, rows: list[dict], diag: Optional[dict]) -> dict:
    success = bool(report["tau2_success"])
    bad = [r for r in rows if not r["match"]]
    violations = [f for f in report["findings"] if f["severity"] == "violation"
                  and not f["rule_id"].startswith("claim_") and f["rule_id"] not in SKIP_RULES]
    false_claims = [c for c in report["claims"] if c["status"] in ("executed_but_differs", "not_executed")]
    if success:
        kind, sentence = "无", "任务成功：数据库最终状态与标准答案一致，回复内容也达标。"
    elif report["false_success"] and false_claims:
        steps = "、".join(str(s) for s in sorted({c["step"] for c in false_claims}))
        action = ACTION_ZH.get(false_claims[0]["action"], "操作")
        what = f"，但数据库里的{_diff_phrase(bad[0])}" if bad else "，但数据库不支持这个说法"
        kind, sentence = "假成功", f"假成功：Agent 在步骤 {steps} 告诉用户{action}已办好{what}（见下方对比）。"
    elif violations:
        f = violations[0]
        tool = next((tool_zh(n) for n in TOOL_ZH if f["message"].startswith(n)), "这次操作")
        kind = "工具报错" if f["rule_id"] == "tool_error" else (
            "异常终止" if f["rule_id"] == "abnormal_termination" else "违反政策")
        sentence = f"{kind}：步骤 {f['step']} {RULE_TEXT.get(f['rule_id'], f['rule_id']).format(tool=tool)}。"
        if bad:
            sentence += f"最终数据库的{_diff_phrase(bad[0])}。"
    elif bad:
        kind, sentence = "结果不符", f"任务失败：最终数据库的{_diff_phrase(bad[0])}（共 {len(bad)} 处不一致）。"
    else:
        kind, sentence = "回复不达标", "任务失败：数据库结果正确，但 Agent 的回复没有满足任务要求的内容。"
    if not success and diag and not diag.get("abstain") and diag.get("critical_step") is not None:
        sentence += f"调查 agent 认为根源在步骤 {diag['critical_step']}（{CATEGORY_ZH.get(diag.get('category'), diag.get('category'))}）。"
    if not diag:
        ai = {"text": "未运行调查 agent", "tone": "muted"}
    elif diag.get("abstain"):
        ai = {"text": "拿不准，需要人工判断", "tone": "warn"}
    else:
        conf = diag.get("confidence")
        ai = {"text": f"步骤 {diag.get('critical_step')} · 置信度 {conf:.2f}" if conf is not None
              else f"步骤 {diag.get('critical_step')}", "tone": "ai"}
    return {"sentence": sentence,
            "labels": {"task": {"text": "成功" if success else "失败", "tone": "good" if success else "bad"},
                       "kind": {"text": kind, "tone": "good" if success else "bad"}, "ai": ai}}


# --- timeline ------------------------------------------------------------------------------------

MAX_RAW = 6000


def timeline(sim: dict, report: dict, names: Names, translations: dict[str, str]) -> list[dict]:
    """Messages and tool calls in order. A tool result is folded into its call's card."""
    msgs = sim.get("messages") or []
    calls = {(c["step"], i): c for i, c in enumerate(tool_calls(msgs))}
    by_step: dict[int, list[dict]] = {}
    for c in calls.values():
        by_step.setdefault(c["step"], []).append(c)
    result_steps = {c["result_step"] for c in calls.values() if c["result_step"] is not None}
    rules = {}
    for f in report["findings"]:
        if not f["rule_id"].startswith("claim_") and f["rule_id"] not in SKIP_RULES:
            rules.setdefault(f["step"], []).append(RULE_TEXT.get(f["rule_id"], f["rule_id"]).format(tool="").strip())
    claims = {}
    for c in report["claims"]:
        if c["status"] != "verified":
            claims.setdefault(c["step"], c["status"])
    out = []
    for step, m in enumerate(msgs):
        role = m.get("role")
        if role == "tool" and step in result_steps:
            continue                               # shown inside the call card
        text = (m.get("content") or "").strip()
        entry = {"step": step, "role": role, "text": text, "zh": translations.get(text) if text else None,
                 "rules": sorted(set(rules.get(step, []))), "claim": claims.get(step), "calls": []}
        for c in by_step.get(step, []):
            raw = {"arguments": c["args"], "result": c["result"]}
            raw_text = json.dumps(raw, ensure_ascii=False, indent=1)
            entry["calls"].append({
                "name": c["name"], "name_zh": tool_zh(c["name"]), "write": c["name"] in WRITE_TOOLS,
                "summary": call_summary(c["name"], c["args"], names), "ok": c["ok"],
                "result_step": c["result_step"], "result": result_summary(c["name"], c["ok"], c["result"], names),
                "raw": raw_text if len(raw_text) <= MAX_RAW else raw_text[:MAX_RAW] + "\n…（已截断）",
            })
            entry["rules"] = sorted(set(entry["rules"] + rules.get(c["result_step"], [])))
        out.append(entry)
    return out


def key_steps(report: dict, diag: Optional[dict], chain: list[dict]) -> list[int]:
    """Steps shown in "只看关键步骤": the causal chain, claims, violations, the critical step, each +-1."""
    core = {link["step"] for link in chain if link.get("step") is not None}
    core |= {c["step"] for c in report["claims"] if c["status"] in CLAIM_PHRASE}
    core |= {f["step"] for f in report["findings"] if f["severity"] == "violation" and f["rule_id"] not in SKIP_RULES}
    if diag and diag.get("critical_step") is not None:
        core.add(diag["critical_step"])
    return sorted({s + d for s in core if s is not None for d in (-1, 0, 1)})
