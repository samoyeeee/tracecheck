"""Tests for agent specs: prompt building and tool-description patching."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.base import AgentSpec, patch_tools  # noqa: E402
from agent.versions import SPECS  # noqa: E402


@pytest.fixture(scope="module")
def retail():
    from tau2.registry import registry
    env = registry.get_env_constructor("retail")()
    return env.get_tools(), env.get_policy()


def test_v1_prompt_contains_full_policy(retail):
    _, policy = retail
    prompt = SPECS["v1"].build_system_prompt(policy)
    assert policy in prompt and "explicitly confirm" in prompt


def test_policy_transform_is_applied(retail):
    _, policy = retail
    spec = AgentSpec("x", "", policy_transform=lambda p: p.replace("explicit user confirmation", "REMOVED"))
    assert "REMOVED" in spec.build_system_prompt(policy)


def test_patch_changes_only_the_advertised_schema(retail):
    tools, _ = retail
    spec = AgentSpec("x", "", tool_descriptions={"cancel_pending_order": "Vague."},
                     param_descriptions={"cancel_pending_order": {"reason": "Any text."}})
    patched = {t.name: t for t in patch_tools(tools, spec)}
    original = {t.name: t for t in tools}
    fn = patched["cancel_pending_order"].openai_schema["function"]
    assert fn["description"] == "Vague."
    assert fn["parameters"]["properties"]["reason"]["description"] == "Any text."
    assert original["cancel_pending_order"].openai_schema["function"]["description"] != "Vague."
    assert patched["get_order_details"] is original["get_order_details"]  # untouched tools pass through


def test_patch_rejects_unknown_names(retail):
    tools, _ = retail
    with pytest.raises(KeyError):
        patch_tools(tools, AgentSpec("x", "", tool_descriptions={"no_such_tool": "x"}))
    with pytest.raises(KeyError):
        bad = AgentSpec("x", "", param_descriptions={"cancel_pending_order": {"nope": "x"}})
        patch_tools(tools, bad)[0].openai_schema  # noqa: B018
        [t.openai_schema for t in patch_tools(tools, bad)]


def test_code_level_bugs_rewrite_only_the_targeted_arguments():
    from agent.versions import drop_address2, drop_last_item
    a = drop_address2("modify_user_address", {"address1": "1 Main", "address2": "Apt 3", "zip": "1"})
    assert a == {"address1": "1 Main", "address2": "", "zip": "1"}
    assert drop_address2("cancel_pending_order", {"address2": "x"}) == {"address2": "x"}
    r = drop_last_item("exchange_delivered_order_items",
                       {"order_id": "#W1", "item_ids": ["a", "b"], "new_item_ids": ["c", "d"]})
    assert r["item_ids"] == ["a"] and r["new_item_ids"] == ["c"]
    assert drop_last_item("return_delivered_order_items", {"item_ids": ["a"]}) == {"item_ids": ["a"]}
