"""The agent under test.

One class, configured by an ``AgentSpec``. v1, the bug variants (phase 4) and
the fix v2 are all specs that differ from v1 in exactly one field, so "what
changed between versions" is always a small, reviewable diff of data.

The agent is deliberately plain: a system prompt (instructions + the retail
policy), the tau2 tools, and one LLM call per turn. No planning, no memory,
no self-checking - a normal-strength baseline that fails often enough to
give the triage layers something to analyse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from pydantic import BaseModel
from tau2.agent.base.llm_config import LLMConfigMixin
from tau2.agent.base_agent import HalfDuplexAgent, ValidAgentInputMessage
from tau2.data_model.message import (
    APICompatibleMessage, AssistantMessage, Message, MultiToolMessage, SystemMessage,
)
from tau2.utils.llm_utils import generate

INSTRUCTIONS_V1 = """
You are a customer service agent for an online retail store. Help the user
according to the policy below.

In each turn you do exactly one of two things:
- send a message to the user, or
- make one tool call.
Never do both in the same turn.

Only state things you learned from the user or from tool results. Before any
tool call that changes the database, list the details of the change and wait
for the user to explicitly confirm.
""".strip()

SYSTEM_TEMPLATE = """
<instructions>
{instructions}
</instructions>
<policy>
{policy}
</policy>
""".strip()


@dataclass(frozen=True)
class AgentSpec:
    """Everything that defines one agent version."""

    name: str
    description: str
    instructions: str = INSTRUCTIONS_V1
    # Edits applied to the policy text before it goes into the prompt.
    policy_transform: Optional[Callable[[str], str]] = None
    # {tool_name: new description} - replaces the tool's description.
    tool_descriptions: dict[str, str] = field(default_factory=dict)
    # {tool_name: {param_name: new description}} - replaces a parameter description.
    param_descriptions: dict[str, dict[str, str]] = field(default_factory=dict)

    def build_system_prompt(self, domain_policy: str) -> str:
        policy = self.policy_transform(domain_policy) if self.policy_transform else domain_policy
        return SYSTEM_TEMPLATE.format(instructions=self.instructions, policy=policy)


class PatchedTool:
    """A tau2 tool whose *advertised* schema is edited; execution is untouched.

    Only what the model reads changes (descriptions). The environment still
    runs the real tool, so a misleading description produces real mistakes.
    """

    def __init__(self, tool, description: Optional[str], params: dict[str, str]):
        self._tool = tool
        self._description = description
        self._params = params
        self.name = tool.name

    @property
    def openai_schema(self) -> dict:
        import copy

        schema = copy.deepcopy(self._tool.openai_schema)
        fn = schema["function"]
        if self._description is not None:
            fn["description"] = self._description
        props = fn.get("parameters", {}).get("properties", {})
        for param, text in self._params.items():
            if param not in props:
                raise KeyError(f"{self.name} has no parameter {param!r}")
            props[param]["description"] = text
        return schema

    def __getattr__(self, item):  # everything else behaves like the real tool
        return getattr(self._tool, item)


def patch_tools(tools: list, spec: AgentSpec) -> list:
    names = {t.name for t in tools}
    unknown = (set(spec.tool_descriptions) | set(spec.param_descriptions)) - names
    if unknown:
        raise KeyError(f"spec {spec.name!r} patches unknown tools: {sorted(unknown)}")
    out = []
    for tool in tools:
        desc = spec.tool_descriptions.get(tool.name)
        params = spec.param_descriptions.get(tool.name, {})
        out.append(PatchedTool(tool, desc, params) if (desc is not None or params) else tool)
    return out


class AgentState(BaseModel):
    system_messages: list[SystemMessage]
    messages: list[APICompatibleMessage]


class TraceCheckAgent(LLMConfigMixin, HalfDuplexAgent[AgentState]):
    """Turn-based tool-calling agent defined by an AgentSpec."""

    def __init__(self, tools, domain_policy: str, spec: AgentSpec, llm: str,
                 llm_args: Optional[dict] = None):
        super().__init__(tools=patch_tools(tools, spec), domain_policy=domain_policy,
                         llm=llm, llm_args=llm_args)
        self.spec = spec

    @property
    def system_prompt(self) -> str:
        return self.spec.build_system_prompt(self.domain_policy)

    def get_init_state(self, message_history: Optional[list[Message]] = None) -> AgentState:
        return AgentState(
            system_messages=[SystemMessage(role="system", content=self.system_prompt)],
            messages=list(message_history or []),
        )

    def generate_next_message(
        self, message: ValidAgentInputMessage, state: AgentState
    ) -> tuple[AssistantMessage, AgentState]:
        if isinstance(message, MultiToolMessage):
            state.messages.extend(message.tool_messages)
        else:
            state.messages.append(message)
        reply = generate(
            model=self.llm,
            tools=self.tools,
            messages=state.system_messages + state.messages,
            call_name="agent_response",
            **self.llm_args,
        )
        state.messages.append(reply)
        return reply, state
