"""Load a named suite from Postgres and persist a report. No LLM on this path."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from agent_core.eval.harness import run_suite_fixtures
from agent_core.cards.defaults import COLLECTIONS_BOT_ID

logger = logging.getLogger(__name__)

_ORIGINS = frozenset({"manual", "scheduled", "canary", "upgrade"})


def bot_id_for_suite(suite_id: str) -> str | None:
    """Which card a report for this suite belongs to, when one clearly does.

    Deliberately still a name match, and deliberately still returns None for
    everything else. Resolving it from `agent_card.eval.suite_id` was tried and
    is wrong: that relation is one-to-MANY here — nine cards in this tenant name
    `eval-regression-collections`, including two clones and an audit fixture —
    so any "pick one" rule silently attributes kaia's scheduled runs to whichever
    clone was published most recently.

    A suite genuinely is not owned by one card, so NULL is the truthful answer
    for the scheduled runs, not a gap to be filled in by guessing. What was
    actually broken is the reading of NULL downstream: the Evals tab treated
    "filed against no card" as "never run on this card", so insurance-v1
    reported itself untested while its lapse suites passed nightly. That is
    fixed where it is wrong — in the tab — rather than by inventing an owner
    here.
    """
    if suite_id.endswith("-collections") or "collections" in suite_id:
        return COLLECTIONS_BOT_ID
    return None


def load_suite_fixtures(suite_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import db

    with db.engine.connect() as conn:
        suite = db._one(
            conn.execute(
                text("SELECT id, kind, name FROM eval_suites WHERE id = :id AND tenant_id = :t"),
                {"id": suite_id, "t": db._tenant()},
            )
        )
        if suite is None:
            raise KeyError("eval_suite_not_found")
        tasks = db._rows(
            conn.execute(
                text(
                    "SELECT id, name, grader, fixture FROM eval_tasks WHERE suite_id = :id ORDER BY id"
                ),
                {"id": suite_id},
            )
        )
        cases = db._rows(
            conn.execute(
                text(
                    "SELECT id, name, attack, fixture FROM eval_redteam_cases WHERE suite_id = :id ORDER BY id"
                ),
                {"id": suite_id},
            )
        )
    fixtures = [
        {"id": t["id"], "name": t["name"], "grader": t["grader"], "fixture": t.get("fixture") or {}}
        for t in tasks
    ]
    for case in cases:
        fixtures.append(
            {
                "id": case["id"],
                "name": case["name"],
                "grader": case.get("attack") or "no_prose_handoff",
                "fixture": case.get("fixture") or {},
            }
        )
    return dict(suite), fixtures


def run_named_suite(
    suite_id: str,
    *,
    origin: str = "manual",
    bot_id: str | None = None,
    prompt_version_id: str | None = None,
) -> dict[str, Any]:
    import db

    origin = origin if origin in _ORIGINS else "manual"
    suite, fixtures = load_suite_fixtures(suite_id)
    result = run_suite_fixtures(fixtures)
    # What was judged, as one key -- the gate reads by this, not by row id.
    key = None
    if prompt_version_id:
        from agent_core.eval.provenance import content_key_for_version

        version = db.get_prompt_version(prompt_version_id)
        key = content_key_for_version(version) if version else None
    saved = db.save_eval_report(
        suite_id=suite_id,
        bot_id=bot_id if bot_id is not None else bot_id_for_suite(suite_id),
        status=result["status"],
        summary={"failed": result["failed"], "total": result["total"], "origin": origin},
        trials=result["trials"],
        origin=origin,
        prompt_version_id=prompt_version_id,
        content_key=key,
    )
    logger.info(
        "gf14_debug eval_saved report=%s suite=%s bot=%s pv=%s key=%s",
        saved.get("id"),
        suite_id,
        bot_id,
        prompt_version_id,
        (key or "")[:16],
    )
    return {
        "suiteId": suite_id,
        "kind": suite["kind"],
        "name": suite.get("name"),
        "reportId": saved["id"],
        **result,
    }


#: Which suite satisfies which card requirement. The gate reads by kind (any
#: suite of that kind filed against the content counts), so this only decides
#: which suite *this* action runs. `bot_id_for_suite` knows only the
#: collections family; the lapse suites are the insurance card's.
SUITES_BY_BOT: dict[str, dict[str, str]] = {
    "insurance-v1": {"regression": "eval-regression-lapse", "redteam": "eval-redteam-lapse"},
}
DEFAULT_SUITES: dict[str, str] = {
    "regression": "eval-regression-collections",
    "redteam": "eval-redteam-collections",
    "outbound": "eval-outbound-collections",
}
#: Required kinds this action cannot satisfy, and where the author can.
_ELSEWHERE = {"twin": "run it from the Sandbox inspector's Twin tab"}


def run_required_suites(bot_id: str, prompt_version_id: str) -> dict[str, Any]:
    """Run every suite ``bot_id``'s card requires, filed against the stored
    content of ``prompt_version_id`` -- the report G7/G8/G-OB9 read.

    The publish dialog had no way to produce one: the nightly scheduler files
    its runs against no version and no content, so a draft's eval gates failed
    "has not been run" with nothing on the dialog to run them, and the only
    remedy was a per-suite Run button two tabs away that nobody was pointed at.
    """
    import db
    from agent_core.cards.schema import CardEval, is_authored, parse_card

    version = db.get_prompt_version(prompt_version_id)
    if version is None:
        raise KeyError(f"prompt_version_not_found: {prompt_version_id}")
    if version.get("botId") != bot_id:
        raise ValueError("prompt_version_bot_mismatch")
    raw = version.get("agentCard") or {}
    # A legacy (unauthored) card is gated on the default requirement, exactly
    # as `_eval_gate` gates it.
    required = parse_card(raw).eval.require if is_authored(raw) else CardEval().require
    ran: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for kind in required or []:
        if kind in _ELSEWHERE:
            skipped.append({"kind": kind, "reason": _ELSEWHERE[kind]})
            continue
        suite_id = SUITES_BY_BOT.get(bot_id, {}).get(kind) or DEFAULT_SUITES.get(kind)
        if not suite_id:
            skipped.append({"kind": kind, "reason": f"no {kind} suite is configured"})
            continue
        out = run_named_suite(
            suite_id, origin="manual", bot_id=bot_id, prompt_version_id=prompt_version_id
        )
        ran.append(
            {
                "kind": kind,
                "suiteId": suite_id,
                "reportId": out["reportId"],
                "status": out["status"],
                "failed": out["failed"],
                "total": out["total"],
            }
        )
    logger.info(
        "eval.run_required bot=%s pv=%s required=%s ran=%s skipped=%s",
        bot_id,
        prompt_version_id,
        list(required or []),
        [f"{r['kind']}={r['status']}" for r in ran],
        [s["kind"] for s in skipped],
    )
    return {
        "botId": bot_id,
        "promptVersionId": prompt_version_id,
        "status": "pass" if all(r["status"] == "pass" for r in ran) else "fail",
        "ran": ran,
        "skipped": skipped,
    }
