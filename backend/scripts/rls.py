#!/usr/bin/env python
"""Inspect and switch on row-level security.

    python scripts/rls.py status
    python scripts/rls.py plan [--table T] [--sql]
    python scripts/rls.py apply                 # install policies (inert)
    python scripts/rls.py provision-role app_rw --password ...
    python scripts/rls.py enable --verify-as app_rw
    python scripts/rls.py disable

The order matters and the tool enforces it. ``apply`` installs policies without
turning row security on, so they can be read out of ``pg_policies`` and reviewed
before they affect a single query. ``enable`` is the switch, and it verifies
itself inside the transaction that does the work: it counts what each tenant
should see, turns policies on, counts again as the application's own role, and
raises rather than commits if the numbers disagree. Because Postgres keeps DDL
transactional, a failed enable leaves nothing behind.

The one thing to understand before running ``enable``: superusers and roles with
BYPASSRLS ignore policies entirely. Enabling while the application connects as
such a role is worse than not enabling, because everything looks like it worked.
``status`` leads with that, and ``enable`` refuses.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402
import rls  # noqa: E402


def _print_status(conn) -> int:
    status = rls.status(conn)
    print(f"database        {db.DATABASE_URL.rsplit('@', 1)[-1]}")
    print(f"role            {status['role']}")
    print(f"tenant GUC      {status['tenant_guc'] or '<UNSET>'}")
    print(
        f"policies        {status['installed']} installed / {status['derived']} derived"
    )
    print(
        f"enforcing       {status['enforcing']} enabled / {status['forced']} forced"
    )
    print("coverage        " + ", ".join(f"{k}={v}" for k, v in sorted(status["by_depth"].items())))
    print(f"no policy       {len(status['unscoped'])} tables: {', '.join(status['unscoped'])}")
    if status["weak"]:
        print(
            f"weakly scoped   {len(status['weak'])} tables reach their tenant only "
            f"through nullable columns: {', '.join(sorted(status['weak']))}"
        )

    problems = 0
    if status["role_bypasses_rls"]:
        problems += 1
        print(
            f"\n  !! {status['role']} is a superuser or has BYPASSRLS. Policies are "
            "IGNORED for this role, whether or not they are enabled.\n"
            "     Create an application role and point DATABASE_URL at it:\n"
            f"       python scripts/rls.py provision-role app_rw --password ..."
        )
    if not status["tenant_guc"]:
        problems += 1
        print(
            f"\n  !! {rls.tenant_context.GUC} is unset on this connection. With "
            "policies enforcing, every query would return zero rows."
        )
    if status["missing_policy"]:
        problems += 1
        missing = status["missing_policy"]
        shown = ", ".join(missing[:8])
        more = f" (+{len(missing) - 8} more)" if len(missing) > 8 else ""
        print(f"\n  !! derived but not installed: {len(missing)} tables — {shown}{more}")
        print("     run: python scripts/rls.py apply")

    orphans = rls.orphan_rows(conn)
    if orphans:
        problems += 1
        print("\n  !! rows that belong to no tenant — enabling would hide them:")
        for table, count in sorted(orphans.items()):
            print(f"       {table}: {count}")

    if not problems:
        print("\n  ok — no blocking issues")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="coverage, enforcement, and blocking issues")

    p_plan = sub.add_parser("plan", help="show the derived policies")
    p_plan.add_argument("--table", help="one table only")
    p_plan.add_argument("--sql", action="store_true", help="print the predicate SQL")

    sub.add_parser("apply", help="install/refresh policies without enabling them")

    p_role = sub.add_parser("provision-role", help="create a role policies apply to")
    p_role.add_argument("role")
    p_role.add_argument("--password", required=True)

    p_enable = sub.add_parser("enable", help="turn row security on, verifying first")
    p_enable.add_argument(
        "--verify-as",
        help="role to count rows as — the application's role, not the owner",
    )
    p_enable.add_argument(
        "--allow-bypassing-role",
        action="store_true",
        help="proceed even though the verifying role ignores policies (rarely right)",
    )

    sub.add_parser("disable", help="turn row security off, leaving policies installed")

    args = parser.parse_args()

    if args.command == "status":
        with db.engine.connect() as conn:
            return _print_status(conn)

    if args.command == "plan":
        with db.engine.connect() as conn:
            for policy in rls.plan(conn):
                if args.table and policy.table != args.table:
                    continue
                parents = " <- " + ", ".join(policy.parents) if policy.parents else ""
                flag = "  [weak]" if policy.weak else ""
                print(f"{policy.kind:<8} {policy.table}{parents}{flag}")
                if args.sql:
                    print(f"         {policy.predicate}")
        return 0

    if args.command == "apply":
        with db.engine.begin() as conn:
            statements = rls.apply(conn)
        print(f"installed {len(statements) // 2} policies (not enabled)")
        print("review them:  SELECT * FROM pg_policies WHERE schemaname='public'")
        return 0

    if args.command == "provision-role":
        with db.engine.begin() as conn:
            for stmt in rls.provision_role(conn, args.role, args.password):
                print(stmt)
        print(
            f"\nrole {args.role!r} created. Point DATABASE_URL at it, then:\n"
            f"  python scripts/rls.py enable --verify-as {args.role}"
        )
        return 0

    if args.command == "enable":
        try:
            with db.engine.begin() as conn:
                result = rls.enable(
                    conn,
                    verify_as=args.verify_as,
                    allow_bypassing_role=args.allow_bypassing_role,
                )
        except (rls.EnableRefused, rls.EnableVerificationFailed) as exc:
            print(f"refused:\n{exc}", file=sys.stderr)
            return 1
        print(
            f"row-level security enabled on {result['tables']} tables, verified as "
            f"{result['verified_as']!r} against tenant {result['tenant']!r} "
            f"({result['verified_rows']} rows)"
        )
        return 0

    if args.command == "disable":
        with db.engine.begin() as conn:
            statements = rls.disable(conn)
        print(f"row security disabled on {len(statements)} tables (policies kept)")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
