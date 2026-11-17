"""Shared data structures for triage results.

Every statement TraceCheck makes is tagged with what kind of knowledge it is:

- ``observed``  - read directly from the trajectory or the replayed database
- ``inference`` - a judgement (by a rule heuristic or, in phase 3, by a model)
- ``needs_verification`` - the rules could not decide; a human should look

Layers 1 and 2 (verify.py, rules.py) only produce ``observed`` facts and
``needs_verification`` items; ``inference`` is reserved for the phase-3
investigator. Keyword-based rules that can misfire say so in ``basis``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

Knowledge = Literal["observed", "inference", "needs_verification"]
Severity = Literal["violation", "warning", "info"]

# Status of one "I did X" claim made by the agent.
ClaimStatus = Literal[
    "verified",                # matching write succeeded and the entity ends as expected
    "not_executed",            # no successful matching write before the claim
    "executed_but_differs",    # write happened, but the entity differs from the expected end state
    "unrequested_change",      # write happened on an entity the expected end state leaves untouched
                               # (claim is true; the decision to act was wrong - not a false success)
    "wrong_action",            # write happened, but the task needed a different kind of change
                               # (e.g. return instead of exchange) - claim true, decision wrong
    "claimed_before_executed", # write happened only after the claim
    "unverifiable",            # rules cannot map the claim to an entity / action
]
FALSE_SUCCESS_STATUSES = ("not_executed", "executed_but_differs")


@dataclass
class Evidence:
    step: int        # index into the trajectory's ``messages`` list
    role: str        # assistant / user / tool
    text: str        # quoted snippet (trimmed)


@dataclass
class Finding:
    """One rule hit (layer 2) or one checked claim (layer 1)."""

    rule_id: str
    layer: Literal["verify", "rules"]
    severity: Severity
    knowledge: Knowledge
    step: Optional[int]
    message: str                       # one-line, human readable
    evidence: list[Evidence] = field(default_factory=list)
    policy_quote: Optional[str] = None # original policy sentence the rule enforces
    basis: str = "structural"          # "structural" (exact) or "keyword" (heuristic)
    details: dict = field(default_factory=dict)


@dataclass
class Claim:
    step: int
    action: str                     # cancel / return / exchange / modify_items / ...
    entity_ids: list[str]           # order ids (or user id) the claim refers to
    sentence: str
    status: ClaimStatus
    reason: str
    diff: list[dict] = field(default_factory=list)  # field diffs vs expected end state


@dataclass
class TraceReport:
    tag: str
    task_id: str
    trial: int
    file: str
    tau2_reward: Optional[float]
    tau2_success: bool
    tau2_db_match: Optional[bool]
    termination_reason: str
    replay_db_match: Optional[bool]       # our own replay; should agree with tau2_db_match
    db_diff: list[dict]                    # entity-level differences, final vs expected
    claims: list[Claim]
    false_success: bool                    # tau2 failure + at least one contradicted claim
    false_success_types: list[str]
    unbacked_claim_in_passing_run: bool    # tau2 success, but a claim had no matching write
    findings: list[Finding]

    def to_dict(self) -> dict:
        return asdict(self)


# --- phase 3: investigator output -------------------------------------------

CATEGORIES = [  # AgentRx taxonomy (github.com/microsoft/agentrx, MIT licence)
    "Instruction/Plan Adherence Failure", "Invention of New Information", "Invalid Invocation",
    "Misinterpretation of Tool Output", "Intent-Plan Misalignment", "Underspecified User Intent",
    "Intent Not Supported", "Guardrails Triggered", "System Failure", "Inconclusive",
]


@dataclass
class Diagnosis:
    traj_id: str
    arm: str                            # A / B / C
    prompt_version: str
    critical_step: Optional[int]
    failed_agent: Optional[str]         # "assistant" or "user" (the simulated user can be at fault)
    category: Optional[str]
    evidence: list[dict]                # [{step, quote, valid}] - valid = quote found verbatim in that step
    observed_facts: list[str]
    inference: list[str]
    needs_verification: list[str]
    confidence: Optional[float]
    abstain: bool                       # True -> shown as "需要人工判断"
    abstain_reason: str = ""
    summary: str = ""
    model: str = ""
    error: str = ""                     # parse / API problem, if any
    samples: list = field(default_factory=list)  # arm C: the individual answers that were voted on
