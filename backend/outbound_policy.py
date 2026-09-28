"""The tenant's outbound policy: which missions the dialler runs and how.

Per objective: where the conversation starts, how long it may run, what
counts as success, what the agent may offer, the voicemail rule. Per cadence:
attempts, backoff and what stops or retries a case. Per outcome: the post-call
actions. Plus the caller-ID pool, carrier AMD and QA sampling.

This used to be the ``outbound`` block of a legacy agent card, read on every
dial from the published prompt version. Voice Studio agents have no card, so
the policy is PayInt's own. Its values are ``policy/outbound.json``, taken
from the card production dialled under (kaia-v2-4, 2026-09-28), and validated
here on load: an unknown key or an out-of-range value fails loudly rather
than dialling under a policy nobody wrote.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

POLICY_FILE = Path(__file__).resolve().parent / "policy" / "outbound.json"

Direction = Literal["inbound", "outbound", "both"]

#: Mirrors ``flow_graph.OBJECTIVES``. The graph owns the vocabulary because the
#: graph is what has to contain a matching entry node; this restates it as a
#: Literal so a card with a typo fails at parse rather than at dial time.
Objective = Literal[
    "inbound",
    "pre_due_reminder",
    "bounce_cure",
    "dpd_reminder",
    "broken_ptp_chase",
    "hardship_intake",
    "mandate_reregistration",
    "document_chase",
    "callback_honour",
    "welcome_onboarding",
    "retention_save",
    "cross_sell",
    "manual_outbound",
]

VoicemailMode = Literal["always", "never", "first_attempt_only", "engine"]
PoolKind = Literal["service_1600", "promotional", "general"]


class VoicemailPolicy(BaseModel):
    """What to do when a machine answers. Silence is a decision too.

    ``include_grievance_contact`` is not a nicety. A voicemail is a recovery
    communication, and RBI para 100AA requires the grievance officer's details
    in all of them — so a message that only says "please call us back" is a
    communication made without a disclosure that was owed.
    """

    model_config = ConfigDict(extra="forbid")

    leave: VoicemailMode = "first_attempt_only"
    max_sec: int = Field(default=25, ge=5, le=60)
    include_grievance_contact: bool = True


class CardObjective(BaseModel):
    """One mission this agent can be sent on."""

    model_config = ConfigDict(extra="forbid")

    key: Objective
    #: Node key in ``prompt_versions.flow`` whose ``entryFor`` claims this
    #: mission. Compile gate G-OB2 checks the two agree.
    entry_node: str = ""
    #: Outcome codes from the Closer's taxonomy that close the case.
    success: list[str] = Field(default_factory=list)
    partial: list[str] = Field(default_factory=list)
    max_duration_sec: int = Field(default=240, ge=30, le=1800)
    #: Empty means no product may be mentioned on this mission at all. That is
    #: the safe default rather than an omission: a servicing call is not a sales
    #: call, and the borrower did not ask to be sold to.
    allowed_offers: list[str] = Field(default_factory=list)
    #: Named cap set in agent_core.authority. A broken-PTP chase may concede
    #: more than a pre-due nudge, and that is an authored difference.
    authority_profile: str | None = None
    voicemail: VoicemailPolicy = Field(default_factory=VoicemailPolicy)
    cadence: str = "default"


class CardCadence(BaseModel):
    """When to try again. Mechanical, and never a decision about the action.

    Cadence may retry the *same* action. Only the treatment engine may change
    the action — that boundary is what stops a dialler quietly inventing an
    escalation ladder of its own.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = "default"
    max_attempts: int = Field(default=3, ge=1, le=10)
    #: Per borrower per day for this mission. Bounded again at runtime by
    #: contact_policy's own cap, which a card can only ever lower.
    per_day: int = Field(default=1, ge=1, le=5)
    #: Hours to wait before attempt 2, 3, ... A shorter list repeats its last
    #: value rather than falling off the end.
    backoff_hours: list[int] = Field(default_factory=lambda: [4, 24, 72])
    retry_on: list[str] = Field(
        default_factory=lambda: [
            "no_answer",
            "busy",
            "voicemail_left",
            "voicemail_skipped",
        ]
    )
    #: Terminal for the case whatever the attempt count says.
    stop_on: list[str] = Field(
        default_factory=lambda: [
            "ptp_captured",
            "ptp_recommitted",
            "paid_in_call",
            "dispute_raised",
            "opt_out_requested",
            "wrong_number",
            "deceased",
        ]
    )
    #: bot_id on the handoff allowlist, or "human". Where the case goes when the
    #: attempts run out.
    escalate_to: str | None = None


class PostCallRule(BaseModel):
    """One outcome code and what it triggers, versioned with the agent."""

    model_config = ConfigDict(extra="forbid")

    when: str
    do: list[str] = Field(default_factory=list)


class CardPostCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on_outcome: list[PostCallRule] = Field(default_factory=list)
    #: Send the borrower a written record of what was agreed.
    written_followup: bool = True
    #: Honour promises the agent made on the call.
    obligations: bool = True
    qa: Literal["always", "sampled", "never"] = "always"


class CardOutbound(BaseModel):
    """Everything about being the one who dialled.

    ``direction`` defaults to ``inbound`` so every card that exists today keeps
    exactly the behaviour it has: no objectives, no cadence, no dialling.
    """

    model_config = ConfigDict(extra="forbid")

    direction: Direction = "inbound"
    objectives: list[CardObjective] = Field(default_factory=list)
    cadences: list[CardCadence] = Field(default_factory=list)
    post_call: CardPostCall = Field(default_factory=CardPostCall)
    #: Which caller-ID pool this agent dials from. A service-only pool
    #: (TRAI 1600 series) forbids promotional content — compile gate G-OB4.
    number_pool: str | None = None
    pool_kind: PoolKind = "general"
    #: Slots reserved out of the outbound fleet gate, so a cross-sell campaign
    #: cannot starve the bounce-cure queue. 0 means "share the general pool".
    #: Ask the carrier for an answering-machine verdict as a second signal
    #: alongside Pipecat's in-band detector.
    carrier_amd: bool = False
    #: Drive DTMF through a workplace switchboard to reach a human.
    ivr_traversal: bool = False
    ivr_max_sec: int = Field(default=90, ge=15, le=300)

    def objective(self, key: str) -> CardObjective | None:
        return next((o for o in self.objectives if o.key == key), None)

    def cadence_for(self, key: str) -> CardCadence:
        """The cadence an objective names, or a conservative default.

        Never None: a missing cadence must not read as "retry forever". G-OB8
        stops a card being published that names a cadence it does not define,
        so this fallback only ever covers the un-authored case.
        """
        objective = self.objective(key)
        name = objective.cadence if objective else "default"
        return next((c for c in self.cadences if c.name == name), CardCadence())

    @property
    def dials(self) -> bool:
        return self.direction in ("outbound", "both")


@lru_cache(maxsize=1)
def current() -> CardOutbound:
    """The outbound policy every Voice Studio agent dials under."""
    return CardOutbound.model_validate(json.loads(POLICY_FILE.read_text(encoding="utf-8")))


class PolicyCard:
    """What the dialler's call sites read from a "card": only ``outbound``."""

    def __init__(self, outbound: CardOutbound) -> None:
        self.outbound = outbound


if __name__ == "__main__":
    policy = current()
    assert policy.dials and policy.objective("dpd_reminder") is not None
    assert policy.cadence_for("broken_ptp_chase").backoff_hours == [4, 24, 72]
    assert policy.objective("pre_due_reminder").max_duration_sec == 180
    assert policy.post_call.qa == "always" and not policy.carrier_amd
    print("ok", [o.key for o in policy.objectives])
