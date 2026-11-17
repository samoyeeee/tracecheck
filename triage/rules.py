"""Layer 2: deterministic checks on a trajectory. No LLM.

Each check returns ``Finding`` objects with the rule that fired, the step
(index into ``messages``), a quoted evidence snippet and, for policy rules,
the original policy sentence it enforces.

Checks that rely on exact structure (tool names, arguments, tool results)
report ``basis="structural"``. Checks that rely on keywords in free text
(e.g. "did the user say yes") report ``basis="keyword"`` and, when the
keywords are inconclusive, emit ``needs_verification`` instead of a verdict.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Callable, Optional

from triage.schema import Evidence, Finding
from triage.verify import WRITE_TOOLS, tool_calls

# Original policy sentences (data/tau2/domains/retail/policy.md, tau2 commit c06b07d).
POLICY = {
    "auth": "At the beginning of the conversation, you have to authenticate the user identity by "
            "locating their user id via email, or via name + zip code. This has to be done even when "
            "the user already provides the user id.",
    "one_user": "You can only help one user per conversation (but you can handle multiple requests "
                "from the same user), and must deny any requests for tasks related to any other user.",
    "confirm": "Before taking any action that updates the database (cancel, modify, return, exchange), "
               "you must list the action details and obtain explicit user confirmation (yes) to proceed.",
    "one_call": "You should at most make one tool call at a time, and if you take a tool call, you should "
                "not respond to the user at the same time. If you respond to the user, you should not make "
                "a tool call at the same time.",
    "transfer": "To transfer, first make a tool call to transfer_to_human_agents, and then send the message "
                "'YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.' to the user.",
    "once_per_order": "Exchange or modify order tools can only be called once per order.",
    "check_status": "An order can only be {verb} if its status is '{status}', and you should check its "
                    "status before taking the action.",
    "cancel_reason": "The user needs to confirm the order id and the reason (either 'no longer needed' or "
                     "'ordered by mistake') for cancellation. Other reasons are not acceptable.",
    "return_refund": "The refund must either go to the original payment method, or an existing gift card.",
    "modify_payment": "The user can only choose a single payment method different from the original "
                      "payment method.",
}

TRANSFER_MESSAGE = "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
AUTH_TOOLS = {"find_user_id_by_email", "find_user_id_by_name_zip"}
USER_SCOPED_TOOLS = {"get_user_details", "get_order_details"} | WRITE_TOOLS
# Required order status per write tool (policy sections "Cancel pending order", ...).
REQUIRED_STATUS = {
    "cancel_pending_order": ("cancelled", "pending"),
    "modify_pending_order_address": ("modified", "pending"),
    "modify_pending_order_items": ("modified", "pending"),
    "modify_pending_order_payment": ("modified", "pending"),
    "return_delivered_order_items": ("returned", "delivered"),
    "exchange_delivered_order_items": ("exchanged", "delivered"),
}
ONCE_PER_ORDER = {"exchange_delivered_order_items", "modify_pending_order_items"}
CANCEL_REASONS = {"no longer needed", "ordered by mistake"}

EXPLICIT_YES = re.compile(r"\b(yes|yeah|yep|yup|confirm(ed)?|go ahead|proceed|please do|do it)\b", re.I)
SOFT_YES = re.compile(r"\b(ok(ay)?|sure|correct|that's right|sounds good|fine|alright|right)\b", re.I)
NEGATION = re.compile(r"\b(no|not|don't|wait|hold on|actually|instead|change)\b", re.I)


def _snip(text, n: int = 220) -> str:
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _json(text: str) -> Optional[dict]:
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except (TypeError, json.JSONDecodeError):
        return None


def _sev(c: dict) -> str:
    """A policy breach that the tool itself rejected did no harm: warning only."""
    return "violation" if c["ok"] else "warning"


def _rej(c: dict) -> str:
    return "" if c["ok"] else " (the tool rejected the call)"


def _call_ev(c: dict) -> Evidence:
    return Evidence(step=c["step"], role="assistant",
                    text=f"{c['name']}({_snip(json.dumps(c['args'], ensure_ascii=False), 180)})")


# --- generic checks ------------------------------------------------------------

def check_tool_errors(messages, calls) -> list[Finding]:
    out = []
    for c in calls:
        if c["result_step"] is not None and not c["ok"]:
            out.append(Finding(
                rule_id="tool_error", layer="rules", severity="warning", knowledge="observed",
                step=c["result_step"], message=f"{c['name']} returned an error",
                evidence=[_call_ev(c), Evidence(c["result_step"], "tool", _snip(c["result"]))]))
    return out


def check_repeated_calls(messages, calls) -> list[Finding]:
    """Same tool + same arguments: 3+ times anywhere, or twice back to back."""
    out = []
    key = lambda c: (c["name"], json.dumps(c["args"], sort_keys=True))  # noqa: E731
    counts = Counter(key(c) for c in calls)
    reported = set()
    for i, c in enumerate(calls):
        k = key(c)
        back_to_back = i > 0 and key(calls[i - 1]) == k and not any(
            m.get("role") == "user" for m in messages[calls[i - 1]["step"]:c["step"]])
        if k in reported or not (counts[k] >= 3 or back_to_back):
            continue
        reported.add(k)
        steps = [x["step"] for x in calls if key(x) == k]
        out.append(Finding(
            rule_id="repeated_call", layer="rules", severity="warning", knowledge="observed",
            step=steps[1], message=f"{c['name']} called {counts[k]}x with identical arguments "
                                   f"(steps {steps}){' back to back' if back_to_back else ''}; possible loop",
            evidence=[_call_ev(x) for x in calls if key(x) == k][:3],
            details={"steps": steps, "count": counts[k]}))
    return out


def check_termination(sim) -> list[Finding]:
    reason = sim.get("termination_reason")
    if reason in ("user_stop", "agent_stop", None):
        return []
    return [Finding(rule_id="abnormal_termination", layer="rules", severity="violation",
                    knowledge="observed", step=len(sim.get("messages") or []) - 1,
                    message=f"simulation ended by '{reason}', not by the user or agent")]


# --- policy checks -------------------------------------------------------------

def check_one_call_at_a_time(messages, calls) -> list[Finding]:
    out = []
    for step, m in enumerate(messages):
        if m.get("role") != "assistant" or not m.get("tool_calls"):
            continue
        text = (m.get("content") or "").strip()
        n = len(m["tool_calls"])
        if n > 1 or text:
            what = f"{n} tool calls in one turn" if n > 1 else "text to the user and a tool call in one turn"
            out.append(Finding(
                rule_id="policy_one_action_per_turn", layer="rules", severity="warning",
                knowledge="observed", step=step, message=what, policy_quote=POLICY["one_call"],
                evidence=[Evidence(step, "assistant", _snip(text or str([t['name'] for t in m['tool_calls']])))]))
    return out


def check_authentication(messages, calls) -> list[Finding]:
    """User-specific tools only after a successful find_user_id_* call."""
    authed_at = next((c["step"] for c in calls if c["name"] in AUTH_TOOLS and c["ok"]), None)
    for c in calls:
        if c["name"] in USER_SCOPED_TOOLS and (authed_at is None or c["step"] < authed_at):
            return [Finding(
                rule_id="policy_authenticate_first", layer="rules",
                severity="violation", knowledge="observed", step=c["step"],
                message=f"{c['name']} called before the user was authenticated "
                        f"({'never authenticated' if authed_at is None else f'auth at step {authed_at}'})",
                policy_quote=POLICY["auth"], evidence=[_call_ev(c)])]
    return []


def _order_views(calls) -> list[tuple[int, dict]]:
    """(step, order) for every successful get_order_details result."""
    views = []
    for c in calls:
        if c["name"] == "get_order_details" and c["ok"]:
            order = _json(c["result"])
            if order:
                views.append((c["step"], order))
    return views


def check_other_user(messages, calls) -> list[Finding]:
    authed = [_snip(c["result"], 80) for c in calls if c["name"] in AUTH_TOOLS and c["ok"]]
    if not authed:
        return []
    user = authed[0]
    out = []
    for step, order in _order_views(calls):
        owner = order.get("user_id")
        if owner and owner != user:
            writes = [c for c in calls if c["name"] in WRITE_TOOLS and c["args"].get("order_id") == order.get("order_id")]
            out.append(Finding(
                rule_id="policy_other_users_order", layer="rules",
                severity="violation" if writes else "warning", knowledge="observed", step=step,
                message=f"order {order.get('order_id')} belongs to {owner}, authenticated user is {user}"
                        + (f"; agent then wrote to it at step {writes[0]['step']}" if writes else ""),
                policy_quote=POLICY["one_user"],
                evidence=[Evidence(step, "tool", f"user_id: {owner}")] + [_call_ev(w) for w in writes[:1]]))
    return out


def check_status_before_write(messages, calls) -> list[Finding]:
    out = []
    views = _order_views(calls)
    for c in calls:
        if c["name"] not in REQUIRED_STATUS:
            continue
        verb, status = REQUIRED_STATUS[c["name"]]
        quote = POLICY["check_status"].format(verb=verb, status=status)
        oid = c["args"].get("order_id")
        seen = [(s, o) for s, o in views if o.get("order_id") == oid and s < c["step"]]
        if not seen:
            out.append(Finding(
                rule_id="policy_check_status_first", layer="rules", severity=_sev(c),
                knowledge="observed", step=c["step"],
                message=f"{c['name']} on {oid} without looking the order up first{_rej(c)}",
                policy_quote=quote, evidence=[_call_ev(c)]))
            continue
        last_status = seen[-1][1].get("status")
        if last_status != status:
            out.append(Finding(
                rule_id="policy_wrong_order_status", layer="rules", severity=_sev(c),
                knowledge="observed", step=c["step"],
                message=f"{c['name']} on {oid} whose last seen status was '{last_status}' "
                        f"(needs '{status}'){_rej(c)}",
                policy_quote=quote,
                evidence=[Evidence(seen[-1][0], "tool", f"status: {last_status}"), _call_ev(c)]))
    return out


def check_once_per_order(messages, calls) -> list[Finding]:
    out = []
    per_order = Counter((c["name"], c["args"].get("order_id")) for c in calls if c["name"] in ONCE_PER_ORDER)
    for (name, oid), n in per_order.items():
        if n > 1:
            hits = [c for c in calls if c["name"] == name and c["args"].get("order_id") == oid]
            ok = sum(h["ok"] for h in hits)
            out.append(Finding(
                rule_id="policy_once_per_order", layer="rules",
                severity="violation" if ok > 1 else "warning",
                knowledge="observed", step=hits[1]["step"],
                message=f"{name} called {n}x on {oid} ({ok} accepted by the tool)",
                policy_quote=POLICY["once_per_order"], evidence=[_call_ev(h) for h in hits[:3]]))
    return out


def check_cancel_reason(messages, calls) -> list[Finding]:
    return [Finding(
        rule_id="policy_cancel_reason", layer="rules", severity=_sev(c), knowledge="observed",
        step=c["step"], message=f"cancellation reason '{c['args'].get('reason')}' is not an allowed "
                                f"reason{_rej(c)}",
        policy_quote=POLICY["cancel_reason"], evidence=[_call_ev(c)])
        for c in calls if c["name"] == "cancel_pending_order"
        and str(c["args"].get("reason", "")).strip().lower() not in CANCEL_REASONS]


def _original_payment(calls, oid, before_step) -> Optional[str]:
    for step, order in reversed(_order_views(calls)):
        if order.get("order_id") == oid and step < before_step:
            for p in order.get("payment_history") or []:
                if p.get("transaction_type") == "payment":
                    return p.get("payment_method_id")
    return None


def check_refund_and_payment(messages, calls) -> list[Finding]:
    out = []
    for c in calls:
        oid, pm = c["args"].get("order_id"), c["args"].get("payment_method_id")
        if c["name"] == "return_delivered_order_items" and pm:
            original = _original_payment(calls, oid, c["step"])
            if original and pm != original and not str(pm).startswith("gift_card"):
                out.append(Finding(
                    rule_id="policy_return_refund_method", layer="rules", severity=_sev(c),
                    knowledge="observed", step=c["step"],
                    message=f"refund to {pm}; original payment was {original} and {pm} is not a "
                            f"gift card{_rej(c)}",
                    policy_quote=POLICY["return_refund"], evidence=[_call_ev(c)]))
        if c["name"] == "modify_pending_order_payment" and pm:
            original = _original_payment(calls, oid, c["step"])
            if original and pm == original:
                out.append(Finding(
                    rule_id="policy_payment_must_differ", layer="rules", severity=_sev(c),
                    knowledge="observed", step=c["step"],
                    message=f"new payment method {pm} is the same as the original{_rej(c)}",
                    policy_quote=POLICY["modify_payment"], evidence=[_call_ev(c)]))
    return out


def check_confirmation(messages, calls) -> list[Finding]:
    """Each write needs an explicit 'yes' in the user's last message before it,
    and the agent's message before that should list the details (order id)."""
    out = []
    for c in calls:
        if c["name"] not in WRITE_TOOLS:
            continue
        user_steps = [i for i in range(c["step"]) if messages[i].get("role") == "user"]
        if not user_steps:
            out.append(Finding(
                rule_id="policy_confirm_before_write", layer="rules", severity="violation",
                knowledge="observed", step=c["step"], message=f"{c['name']} before any user message",
                policy_quote=POLICY["confirm"], evidence=[_call_ev(c)]))
            continue
        u = user_steps[-1]
        said = messages[u].get("content") or ""
        # Was the same confirmation already used by an earlier write?
        reused = [p for p in calls if p["name"] in WRITE_TOOLS and p["ok"] and u < p["step"] < c["step"]]
        ev = [Evidence(u, "user", _snip(said)), _call_ev(c)]
        if reused:
            out.append(Finding(
                rule_id="policy_confirm_before_write", layer="rules", severity="warning",
                knowledge="needs_verification", basis="keyword", step=c["step"],
                message=f"{c['name']} reuses the confirmation given before step {reused[0]['step']}; "
                        "check that the user confirmed both actions",
                policy_quote=POLICY["confirm"], evidence=ev))
        elif EXPLICIT_YES.search(said):
            pass
        elif SOFT_YES.search(said) and not NEGATION.search(said):
            out.append(Finding(
                rule_id="policy_confirm_before_write", layer="rules", severity="warning",
                knowledge="needs_verification", basis="keyword", step=c["step"],
                message=f"{c['name']} after a soft agreement, not an explicit 'yes'",
                policy_quote=POLICY["confirm"], evidence=ev))
        else:
            out.append(Finding(
                rule_id="policy_confirm_before_write", layer="rules", severity="violation",
                knowledge="observed", basis="keyword", step=c["step"],
                message=f"{c['name']} without an explicit confirmation in the user's last message",
                policy_quote=POLICY["confirm"], evidence=ev))
        # Details listed? The agent's last text message before u should name the order.
        oid = c["args"].get("order_id")
        prev = [i for i in range(u) if messages[i].get("role") == "assistant" and (messages[i].get("content") or "").strip()]
        if oid and prev and oid not in messages[prev[-1]]["content"]:
            out.append(Finding(
                rule_id="policy_list_details_before_write", layer="rules", severity="warning",
                knowledge="needs_verification", basis="keyword", step=c["step"],
                message=f"agent's message before the confirmation does not mention {oid}",
                policy_quote=POLICY["confirm"],
                evidence=[Evidence(prev[-1], "assistant", _snip(messages[prev[-1]]["content"])), _call_ev(c)]))
    return out


def check_transfer(messages, calls) -> list[Finding]:
    out = []
    for c in calls:
        if c["name"] != "transfer_to_human_agents":
            continue
        after = [i for i in range(c["step"] + 1, len(messages))
                 if messages[i].get("role") == "assistant" and (messages[i].get("content") or "").strip()]
        text = messages[after[0]]["content"].strip() if after else ""
        if text != TRANSFER_MESSAGE:
            out.append(Finding(
                rule_id="policy_transfer_message", layer="rules", severity="warning",
                knowledge="observed", step=after[0] if after else c["step"],
                message="transfer not followed by the required hold message",
                policy_quote=POLICY["transfer"],
                evidence=[_call_ev(c)] + ([Evidence(after[0], "assistant", _snip(text))] if after else [])))
    return out


CHECKS: list[Callable] = [
    check_tool_errors, check_repeated_calls, check_one_call_at_a_time, check_authentication,
    check_other_user, check_status_before_write, check_once_per_order, check_cancel_reason,
    check_refund_and_payment, check_confirmation, check_transfer,
]


def run_rules(sim: dict) -> list[Finding]:
    messages = sim.get("messages") or []
    calls = tool_calls(messages)
    findings = check_termination(sim)
    for check in CHECKS:
        findings.extend(check(messages, calls))
    return sorted(findings, key=lambda f: (f.step if f.step is not None else -1, f.rule_id))
