"""Registry of agent versions. Add a version = add an AgentSpec here.

Phase 4 variants each differ from v1 in one place (see ``changed``), so a
regression or a fix can be traced back to a single, reviewable edit.
"""

from __future__ import annotations

from agent.base import INSTRUCTIONS_V1, AgentSpec

V1 = AgentSpec(
    name="v1",
    description="Baseline: plain tool-calling agent with the unmodified retail policy.",
)

# --- planted bugs (phase 4) ----------------------------------------------------

AUTH_SENTENCE = ("At the beginning of the conversation, you have to authenticate the user identity by "
                 "locating their user id via email, or via name + zip code. This has to be done even when "
                 "the user already provides the user id.")


def _remove(sentence: str):
    def transform(policy: str) -> str:
        if sentence not in policy:
            raise ValueError(f"policy no longer contains: {sentence[:60]}...")
        return policy.replace(sentence, "")
    return transform


BUG_AUTH = AgentSpec(
    name="bug_auth",
    description="Bug 1 (policy rule deleted): the authentication rule is removed from the policy.",
    policy_transform=_remove(AUTH_SENTENCE),
)

BUG_TRANSFER = AgentSpec(
    name="bug_transfer",
    description="Bug 2 (vague tool description): transfer_to_human_agents loses its 'only transfer if' conditions.",
    tool_descriptions={"transfer_to_human_agents": "Transfer the user to a human agent, with a summary of the user's issue."},
)

CONFIRM_POLICY = ("Before taking any action that updates the database (cancel, modify, return, exchange), you "
                  "must list the action details and obtain explicit user confirmation (yes) to proceed.")
CONFIRM_INSTRUCTION = (" Before any\ntool call that changes the database, list the details of the change and wait\n"
                       "for the user to explicitly confirm.")
assert CONFIRM_INSTRUCTION in INSTRUCTIONS_V1

BUG_NOCONFIRM = AgentSpec(
    name="bug_noconfirm",
    description="Bug 3 (confirmation requirement removed): the 'confirm before writing' rule is deleted from "
                "the system prompt (the policy sentence and the same sentence in our instructions). "
                "Tool descriptions, written by the tool provider, still mention it.",
    instructions=INSTRUCTIONS_V1.replace(CONFIRM_INSTRUCTION, "").rstrip(),
    policy_transform=_remove(CONFIRM_POLICY),
)

BUG_PARAM = AgentSpec(
    name="bug_param",
    description="Bug 4 (wrong parameter description): modify_pending_order_items.new_item_ids is described "
                "as product ids instead of item ids.",
    param_descriptions={"modify_pending_order_items": {
        "new_item_ids": "The product ids of the new products, each such as '1008292230' (the product_id "
                        "returned by get_product_details). Each one should match the item id in the same position."}},
)

# --- fix (phase 4) ----------------------------------------------------------------
# Target: the most frequent agent-side problem in the phase-3 diagnoses of v1
# failures (Instruction/Plan Adherence Failure): not searching the user's orders,
# transferring to a human too early, dropping one of several requests.

INSTRUCTIONS_V2 = INSTRUCTIONS_V1 + """

Before giving up on any request:
- If the user cannot give an order id, or an item is not in the order you
  looked at, use get_user_details and get_order_details to search all of
  the user's orders yourself before asking again.
- Keep a list of every request the user has made. Handle each one (or tell
  the user clearly why the policy does not allow it) before ending.
- Transfer to a human agent only if the user explicitly asks for one, or the
  request is outside what the policy and tools allow - never just because a
  lookup failed or the conversation is difficult."""

V2 = AgentSpec(
    name="v2",
    description="Fix: v1 + three instructions against the most frequent agent-side failures "
                "(search the user's orders, track every request, transfer only when required).",
    instructions=INSTRUCTIONS_V2,
)

SPECS: dict[str, AgentSpec] = {spec.name: spec for spec in [V1, BUG_AUTH, BUG_TRANSFER, BUG_NOCONFIRM, BUG_PARAM, V2]}


def registered_name(version: str) -> str:
    return f"tracecheck_{version}"


def register_all() -> None:
    """Register every version with tau2 as agent ``tracecheck_<name>``."""
    from tau2.registry import registry

    from agent.base import TraceCheckAgent

    existing = set(registry.get_agents()) if hasattr(registry, "get_agents") else set()
    for spec in SPECS.values():
        name = registered_name(spec.name)
        if name in existing:
            continue

        def factory(tools, domain_policy, _spec=spec, **kwargs):
            return TraceCheckAgent(tools=tools, domain_policy=domain_policy, spec=_spec,
                                   llm=kwargs.get("llm"), llm_args=kwargs.get("llm_args"))

        registry.register_agent_factory(factory, name)
