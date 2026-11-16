"""Registry of agent versions. Add a version = add an AgentSpec here."""

from __future__ import annotations

from agent.base import AgentSpec, TraceCheckAgent

V1 = AgentSpec(
    name="v1",
    description="Baseline: plain tool-calling agent with the unmodified retail policy.",
)

SPECS: dict[str, AgentSpec] = {spec.name: spec for spec in [V1]}


def registered_name(version: str) -> str:
    return f"tracecheck_{version}"


def register_all() -> None:
    """Register every version with tau2 as agent ``tracecheck_<name>``."""
    from tau2.registry import registry

    existing = set(registry.get_agents()) if hasattr(registry, "get_agents") else set()
    for spec in SPECS.values():
        name = registered_name(spec.name)
        if name in existing:
            continue

        def factory(tools, domain_policy, _spec=spec, **kwargs):
            return TraceCheckAgent(tools=tools, domain_policy=domain_policy, spec=_spec,
                                   llm=kwargs.get("llm"), llm_args=kwargs.get("llm_args"))

        registry.register_agent_factory(factory, name)
