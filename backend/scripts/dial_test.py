"""Place one real outbound call through the full attempt ledger.

    python -m scripts.dial_test --customer cust-susanth
    python -m scripts.dial_test --customer cust-susanth --dry-run
    python -m scripts.dial_test --attempt CA-XXXX --show

This is the manual end-to-end for O0: it exercises the same path the treatment
executor and the bounce autodial use — reserve, contact gate, fleet gate, dial,
carrier callbacks, Closer — rather than a shortcut that proves less than it
appears to.

Refuses to run against production, and refuses to dial a number that is not on
a customer row. Both matter more here than usual: this script's whole purpose is
to make a real phone ring.

What to watch after it runs
---------------------------
    SELECT state, provider_status, ring_sec, talk_sec, answered_by, right_party
    FROM call_attempts ORDER BY reserved_at DESC LIMIT 5;

The states arrive from the selected telephony provider (``TELEPHONY_PROVIDER``):
Twilio's status callback, which needs ``PUBLIC_BASE_URL`` to be the live ngrok,
or the Asterisk controller's ARI events, which need ``asterisk_controller``
running. Without them the row sits at ``dialing`` until ``outbound.sweep_stale``
reaps it, so the script checks the provider before dialling rather than after.
"""

from __future__ import annotations

import argparse
import json
import sys

from env_loader import load_env
import env_utils
from env_utils import env_bool

load_env()

import contact_policy  # noqa: E402
import db  # noqa: E402
import outbound  # noqa: E402
from sqlalchemy import text  # noqa: E402


def _is_prod() -> bool:
    return env_utils.is_prod()


def _customer(conn, customer_id: str) -> dict:
    row = conn.execute(
        text(
            """
            SELECT c.id, c.tenant_id, c.name, c.phone_primary, c.phone_alt,
                   c.language, c.timezone,
                   a.id AS account_id, a.dpd, a.outstanding
            FROM customers c
            LEFT JOIN accounts a ON a.customer_id = c.id
            WHERE c.id = :id
            ORDER BY a.dpd DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"id": customer_id},
    ).mappings().first()
    if row is None:
        sys.exit(f"no such customer: {customer_id}")
    return dict(row)


def _preflight() -> list[str]:
    """Everything that makes a dial silently useless rather than loudly broken."""
    from voice import telephony

    return telephony.preflight()


def _show(attempt_id: str) -> None:
    with db.engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT a.*, o.connection, o.business, o.objective_met,
                       o.nonpayment_reason, o.summary, o.summary_source
                FROM call_attempts a
                LEFT JOIN call_outcomes o ON o.attempt_id = a.id
                WHERE a.id = :id
                """
            ),
            {"id": attempt_id},
        ).mappings().first()
    if row is None:
        sys.exit(f"no such attempt: {attempt_id}")
    print(json.dumps({k: str(v) for k, v in dict(row).items()}, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description="Place one outbound call through the ledger")
    ap.add_argument("--customer", default="cust-susanth")
    ap.add_argument("--objective", default="dpd_reminder")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Reserve and run both gates, then stop before the carrier.",
    )
    ap.add_argument("--show", metavar="ATTEMPT_ID", help="Print one attempt and its outcome")
    ap.add_argument(
        "--force-hours",
        action="store_true",
        help="Bypass the calling-window veto for a rehearsal. Refuses on a real number "
        "outside 08:00-19:00 unless OUTBOUND_TEST_ANY_HOUR is set.",
    )
    args = ap.parse_args()

    if args.show:
        _show(args.show)
        return

    if _is_prod():
        sys.exit("refused: APP_ENV=production")

    problems = _preflight()
    if problems and not args.dry_run:
        for p in problems:
            print(f"  ✗ {p}")
        sys.exit("preflight failed — fix the above or use --dry-run")

    with db.engine.begin() as conn:
        cust = _customer(conn, args.customer)
    phone = cust["phone_primary"] or cust["phone_alt"]
    if not phone:
        sys.exit(f"{cust['id']} has no phone on file")

    print(f"customer   {cust['id']}  ({cust['name']})")
    print(f"account    {cust['account_id']}  dpd={cust['dpd']}  outstanding={cust['outstanding']}")
    print(f"dialling   {outbound.to_e164(phone)}   (stored as {phone})")
    print(f"objective  {args.objective}")

    # Only the clock, never consent. An opt-out or a DND flag is a decision
    # the borrower made and no test flag overrides it.
    waivable: frozenset[str] = frozenset()
    if args.force_hours:
        if env_bool("OUTBOUND_TEST_ANY_HOUR"):
            waivable = frozenset({contact_policy.REASON_HOURS})
        else:
            print("  ! --force-hours needs OUTBOUND_TEST_ANY_HOUR=1 as well")

    reserve_kwargs = dict(
        customer_id=cust["id"],
        to_phone=phone,
        objective=args.objective,
        account_id=cust["account_id"],
        context={"source": "dial_test"},
    )
    with db.engine.begin() as conn:
        if args.dry_run:
            # `evaluate` on a rehearsal, `gate` on a real dial. They answer the
            # same question and only one of them *books* the touch: a --dry-run
            # that admitted would spend the borrower's daily contact budget and
            # put the next two hours behind a cooling-off veto, so rehearsing
            # would make the thing it rehearses impossible.
            attempt = outbound.reserve(conn, **reserve_kwargs)
            if attempt is None:
                sys.exit("could not reserve an attempt")
            decision = contact_policy.evaluate(
                conn,
                customer_id=cust["id"],
                channel="voice",
                purpose="outreach",
                session_key=attempt["id"],
            )
            allowed = decision.allowed
            if not allowed and decision.reason in waivable:
                print("  ! calling-window veto overridden for a rehearsal")
                allowed = True
            reason = decision.reason
        else:
            gated = outbound.gate(
                conn,
                admit={"source": "dial_test", "actor_kind": "human"},
                waivable=waivable,
                **reserve_kwargs,
            )
            attempt = gated.attempt
            if attempt is None:
                sys.exit("could not reserve an attempt")
            if gated.waived:
                print("  ! calling-window veto overridden for a rehearsal")
            allowed = gated.allowed
            reason = gated.reason

    print(f"attempt    {attempt['id']}  (attempt #{attempt['attemptNo']})")
    if not allowed:
        print(f"gate       DENIED · {reason}")
        print("           the attempt is recorded as suppressed — that is the point")
        return
    print("gate       allowed")

    if args.dry_run:
        # Release it rather than leaving it `reserved`. A reserved row counts
        # against the fleet gate until `outbound.sweep_stale` reaps it, so a few
        # rehearsals in a row would quietly throttle real dialling.
        with db.engine.begin() as conn:
            outbound.mark(conn, attempt["id"], state=outbound.STATE_CANCELED)
        print("dry-run    stopping before the carrier (attempt cancelled)")
        return

    result = outbound.place(db.engine, attempt, to_phone=phone)
    print(f"result     {json.dumps(result, default=str)}")
    if result.get("placed"):
        print()
        print("Your phone should ring. Watch the row fill in:")
        print(f"  python -m scripts.dial_test --show {attempt['id']}")


if __name__ == "__main__":
    main()
