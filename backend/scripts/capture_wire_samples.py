"""Capture one real 200 body per GET route for the frontend's wire contract test.

``Habibi/src/api/wire/wire.test.ts`` parses every sample here with the schema
``gen_wire_schemas.py`` generated for its route, so a translation error in
the generator, or a model the API does not actually honour, is caught before
a screen goes blank on it. Runs against the dev stack (seeded, synthetic
data); arrays are cut to three items so the file stays small.

    python scripts/capture_wire_samples.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

#: Inside the voice container only /app is mounted; WIRE_SAMPLES_OUT points the
#: file somewhere writable and it is moved into Habibi/src/api/wire/ by hand.
OUT = Path(os.getenv("WIRE_SAMPLES_OUT") or Path(__file__).resolve().parents[2] / "Habibi" / "src" / "api" / "wire" / "samples.json")
SKIP_PREFIXES = ("/metrics", "/pay/", "/floor/copilot", "/webhooks", "/webhook/", "/twilio/")


def _trim(value, depth: int = 0):
    if isinstance(value, list):
        return [_trim(v, depth + 1) for v in value[:3]]
    if isinstance(value, dict):
        return {k: _trim(v, depth + 1) for k, v in value.items()}
    return value


def _param_values(conn) -> dict[str, str]:
    from sqlalchemy import text

    def one(sql: str) -> str | None:
        try:
            with conn.begin_nested():
                row = conn.execute(text(sql)).first()
        except Exception:  # a table this stack does not have
            return None
        return str(row[0]) if row and row[0] is not None else None

    tenant_pv = "SELECT id FROM prompt_versions WHERE status = 'published' AND bot_id = 'kaia-v2-4' ORDER BY created_at DESC LIMIT 1"
    values = {
        "bot_id": "kaia-v2-4",
        "customer_id": one("SELECT id FROM customers_pii WHERE id <> 'UNKNOWN-CALLER' ORDER BY id LIMIT 1"),
        "interaction_id": one("SELECT id FROM interactions ORDER BY started_at DESC NULLS LAST LIMIT 1"),
        "conversation_id": one("SELECT id FROM conversations ORDER BY created_at DESC LIMIT 1"),
        "version_id": one(tenant_pv),
        "deployment_id": one("SELECT id FROM bot_deployments WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"),
        "run_id": one("SELECT id FROM sandbox_runs ORDER BY created_at DESC LIMIT 1"),
        "document_id": one("SELECT id FROM kb_documents ORDER BY id LIMIT 1"),
        "doc_id": one("SELECT id FROM kb_documents ORDER BY id LIMIT 1"),
        "skill_id": one("SELECT id FROM skills ORDER BY id LIMIT 1"),
        "endpoint_id": one("SELECT id FROM webhook_endpoints ORDER BY id LIMIT 1"),
        "rule_id": one("SELECT id FROM routing_rules ORDER BY id LIMIT 1"),
        "report_id": one("SELECT id FROM eval_reports ORDER BY created_at DESC LIMIT 1"),
        "promise_id": one("SELECT id FROM promises ORDER BY id LIMIT 1"),
        "dispute_id": one("SELECT id FROM disputes ORDER BY id LIMIT 1"),
        "lead_id": one("SELECT id FROM leads ORDER BY id LIMIT 1"),
        "campaign_id": one("SELECT id FROM campaigns ORDER BY id LIMIT 1"),
        "mission_id": one("SELECT id FROM outbound_missions ORDER BY id LIMIT 1"),
        "call_id": one("SELECT id FROM interactions WHERE channel = 'voice' ORDER BY started_at DESC NULLS LAST LIMIT 1"),
        "connector_id": one("SELECT id FROM connectors ORDER BY id LIMIT 1"),
        "provider_id": one("SELECT id FROM providers ORDER BY id LIMIT 1"),
        "user_id": one("SELECT id FROM users ORDER BY id LIMIT 1"),
        "team_id": one("SELECT id FROM teams ORDER BY id LIMIT 1"),
        "product_id": one("SELECT id FROM products ORDER BY id LIMIT 1"),
        "account_id": one("SELECT id FROM accounts ORDER BY id LIMIT 1"),
    }
    return {k: v for k, v in values.items() if v}


def main_() -> int:
    from fastapi.testclient import TestClient

    import db
    import main

    with db.engine.begin() as conn:
        params = _param_values(conn)
    client = TestClient(main.app)
    spec = main.app.openapi()
    samples = []
    skipped = []
    for path, ops in spec["paths"].items():
        op = ops.get("get")
        if op is None or path.startswith(SKIP_PREFIXES):
            continue
        content = op.get("responses", {}).get("200", {}).get("content", {})
        if not any(k.startswith("application/json") for k in content):
            continue
        concrete = path
        for name in re.findall(r"\{(\w+)\}", path):
            if name not in params:
                concrete = None
                break
            concrete = concrete.replace("{" + name + "}", params[name])
        if concrete is None:
            skipped.append(path)
            continue
        try:
            res = client.get(concrete)
        except Exception as exc:  # a route that needs a live dependency
            skipped.append(f"{path} ({type(exc).__name__})")
            continue
        if res.status_code != 200:
            skipped.append(f"{path} ({res.status_code})")
            continue
        samples.append({"key": f"GET {path}", "path": concrete, "body": _trim(res.json())})
    OUT.write_text(json.dumps(samples, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(samples)} samples to {OUT}; skipped {len(skipped)}:")
    for s in skipped:
        print("  ", s)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main_())
