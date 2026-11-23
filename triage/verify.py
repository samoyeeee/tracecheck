"""Layer 1: outcome verification and false-success detection. No LLM.

For one trajectory this module

1. takes tau2's verdict (reward, db_check) as the ground truth for success;
2. rebuilds three databases deterministically with tau2's own environment:
   - ``initial``  - the task's starting state,
   - ``final``    - the starting state + every tool call the agent made,
   - ``expected`` - the starting state + the task's reference actions,
   and diffs ``final`` against ``expected`` per order / user (field level);
3. finds sentences where the agent tells the user an action is done
   ("your order has been cancelled", "exchange completed", ...) using
   keyword + structure rules, and checks each claim against the tool calls
   and the replayed databases.

A claim is a **false success** when the agent said the action was done but
either no successful matching write happened before the message
(``not_executed``) or the write happened and the entity still differs from
the expected end state (``executed_but_differs``). Claims the rules cannot
pin to an action or entity are ``unverifiable`` - they are reported, never
guessed.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from triage.schema import FALSE_SUCCESS_STATUSES, Claim, TraceReport

# --- action vocabulary -------------------------------------------------------

# Which write tools can make a claim of each action type true.
ACTION_TOOLS: dict[str, set[str]] = {
    "cancel": {"cancel_pending_order"},
    "return": {"return_delivered_order_items"},
    # Agents say "exchange" for item changes on pending orders too, and vice versa.
    "exchange": {"exchange_delivered_order_items", "modify_pending_order_items"},
    # "order updated / modified" may describe any change to a pending order.
    "modify_items": {"modify_pending_order_items", "exchange_delivered_order_items",
                     "modify_pending_order_address", "modify_pending_order_payment"},
    "modify_payment": {"modify_pending_order_payment"},
    "modify_address": {"modify_pending_order_address", "modify_user_address"},
    "modify_user_address": {"modify_user_address"},
}
# "All your requests have been completed": true if any write happened.
ACTION_TOOLS["all_requests"] = set().union(*ACTION_TOOLS.values())
WRITE_TOOLS = set().union(*ACTION_TOOLS.values())

# Order status each action leaves behind; used to skip sentences that merely
# describe a state the order already had before the conversation.
ACTION_STATUS = {
    "cancel": "cancelled",
    "return": "return requested",
    "exchange": "exchange requested",
    "modify_items": "pending (item modified)",
}

ORDER_ID = re.compile(r"#W\d{7}")

# Sentence must contain a completion marker AND an action keyword.
COMPLETION = re.compile(
    r"\b(has|have) (now )?(also )?been\b|\bsuccessfully\b|\b(is|are) now\b|"
    r"\bcompleted?\b|\bprocessed\b|\bsubmitted\b|✅|"
    r"\bI(?:'ve| have) (?:now )?(?:successfully )?(?:cancel|return|exchang|modif|updat|chang|process|submit)",
    re.I,
)
# Strong markers allow the action to be taken from the rest of the message.
STRONG_COMPLETION = re.compile(r"\bsuccessfully\b|\bhas been (processed|completed)\b|✅", re.I)
# Hedged / future / negated sentences, and sentences about non-write steps
# (authentication, look-ups) or side effects (refunds, balances), are not claims.
NOT_A_CLAIM = re.compile(
    r"\?|\b(will|would|can|could|should|need|needs|want|wants|wish|let me|going to|once|"
    r"if|before|please confirm|to proceed|unable|cannot|can't|couldn't|not|doesn't|don't|"
    r"isn't|wasn't|haven't|hasn't|won't|wouldn't|might|may|wait|then|unfortunately|authenticat\w*|verif\w*|found|locat\w*|"
    r"look(ed)? up|refund\w*|balance|available|availability)\b",
    re.I,
)
_CHANGED = r"(updated|changed|modified|switched|change|update)"
ACTION_KEYWORDS: list[tuple[str, re.Pattern]] = [
    # order matters: the first match wins
    ("modify_user_address", re.compile(
        rf"\b(default|profile|account)\b[^.]*\baddress\b[^.]*\b{_CHANGED}\b|"
        rf"\b{_CHANGED}\b[^.]*\b(default|profile|account)\b[^.]*\baddress\b", re.I)),
    ("modify_address", re.compile(rf"\baddress\b[^.]*\b{_CHANGED}\b|\b{_CHANGED}\b[^.]*\baddress\b", re.I)),
    ("modify_payment", re.compile(rf"\bpayment\b[^.]*\b{_CHANGED}\b|\b{_CHANGED}\b[^.]*\bpayment\b", re.I)),
    ("cancel", re.compile(r"\bcancel", re.I)),
    ("exchange", re.compile(r"\bexchang", re.I)),
    ("return", re.compile(r"\breturn(s|ed)?\b(?! (instructions|label))", re.I)),
    ("modify_items", re.compile(rf"\bmodification|\b(item|items|order|orders)\b[^.]*\b{_CHANGED}\b|"
                                rf"\b{_CHANGED}\b[^.]*\b(item|items|order|orders)\b", re.I)),
    ("all_requests", re.compile(r"\b(all|both|every)\b[^.]*\b(requests?|actions?|changes|everything)\b|"
                                r"\beverything\b|\bchanges\b", re.I)),
]

SENTENCE_SPLIT = re.compile(r"(?<=[.!])\s+|\n+")


def _clean(text: str) -> str:
    return re.sub(r"[*_`#>]+(?!W\d)", "", text).strip()


def classify_sentence(sentence: str) -> Optional[str]:
    """Action type if ``sentence`` is a completion claim, else None."""
    if not COMPLETION.search(sentence) or NOT_A_CLAIM.search(sentence):
        return None
    for action, pattern in ACTION_KEYWORDS:
        if pattern.search(sentence):
            return action
    if STRONG_COMPLETION.search(sentence):
        return "unspecified"
    return None


FAILURE_WORDS = re.compile(
    r"\b(unable|cannot|can't|couldn't|could not|not able|failed|fail|unsuccessful|not possible|"
    r"wasn't|was not|weren't|were not|not been|not processed|issue|problem|error)\b|❌", re.I)
ITEM_LIST_FIELDS = ("return_items", "exchange_items", "exchange_new_items")
DERIVED_FIELDS = {"exchange_price_difference"}   # follow from the item lists


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def extract_claims(messages: list[dict]) -> list[dict]:
    """All completion claims in assistant text, one per (step, action, orders).

    Order ids are taken from the sentence itself only; a claim without an id
    is checked against every matching write (see ``check_claim``).
    """
    claims = []
    for step, msg in enumerate(messages):
        if msg.get("role") != "assistant" or not (msg.get("content") or "").strip():
            continue
        seen = set()
        for raw in SENTENCE_SPLIT.split(msg["content"]):
            sentence = _clean(raw)
            action = classify_sentence(sentence)
            if action is None:
                continue
            ids = sorted(set(ORDER_ID.findall(sentence)))
            if (action, tuple(ids)) in seen:
                continue
            seen.add((action, tuple(ids)))
            later = " ".join(_clean(m.get("content") or "") for m in messages[step:]
                             if m.get("role") == "assistant")
            claims.append({"step": step, "action": action, "entity_ids": ids,
                           "sentence": sentence[:300], "later_text": later,
                           "message": _clean(msg["content"])})
    return claims


# --- database replay ---------------------------------------------------------

@lru_cache(maxsize=None)
def _task(task_id: str):
    from tau2.runner import get_tasks
    return get_tasks("retail", task_ids=[task_id])[0]


def _fresh_env(task, message_history):
    from tau2.registry import registry
    ist = task.initial_state
    env = registry.get_env_constructor("retail")()
    env.set_state(
        initialization_data=ist.initialization_data if ist else None,
        initialization_actions=ist.initialization_actions if ist else None,
        message_history=list(message_history),
        strict=False,
    )
    return env


def replay(sim_json: str, task_id: str) -> dict[str, Any]:
    """Rebuild initial / final / expected DBs exactly as tau2's evaluator does."""
    from tau2.data_model.simulation import SimulationRun

    task = _task(task_id)
    sim = SimulationRun.model_validate_json(sim_json)
    prefix = (task.initial_state.message_history if task.initial_state else None) or []
    initial = _fresh_env(task, prefix)
    final = _fresh_env(task, sim.messages or [])
    expected = _fresh_env(task, prefix)
    for action in (task.evaluation_criteria.actions or []) if task.evaluation_criteria else []:
        try:
            expected.make_tool_call(tool_name=action.name, requestor=action.requestor, **action.arguments)
        except Exception:  # noqa: BLE001 - tau2 also ignores failing reference actions
            pass
    match = (final.get_db_hash() == expected.get_db_hash()
             and final.get_user_db_hash() == expected.get_user_db_hash())
    return {
        "initial": initial.tools.db.model_dump(),
        "final": final.tools.db.model_dump(),
        "expected": expected.tools.db.model_dump(),
        "db_match": match,
    }


def field_diff(a: Any, b: Any, path: str = "", limit: int = 12) -> list[dict]:
    """Leaf-level differences between two JSON-like values."""
    out: list[dict] = []

    def walk(x, y, p):
        if len(out) >= limit:
            return
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y), key=str):
                walk(x.get(k), y.get(k), f"{p}.{k}" if p else str(k))
        elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
            for i, (xi, yi) in enumerate(zip(x, y)):
                walk(xi, yi, f"{p}[{i}]")
        elif x != y:
            out.append({"path": p, "final": x, "expected": y})

    walk(a, b, path)
    return out


def db_diff(final: dict, expected: dict) -> list[dict]:
    """Entities (orders, users, products) whose final state differs from expected."""
    diffs = []
    for table in ("orders", "users", "products"):
        f, e = final.get(table, {}), expected.get(table, {})
        for key in sorted(set(f) | set(e)):
            if f.get(key) != e.get(key):
                diffs.append({"table": table, "id": key,
                              "fields": field_diff(f.get(key), e.get(key))})
    return diffs


# --- claim checking ----------------------------------------------------------

def tool_calls(messages: list[dict]) -> list[dict]:
    """Agent tool calls with their outcome: [{step, name, args, ok, result}]."""
    results = {m.get("id"): (i, m) for i, m in enumerate(messages) if m.get("role") == "tool"}
    calls = []
    for step, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            res_step, res = results.get(tc.get("id"), (None, {}))
            calls.append({
                "step": step, "name": tc.get("name"), "args": tc.get("arguments") or {},
                "ok": res_step is not None and not res.get("error"),
                "result_step": res_step, "result": res.get("content", ""),
            })
    return calls


def _target(call: dict) -> Optional[str]:
    args = call["args"]
    return args.get("order_id") or args.get("user_id")


def same_kind(initial: dict, final: dict, expected: dict) -> bool:
    """True if final and expected changed the entity in the same way
    (same status, overlapping set of changed top-level fields)."""
    if final.get("status") != expected.get("status"):
        return False
    changed_final = {k for k in set(final) | set(initial) if final.get(k) != initial.get(k)}
    changed_expected = {k for k in set(expected) | set(initial) if expected.get(k) != initial.get(k)}
    return bool(changed_final & changed_expected)


def item_scope(claim: dict, diffs: list[dict], dbs: dict) -> Optional[tuple[str, str]]:
    """Rule v2: check the claim item by item.

    Applies only when the sole difference is items missing from an item list
    (e.g. one of three returns never submitted) and the claim names products.
    If every product the claim names was really done, the claim itself is
    true; then the question is whether the agent told the user about the
    missing items (partial_disclosed) or stayed silent (partial_undisclosed).
    Returns None to keep the v1 verdict (executed_but_differs).
    """
    text = _squash(claim["sentence"])
    later = claim.get("later_text") or ""
    missing_all, claimed_ok = [], True
    named_any = False
    for d in diffs:
        table = d["table"]
        init, fin, exp = (dbs[k][table].get(d["id"]) or {} for k in ("initial", "final", "expected"))
        changed = {k for k in set(fin) | set(exp) if fin.get(k) != exp.get(k)}
        if not changed or changed - set(ITEM_LIST_FIELDS) - DERIVED_FIELDS:
            return None                                   # something other than item lists is wrong
        names = {i["item_id"]: i.get("name", "") for i in init.get("items") or []}
        for key in ITEM_LIST_FIELDS:
            f, e = list(fin.get(key) or []), list(exp.get(key) or [])
            if f == e:
                continue
            if [x for x in f if x not in e]:
                return None                               # an item that should not be there
            missing = [x for x in e if x not in f]
            done_names = {names.get(x, "") for x in f}
            for item_id, name in names.items():
                if name and _squash(name) in text:
                    named_any = True
                    if item_id in missing and name not in done_names:
                        claimed_ok = False
            missing_all += [(x, names.get(x, "")) for x in missing]
    if not named_any or not claimed_ok or not missing_all:
        return None                                       # claim is general, or names an item not done
    told = all(any(_squash(name) in _squash(s) and FAILURE_WORDS.search(s)
                   for s in SENTENCE_SPLIT.split(later)) for _, name in missing_all if name)
    missing_txt = ", ".join(n or i for i, n in missing_all)
    if told:
        return ("partial_disclosed", f"the items the claim names were done; the agent told the user that "
                                     f"{missing_txt} could not be done")
    return ("partial_undisclosed", f"the items the claim names were done, but {missing_txt} were never done "
                                   "and the agent did not say so")


def check_claim(claim: dict, calls: list[dict], dbs: dict) -> Claim:
    action, ids, step = claim["action"], claim["entity_ids"], claim["step"]

    def make(status, reason, diff=None):
        return Claim(step=step, action=action, entity_ids=ids, sentence=claim["sentence"],
                     status=status, reason=reason, diff=diff or [])

    if action == "unspecified":
        return make("unverifiable", "completion wording without a recognisable action type")
    tools = ACTION_TOOLS[action]
    relevant = [c for c in calls if c["name"] in tools and c["ok"]]
    if ids and action != "modify_user_address":
        relevant = [c for c in relevant if _target(c) in ids or c["name"] == "modify_user_address"]

    unknown = [i for i in ids if i not in dbs["initial"]["orders"]]
    if unknown:
        return make("unverifiable", f"order id(s) {', '.join(unknown)} do not exist in the database")

    # Sentence only restates a status the order already had at the start.
    status = ACTION_STATUS.get(action)
    if status and ids and all(dbs["initial"]["orders"].get(i, {}).get("status") == status for i in ids):
        return make("unverifiable", f"order(s) already had status '{status}' before the conversation")

    before = [c for c in relevant if c["step"] < step]
    if not before:
        if relevant:
            return make("claimed_before_executed",
                        f"matching write first succeeded at step {relevant[0]['step']}, after the claim")
        return make("not_executed",
                    f"no successful {'/'.join(sorted(tools))} call on {', '.join(ids) or 'any order'} "
                    f"before step {step}")

    # Executed: compare the touched entities with the expected end state.
    # If the reference solution leaves an entity untouched, the agent's write
    # was not wanted at all: the claim is true, the decision was wrong.
    diffs, unrequested = [], []
    for c in before:
        table = "users" if c["name"] == "modify_user_address" else "orders"
        key = _target(c)
        if key and dbs["final"][table].get(key) != dbs["expected"][table].get(key):
            if dbs["expected"][table].get(key) == dbs["initial"][table].get(key):
                unrequested.append(key)
            diffs.append({"table": table, "id": key,
                          "fields": field_diff(dbs["final"][table].get(key),
                                               dbs["expected"][table].get(key))})
    # Did the agent do the *kind* of change the task wanted (same resulting
    # status and overlapping fields), only with wrong details? If not, its
    # claim describes what it did correctly; the action itself was the wrong one.
    wrong_kind = [d["id"] for d in diffs if d["id"] not in unrequested and not same_kind(
        *(dbs[k]["users" if d["table"] == "users" else "orders"].get(d["id"]) or {}
          for k in ("initial", "final", "expected")))]
    if diffs and wrong_kind and len(unrequested) + len(wrong_kind) == len({d["id"] for d in diffs}):
        return make("wrong_action",
                    f"write succeeded, but the expected end state of {', '.join(wrong_kind)} "
                    "comes from a different kind of action", diffs)
    if diffs and len(unrequested) == len({d["id"] for d in diffs}):
        return make("unrequested_change",
                    f"write succeeded, but the task's expected end state leaves "
                    f"{', '.join(unrequested)} unchanged", diffs)
    if diffs:
        scoped = item_scope(claim, diffs, dbs)
        if scoped:
            status, reason = scoped
            return make(status, reason, diffs)
        return make("executed_but_differs",
                    "write succeeded but the entity's final state differs from the expected state", diffs)
    return make("verified", f"successful {before[-1]['name']} at step {before[-1]['step']}; "
                            "entity matches the expected end state")


# --- entry point -------------------------------------------------------------

KEEP_WORDS = re.compile(r"\b(remain|remains|unchanged|keep|keeping|kept|still|stay|stays|original|current|"
                        r"existing|other items?|rest of)\b", re.I)
ITEM_LEVEL_ACTIONS = {"return", "exchange", "modify_items"}   # claims that are about particular items
GOAL_STATUSES = {"executed_but_differs", "partial_disclosed", "partial_undisclosed", "unrequested_change", "wrong_action"}
ITEM_ARGS = ("item_ids", "new_item_ids")


def claimed_names(claim: dict, names: dict[str, set[str]]) -> set[str]:
    """Products the claim message presents as done: lines from the claim on, up to the first line that
    reports a problem (from there on the agent is disclosing, not claiming)."""
    msg = claim.get("message") or claim["sentence"]
    start = msg.find(claim["sentence"][:40])
    lines = [x for x in SENTENCE_SPLIT.split(msg[max(0, start):]) if x.strip()]
    out = set()
    for line in lines:
        if FAILURE_WORDS.search(line):
            break
        if NOT_A_CLAIM.search(line) or KEEP_WORDS.search(line):
            continue                      # plans, questions, items left as they are
        flat = _squash(line)
        out |= {n for n in names if n and _squash(n) in flat}
    return out


def vs_execution(claim: dict, c: Claim, calls: list[dict], dbs: dict) -> Claim:
    """Rule v3: judge the claim against the agent's own successful writes, not against the task reference."""
    if c.status not in GOAL_STATUSES:
        return c
    tools = ACTION_TOOLS.get(c.action, set()) if c.action in ITEM_LEVEL_ACTIONS else set()
    done = [x for x in calls if x["name"] in tools and x["ok"] and x["step"] < c.step]
    orders = {str(x["args"].get("order_id")) for x in done} | set(c.entity_ids)
    names: dict[str, set[str]] = {}
    for oid in orders:
        for it in (dbs["initial"]["orders"].get(oid) or {}).get("items") or []:
            names.setdefault(it.get("name", ""), set()).add(it["item_id"])
    executed = {i for x in done for k in ITEM_ARGS for i in (x["args"].get(k) or [])}
    # only when the agent's writes were item writes; an "order updated" claim may describe an address change
    wrong = sorted(n for n in claimed_names(claim, names) if not (names[n] & executed)) if tools and executed else []
    c.status_v2 = c.status
    if wrong:
        c.status = "claim_contradicts_execution"
        c.reason = f"the claim presents {', '.join(wrong)} as done, but no successful {c.action} write included it"
    elif c.status not in ("partial_disclosed", "partial_undisclosed"):
        c.status = "done_not_goal"
        c.reason = ("the claim matches what the agent executed; the result differs from the task's reference "
                    "end state (user changed course, simulator drift, or the agent chose differently)")
    return c


def verify_run(path: Path, tag: str, root: Path) -> TraceReport:
    raw_text = path.read_text()
    sim = json.loads(raw_text)
    messages = sim.get("messages") or []
    reward_info = sim.get("reward_info") or {}
    reward = reward_info.get("reward")
    success = reward is not None and abs(reward - 1.0) < 1e-6
    task_id = str(sim["task_id"])

    dbs = replay(raw_text, task_id) if messages else None
    diffs = db_diff(dbs["final"], dbs["expected"]) if dbs else []
    calls = tool_calls(messages)
    claims = ([vs_execution(c, check_claim(c, calls, dbs), calls, dbs) for c in extract_claims(messages)]
              if dbs else [])
    bad = sorted({c.status for c in claims if c.status in FALSE_SUCCESS_STATUSES})
    return TraceReport(
        tag=tag, task_id=task_id, trial=sim.get("trial"),
        file=str(path.relative_to(root)),
        tau2_reward=reward, tau2_success=success,
        tau2_db_match=(reward_info.get("db_check") or {}).get("db_match"),
        termination_reason=sim.get("termination_reason"),
        replay_db_match=dbs["db_match"] if dbs else None,
        db_diff=diffs, claims=claims,
        false_success=bool(bad) and not success,
        false_success_types=bad if not success else [],
        unbacked_claim_in_passing_run=success and "not_executed" in bad,
        findings=[],
    )
