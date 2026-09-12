"""Does the compiled bundle match what the live mouth would run, on every card?

``deployment._dual_compute_parity`` compares the persisted artefact against
the live path on each call and only logs -- ``FLEET_ENABLED`` is the cutover
that makes the bundle authoritative. Flip it after this says every active
deployment is ``ok``, not before: a mismatch here is a call that would change
the moment the flag turned.

Read-only. Exit 0 when every active deployment agrees, 1 otherwise.

    docker compose exec -T api python scripts/fleet_parity.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    import db
    from sqlalchemy import text

    from agent_core.deployment import load_active_bundle
    from agent_core.fleet.compile import bundle_hash_valid, parity_report
    from agent_core.fleet.schema import CompiledBundle
    from agent_core.tools.grant import ToolGrant

    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT d.bot_id, d.environment FROM bot_deployments d "
                "JOIN bots b ON b.id = d.bot_id "
                "WHERE b.tenant_id = :t AND d.status = 'active' ORDER BY d.environment, d.bot_id"
            ),
            {"t": db.current_tenant()},
        ).mappings().all()
    bad = 0
    for row in rows:
        label = f"{row['bot_id']:20} {row['environment']:11}"
        try:
            bundle = load_active_bundle(row["environment"], bot_id=row["bot_id"])
        except KeyError as exc:
            print(f"{label} no bundle ({exc})")
            bad += 1
            continue
        compiled = bundle.get("compiled")
        if not isinstance(compiled, dict) or not compiled.get("bundle_hash"):
            print(f"{label} no compiled artefact -- publish the card")
            bad += 1
            continue
        parsed = CompiledBundle.model_validate(compiled)
        if str(bundle.get("bundleHash") or "") != parsed.bundle_hash:
            print(f"{label} deployment pins {bundle.get('bundleHash')}, row carries {parsed.bundle_hash}")
            bad += 1
            continue
        if not bundle_hash_valid(parsed):
            print(f"{label} bundle content hash invalid")
            bad += 1
            continue
        live_grant = ToolGrant.for_bundle(bundle, channel="voice")
        # With FLEET_ENABLED on, load_active_bundle has already swapped the
        # bundle's fields for the compiled ones; the live side of the
        # comparison is the published row itself.
        version = bundle.get("promptVersion") if isinstance(bundle.get("promptVersion"), dict) else {}
        report = parity_report(
            live_prompt=str(version.get("prompt") or ""),
            live_persona=version.get("persona") if isinstance(version.get("persona"), dict) else {},
            live_guardrails=version.get("guardrails") if isinstance(version.get("guardrails"), dict) else {},
            live_flow=version.get("flow") if isinstance(version.get("flow"), dict) else {},
            live_tools=live_grant.allowed,
            bundle=parsed,
            channel="voice",
            bot_id=str(bundle.get("botId") or ""),
            prompt_version_id=str(bundle.get("promptVersionId") or ""),
        )
        members = len(parsed.grant_by_specialist)
        fleet = f"fleet of {members}" if members > 1 else "single"
        # Derivation: a door's bundle names the member versions it merged. A
        # member that has published since is a stale door -- the rebuild on
        # publish did not happen (an experiment was running, or it failed).
        stale = []
        for member, version_id in parsed.member_versions.items():
            current = db.get_published_prompt_version(member)
            if current and str(current.get("id")) != version_id:
                stale.append(f"{member}: merged {version_id}, published {current.get('id')}")
        if not report["ok"]:
            bad += 1
            print(f"{label} MISMATCH {json.dumps(report.get('mismatches'))[:200]}")
        elif stale:
            bad += 1
            print(f"{label} STALE  {'; '.join(stale)}")
        else:
            print(f"{label} ok   {parsed.bundle_hash[:12]}  {fleet}")
    print(f"\n{len(rows) - bad} of {len(rows)} active deployment(s) agree with their bundle")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
