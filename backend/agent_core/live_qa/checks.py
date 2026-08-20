"""Deterministic FPC checks. No I/O, no Azure, no raises.

Each check returns a Finding or None. None means the check had no opportunity
to apply — not a pass, not a fail. The scorer treats that as a neutral 3 so a
call that never discussed dues is not punished for skipping Mini-Miranda.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from contact_policy import RBI_VOICE_END, RBI_VOICE_START

SCHEMA_VERSION = "live_qa.v1"

ACTION_NONE = "none"
ACTION_LISTEN = "listen"
ACTION_WHISPER = "whisper"
ACTION_BARGE = "barge"
ACTION_INBOX = "inbox"

VERDICT_PASS = "pass"
VERDICT_SOFT = "fail_soft"
VERDICT_CRITICAL = "fail_critical"

# Amount / dues language the bot must not speak to a third party or before
# identity. Deliberately requires a currency marker or a collections noun so
# "I'll wait a minute" does not trip it.
_DUES_RE = re.compile(
    r"(?:₹\s*[\d,]+|(?:\d[\d,]{2,})\s*(?:rupees|rs\.?)|"
    r"\b(?:outstanding|overdue|emi|minimum due|bounce charge|late fee)\b)",
    re.I,
)

_MIRANDA_RE = re.compile(
    r"(?:this (?:call|message) is (?:an attempt )?to collect|"
    r"attempt to collect (?:a )?debt|"
    r"this is a collections? (?:call|message)|"
    r"calling (?:you )?(?:about|regarding) (?:your )?(?:loan|account|emi)|"
    r"mini[\s-]?miranda)",
    re.I,
)

_OPT_OUT_RE = re.compile(
    r"\b(?:stop calling|don't call|do not call|dnd|"
    r"remove (?:me|my number)|opt(?:ed)? out|unsubscribe)\b",
    re.I,
)

_PAYMENT_PUSH_RE = re.compile(
    r"\b(?:pay now|make (?:the |a )?payment|outstanding|overdue|emi due|"
    r"pay[\s-]?link|minimum due)\b",
    re.I,
)


@dataclass(frozen=True)
class TurnFacts:
    """What one turn knows. Unknown is absent, not zero."""

    channel: str = "voice"
    bot_text: str = ""
    customer_text: str = ""
    turn_index: int = 0
    elapsed_seconds: float = 0.0
    identity_verified: bool = False
    third_party: bool = False
    now_hour: int | None = None
    #: Who placed the call. The RBI calling-window rule governs *contact
    #: attempts* — a bank must not ring a borrower after 19:00. It says nothing
    #: about answering one who rang you, and refusing to serve an inbound caller
    #: at 20:00 would be the worse outcome. Unknown stays "outbound" so a caller
    #: that has not been taught to set this keeps the stricter behaviour.
    direction: str = "outbound"
    #: A rehearsal, not a contact. Sandbox and eval traffic reaches no customer,
    #: so no contact rule can be breached by it.
    simulated: bool = False
    recording_disclosed: bool = False
    miranda_disclosed: bool = False
    hardship_hold: bool = False
    legal_hold: bool = False
    guardrail_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Finding:
    check_id: str
    criterion_id: str
    rule_id: str | None
    flag: str
    passed: bool
    critical: bool
    score: float
    action: str
    reason: str
    note: str

    def to_log(self) -> dict[str, object]:
        return {
            "checkId": self.check_id,
            "criterionId": self.criterion_id,
            "ruleId": self.rule_id,
            "flag": self.flag,
            "passed": self.passed,
            "critical": self.critical,
            "score": self.score,
            "action": self.action,
            "reason": self.reason,
        }


def _fail(
    *,
    check_id: str,
    criterion_id: str,
    rule_id: str | None,
    flag: str,
    critical: bool,
    action: str,
    reason: str,
    note: str,
) -> Finding:
    return Finding(
        check_id=check_id,
        criterion_id=criterion_id,
        rule_id=rule_id,
        flag=flag,
        passed=False,
        critical=critical,
        score=0.0,
        action=action,
        reason=reason,
        note=note,
    )


def mentions_dues(text: str) -> bool:
    return bool(_DUES_RE.search(text or ""))


def _channel_action(facts: TurnFacts, voice_action: str) -> str:
    if (facts.channel or "voice").lower() in {"whatsapp", "sms", "chat", "email"}:
        if voice_action == ACTION_BARGE:
            return ACTION_INBOX
        if voice_action in {ACTION_LISTEN, ACTION_WHISPER}:
            return ACTION_NONE
    return voice_action


def check_hours(facts: TurnFacts) -> Finding | None:
    """An *outbound* voice turn outside RBI 08:00–19:00 local.

    WhatsApp is not a call, an inbound call is not a contact attempt, and a
    simulated call reaches nobody. This used to flag any voice turn by the
    clock alone, so a sandbox rehearsal at 20:43 opened with a critical
    compliance breach on turn one — which then spent a high-severity
    self-correction before the caller had said anything.
    """
    if (facts.channel or "voice").lower() != "voice":
        return None
    if facts.simulated:
        return None
    if (facts.direction or "outbound").lower() != "outbound":
        return None
    if facts.now_hour is None:
        return None
    hour = int(facts.now_hour)
    if RBI_VOICE_START <= hour < RBI_VOICE_END:
        return None
    return _fail(
        check_id="hours-breach",
        criterion_id="cmp-dnd",
        rule_id="r-dnd-win",
        flag="hours-breach",
        critical=True,
        action=_channel_action(facts, ACTION_BARGE),
        reason="hours-breach",
        note="[live] Voice turn outside RBI 08:00–19:00 local",
    )


def check_recording(facts: TurnFacts) -> Finding | None:
    if "missing-recording-disclosure" in facts.guardrail_flags:
        return _fail(
            check_id="missing-recording-disclosure",
            criterion_id="cmp-recording",
            rule_id="r-rec",
            flag="missing-recording-disclosure",
            critical=True,
            action=ACTION_WHISPER,
            reason="missing-recording-disclosure",
            note="[live] Recording notice missing in the opening turns",
        )
    return None


def check_miranda(facts: TurnFacts) -> Finding | None:
    if facts.miranda_disclosed:
        return None
    if not mentions_dues(facts.bot_text):
        return None
    if _MIRANDA_RE.search(facts.bot_text or ""):
        return None
    return _fail(
        check_id="missing-mini-miranda",
        criterion_id="cmp-miranda",
        rule_id="r-mm",
        flag="missing-mini-miranda",
        critical=True,
        action=ACTION_WHISPER,
        reason="missing-mini-miranda",
        note="[live] Dues discussed without Mini-Miranda disclosure",
    )


def check_identity_before_dues(facts: TurnFacts) -> Finding | None:
    if facts.identity_verified or facts.third_party:
        return None
    if not mentions_dues(facts.bot_text):
        return None
    return _fail(
        check_id="identity-before-verify",
        criterion_id="scr-verify",
        rule_id="r-verify",
        flag="identity-before-verify",
        critical=True,
        action=_channel_action(facts, ACTION_BARGE),
        reason="identity-before-verify",
        note="[live] Account figures spoken before identity verification",
    )


def check_third_party(facts: TurnFacts) -> Finding | None:
    if not facts.third_party:
        return None
    if not mentions_dues(facts.bot_text):
        return None
    return _fail(
        check_id="third-party-leak",
        criterion_id="cmp-language",
        rule_id="r-third",
        flag="third-party-leak",
        critical=True,
        action=_channel_action(facts, ACTION_BARGE),
        reason="third-party-leak",
        note="[live] Account figures spoken to a third party",
    )


def check_opt_out(facts: TurnFacts) -> Finding | None:
    if not _OPT_OUT_RE.search(facts.customer_text or ""):
        return None
    if not _PAYMENT_PUSH_RE.search(facts.bot_text or ""):
        return None
    return _fail(
        check_id="opt-out-ignored",
        criterion_id="cmp-dnd",
        rule_id="r-dnd-disc",
        flag="opt-out-ignored",
        critical=True,
        action=_channel_action(facts, ACTION_BARGE),
        reason="opt-out-ignored",
        note="[live] Caller asked to stop contact; bot continued collecting",
    )


def check_guardrail_flags(facts: TurnFacts) -> list[Finding]:
    """Promote already-computed guardrail flags into FPC findings.

    The guardrail module owns detection. This only decides the rubric cell,
    the compliance rule, and whether a human takes the call now.
    """
    out: list[Finding] = []
    flags = facts.guardrail_flags
    if "authority-cap-exceeded" in flags:
        out.append(
            _fail(
                check_id="authority-cap-exceeded",
                criterion_id="cmp-language",
                rule_id="r-guarantee",
                flag="authority-cap-exceeded",
                critical=True,
                action=_channel_action(facts, ACTION_BARGE),
                reason="authority-cap-exceeded",
                note="[live] Quoted a waiver above the authority ceiling",
            )
        )
    if "waiver-blocked" in flags:
        out.append(
            _fail(
                check_id="waiver-blocked",
                criterion_id="cmp-language",
                rule_id="r-guarantee",
                flag="waiver-blocked",
                critical=True,
                action=ACTION_WHISPER,
                reason="waiver-blocked",
                note="[live] Promised a waiver the matrix did not approve",
            )
        )
    if "auto-escalate" in flags:
        out.append(
            _fail(
                check_id="auto-escalate",
                criterion_id="cmp-language",
                rule_id=None,  # caller conduct — persist already skips a bot violation
                flag="auto-escalate",
                critical=True,
                action=_channel_action(facts, ACTION_BARGE),
                reason="auto-escalate",
                note="[live] Legal threat or abuse — specialist now",
            )
        )
    if any(f.startswith("prohibited:") for f in flags):
        term = next(f for f in flags if f.startswith("prohibited:"))
        out.append(
            _fail(
                check_id=term,
                criterion_id="cmp-language",
                rule_id=None,  # persist.rule_for_flag classifies the term
                flag=term,
                critical=True,
                action=ACTION_WHISPER,
                reason=term,
                note=f"[live] Prohibited language ({term.split(':', 1)[-1]})",
            )
        )
    if "rate-quoted" in flags:
        out.append(
            _fail(
                check_id="rate-quoted",
                criterion_id="cmp-language",
                rule_id="r-false",
                flag="rate-quoted",
                critical=True,
                action=ACTION_WHISPER,
                reason="rate-quoted",
                note="[live] Quoted an interest rate / APR on a collections turn",
            )
        )
    return out


def evaluate_turn(facts: TurnFacts) -> tuple[Finding, ...]:
    """Run every check. Order is the Floor's: hours, leak, identity, then rest."""
    found: list[Finding] = []
    for fn in (
        check_hours,
        check_third_party,
        check_identity_before_dues,
        check_recording,
        check_miranda,
        check_opt_out,
    ):
        hit = fn(facts)
        if hit is not None:
            found.append(hit)
    found.extend(check_guardrail_flags(facts))
    # De-dup by check_id, first writer wins.
    seen: set[str] = set()
    out: list[Finding] = []
    for f in found:
        if f.check_id in seen:
            continue
        seen.add(f.check_id)
        out.append(f)
    return tuple(out)


def worst_action(findings: Sequence[Finding], *, channel: str) -> str:
    rank = {
        ACTION_NONE: 0,
        ACTION_LISTEN: 1,
        ACTION_WHISPER: 2,
        ACTION_INBOX: 3,
        ACTION_BARGE: 4,
    }
    action = ACTION_NONE
    for f in findings:
        if rank.get(f.action, 0) > rank.get(action, 0):
            action = f.action
    if channel in {"whatsapp", "sms", "chat", "email"} and action == ACTION_BARGE:
        return ACTION_INBOX
    return action


def verdict_of(findings: Sequence[Finding]) -> str:
    if any(f.critical and not f.passed for f in findings):
        return VERDICT_CRITICAL
    if any(not f.passed for f in findings):
        return VERDICT_SOFT
    return VERDICT_PASS


def facts_to_log(facts: TurnFacts) -> dict[str, object]:
    return {
        "channel": facts.channel,
        "turnIndex": facts.turn_index,
        "identityVerified": facts.identity_verified,
        "thirdParty": facts.third_party,
        "nowHour": facts.now_hour,
        "hardshipHold": facts.hardship_hold,
        "legalHold": facts.legal_hold,
        "guardrailFlags": list(facts.guardrail_flags),
    }


def local_hour(now: datetime | None) -> int | None:
    if now is None:
        return None
    return now.hour
