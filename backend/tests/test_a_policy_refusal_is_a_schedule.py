"""A refusal about the clock is a schedule, not a failure.

`whatsapp_outbound` handed every `contact_policy` verdict to
`mark_failed_or_retry`, whose classifiers only understand the
`whatsapp_send_failed:*` vocabulary Meta produces. `cooling_off` matched none of
them, fell through to "attempt >= cap", and dead-lettered.

The arithmetic made it certain rather than unlucky: cooling-off is 120
**minutes**, and the retry ladder is five attempts with the backoff capped at
120 **seconds** — about 30 seconds of real waiting. The job could not survive to
the retry that would have succeeded. In the live queue, 18 of 29 outbound
messages were dead on `cooling_off`, and one more on `outside_allowed_window`.

Every sibling caller of `admit` already routed refusals away from that ladder.
This was the one that did not.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import contact_policy as cp
import whatsapp_outbound as wo

IST = ZoneInfo("Asia/Kolkata")


class _Conn:
    """Records the SQL a helper issues, without a database."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):  # noqa: ANN001
        self.calls.append((str(getattr(stmt, "text", stmt)), dict(params or {})))
        return None

    def sql(self) -> str:
        return " ".join(s for s, _ in self.calls)

    @property
    def last_params(self) -> dict:
        return self.calls[-1][1]


def _job(**over):
    base = {
        "id": "WAO-TEST",
        "attempt": 2,
        "purpose": "statutory",
        "created_at": datetime(2026, 9, 11, 6, 0, tzinfo=timezone.utc),
        "conversation_id": "CV-1",
    }
    base.update(over)
    return base


def _decision(reason: str, when: datetime | None):
    return cp.Decision(False, reason, next_allowed_at=when)


# ---------------------------------------------------------------------------
# The distinction the code had no way to express
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [cp.REASON_COOLING, cp.REASON_DAILY, cp.REASON_WEEKLY,
     cp.REASON_HOURS, cp.REASON_WINDOW, cp.REASON_WINDOW_DEFERRED_STATUTORY],
)
def test_a_clock_refusal_carries_a_deadline_and_is_deferrable(reason: str) -> None:
    d = _decision(reason, datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc))
    assert d.deferrable is True
    assert d.as_dict()["nextAllowedAt"].startswith("2026-09-11T12:00")


@pytest.mark.parametrize(
    "reason",
    [cp.REASON_CUSTOMER_DND, cp.REASON_OPTED_OUT, cp.REASON_CONSENT_OVERLAY,
     cp.REASON_SETTLED, cp.REASON_SUPPRESSED, cp.REASON_ENDPOINT],
)
def test_a_refusal_about_the_customer_is_never_deferrable(reason: str) -> None:
    """These do not expire. Retrying them is not patience, it is noise."""
    assert _decision(reason, None).deferrable is False
    # Even handed a deadline, the reason itself disqualifies it.
    assert _decision(reason, datetime.now(timezone.utc)).deferrable is False


def test_a_clock_refusal_with_no_deadline_is_not_deferrable() -> None:
    """Fail safe: without a computed instant there is nothing to schedule."""
    assert _decision(cp.REASON_COOLING, None).deferrable is False


# ---------------------------------------------------------------------------
# When does it stop being true
# ---------------------------------------------------------------------------


def _customer():
    return {"id": "c1", "allowed_hours": None, "allowed_days": None}


def test_cooling_off_clears_one_cooling_period_after_the_last_touch() -> None:
    last = datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc)
    when = cp._next_allowed(
        cp.REASON_COOLING,
        now_local=last.astimezone(IST),
        rules=None,
        channel="whatsapp",
        customer=_customer(),
        last_counted_at=last,
    )
    assert when == last + cp.cooling_off(None)
    # And that is well past anything the transport ladder could have reached.
    assert (when - last) > timedelta(seconds=480)


def test_a_daily_cap_clears_at_the_borrowers_local_midnight() -> None:
    now_local = datetime(2026, 9, 11, 20, 30, tzinfo=IST)
    when = cp._next_allowed(
        cp.REASON_DAILY, now_local=now_local, rules=None,
        channel="whatsapp", customer=_customer(),
    )
    assert when.astimezone(IST) == datetime(2026, 9, 12, 0, 0, tzinfo=IST)


def test_a_closed_window_reopens_at_the_next_opening() -> None:
    """21:00 IST is outside 08:00-19:00, so the next slot is tomorrow morning."""
    now_local = datetime(2026, 9, 11, 21, 0, tzinfo=IST)
    when = cp._next_allowed(
        cp.REASON_HOURS, now_local=now_local, rules=None,
        channel="whatsapp", customer=_customer(),
    )
    reopened = when.astimezone(IST)
    assert reopened.date() == datetime(2026, 9, 12).date()
    assert reopened > now_local


def test_the_window_deadline_respects_the_borrowers_allowed_days() -> None:
    """Friday night, and this borrower has only said Monday is fine."""
    now_local = datetime(2026, 9, 11, 21, 0, tzinfo=IST)  # a Friday
    customer = {"id": "c1", "allowed_hours": None, "allowed_days": "mon"}
    when = cp._next_allowed(
        cp.REASON_WINDOW, now_local=now_local, rules=None,
        channel="whatsapp", customer=customer,
    ).astimezone(IST)
    assert when.isoweekday() == 1, "must land on the Monday they consented to"


def test_a_permanent_reason_has_no_deadline() -> None:
    assert cp._next_allowed(
        cp.REASON_CUSTOMER_DND, now_local=datetime.now(IST), rules=None,
        channel="whatsapp", customer=_customer(),
    ) is None


# ---------------------------------------------------------------------------
# What the queue does with it
# ---------------------------------------------------------------------------


def test_a_deferral_requeues_at_the_deadline_and_does_not_burn_an_attempt() -> None:
    conn = _Conn()
    when = datetime(2026, 9, 11, 14, 0, tzinfo=timezone.utc)
    status = wo._defer(conn, _job(), _decision(cp.REASON_COOLING, when))
    assert status == "queued"
    sql = conn.sql()
    assert "status = 'queued'" in sql
    assert "run_after = :run_after" in sql
    assert conn.last_params["run_after"] == when
    # Counting a deferral as an attempt walks the job toward the dead-letter cap
    # for doing nothing but waiting — which is the original bug in miniature.
    assert "attempt" not in sql


def test_a_deferral_past_its_usefulness_is_cancelled_not_held() -> None:
    """A nudge about a moment that has passed is worse delivered late."""
    conn = _Conn()
    job = _job(purpose="outreach", created_at=datetime(2026, 9, 11, 6, 0, tzinfo=timezone.utc))
    far = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)
    status = wo._defer(conn, job, _decision(cp.REASON_WEEKLY, far))
    assert status == "dead"
    assert "expired_before_window" in conn.last_params["error"]


def test_a_statutory_confirmation_is_held_longer_than_a_nudge() -> None:
    """The pay-link a borrower is waiting for is still wanted two hours late."""
    assert wo._PURPOSE_TTL["statutory"] > wo._PURPOSE_TTL["outreach"]
    conn = _Conn()
    job = _job(purpose="statutory")
    soon = job["created_at"] + timedelta(hours=6)
    assert wo._defer(conn, job, _decision(cp.REASON_COOLING, soon)) == "queued"


def test_a_permanent_refusal_stops_the_job_without_burning_the_ladder() -> None:
    conn = _Conn()
    assert wo.cancel(conn, _job(), cp.REASON_CUSTOMER_DND) == "dead"
    assert "status = 'dead'" in conn.sql()


def test_a_policy_verdict_never_reaches_the_transport_classifier() -> None:
    """The one line this whole file is about."""
    import pathlib

    # Comments only, stripped: this file records the removed line verbatim so
    # the next reader knows what not to reinstate, and a raw grep would match
    # the epitaph as well as the corpse.
    src = "\n".join(
        line
        for line in pathlib.Path(wo.__file__).read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    block = src[src.index("if not decision.allowed:"):]
    block = block[: block.index("return")]
    assert "mark_failed_or_retry" not in block
    assert "decision.deferrable" in block


def test_the_claim_selects_what_the_send_path_reads() -> None:
    """`decision_id` was missing, so treatment attribution silently no-opped."""
    import inspect

    src = inspect.getsource(wo.claim_next_job)
    assert "decision_id" in src
    assert "created_at" in src


def test_a_ttl_cancelled_deferral_closes_out_the_message_row() -> None:
    """A cancelled job leaves the message in `sending` unless it is closed.

    The deferral branch returned early on every path when it was first written,
    so a job cancelled for outliving its TTL left a message row stuck at
    `sending` forever — visible in the Inbox as a reply that never resolved.
    """
    import pathlib

    src = "\n".join(
        line
        for line in pathlib.Path(wo.__file__).read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    block = src[src.index("if decision.deferrable and _defer("):]
    block = block[: block.index('"whatsapp_outbound blocked job')]
    # The early return is guarded on the deferral actually succeeding...
    assert '== "queued"' in block
    # ...and everything that falls past it closes the message out.
    assert "delivery_status = 'failed'" in block


def test_a_deferred_job_does_not_look_like_a_stalled_queue() -> None:
    """`_warn_if_queue_is_not_draining` reports "nothing is consuming the queue"
    for any job queued longer than 120s. A policy deferral is queued for hours
    on purpose, so counting it would fire that warning — and tell an operator to
    go restart a worker that is running fine — every time a borrower happened to
    be inside their cooling-off window."""
    import inspect

    src = inspect.getsource(wo._warn_if_queue_is_not_draining)
    assert "run_after IS NULL OR run_after <= now()" in src


def test_the_contact_policy_route_carries_the_schedule_and_the_binding(db_tx) -> None:
    """`ContactPolicyResponse` forbade extras and named neither `nextAllowedAt`
    nor the policy binding, so every read of a customer's contact policy was a
    500 the moment the gate had a rule set to cite. The route answers with the
    verdict, the schedule when there is one, and the rules it was judged under."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    import main as app_main

    customer_id = db_tx.execute(
        text("SELECT id FROM customers_pii WHERE id <> 'UNKNOWN-CALLER' ORDER BY id LIMIT 1")
    ).scalar()
    assert customer_id
    res = TestClient(app_main.app).get(f"/customers/{customer_id}/contact-policy")
    assert res.status_code == 200, res.text
    body = res.json()
    assert {"allowed", "channel", "purpose", "policyBinding"} <= set(body)
    if body["policyBinding"]:
        assert body["policyBindingHash"].startswith("sha256:")
        assert {"rule_id", "kind", "verdict", "scope"} <= set(body["policyBinding"][0])
