"""Live-stack providers: config rows, health probes, enable/disable and the test log.

Carved from ops_screens.py.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import Any
from sqlalchemy import text
import db
from agent_core.clock import utc_now
from db_core import _id
from db_webhooks import _mask_secret

logger = logging.getLogger(__name__)


# Live-stack providers only (env-backed). CBS / Pipecat-as-connector stay mock-only.
LIVE_PROVIDER_IDS = (
    "azure_openai",
    "azure_speech_stt",
    "azure_speech_tts",
    "twilio",
    "whatsapp",
)


_PROVIDER_META: dict[str, dict[str, Any]] = {
    "azure_openai": {
        "name": "Azure OpenAI",
        "vendor": "Microsoft Azure",
        "category": "Voice AI",
        "capability": "LLM — reasoning core",
        "description": "GPT deployment powering reasoning, RAG synthesis, and tool-calling.",
        "docsUrl": "https://learn.microsoft.com/azure/ai-services/openai/",
        "brandInitial": "Az",
        "brandColor": "bg-blue-100 text-blue-700",
        "capabilities": ["streaming", "tool-calling", "JSON mode"],
        "fields": [
            {"key": "endpoint", "label": "Endpoint", "secret": False},
            {"key": "apiKey", "label": "API key", "secret": True},
            {"key": "deployment", "label": "Deployment name", "secret": False},
            {"key": "apiVersion", "label": "API version", "secret": False},
        ],
        "env_map": {
            "endpoint": "AZURE_OPENAI_ENDPOINT",
            "apiKey": "AZURE_OPENAI_API_KEY",
            "deployment": "AZURE_OPENAI_CHAT_DEPLOYMENT",
            "apiVersion": "AZURE_OPENAI_API_VERSION",
        },
    },
    "azure_speech_stt": {
        "name": "Azure Speech STT",
        "vendor": "Microsoft Azure",
        "category": "Voice AI",
        "capability": "Speech-to-text",
        "description": "Realtime transcription for voice calls.",
        "docsUrl": "https://learn.microsoft.com/azure/ai-services/speech-service/",
        "brandInitial": "ST",
        "brandColor": "bg-sky-100 text-sky-700",
        "capabilities": ["streaming", "multi-language"],
        "fields": [
            {"key": "speechKey", "label": "Speech key", "secret": True},
            {"key": "region", "label": "Region", "secret": False},
            {"key": "language", "label": "Default language", "secret": False},
        ],
        "env_map": {
            "speechKey": "AZURE_SPEECH_KEY",
            "region": "AZURE_SPEECH_REGION",
            "language": "AZURE_SPEECH_LANGUAGE",
        },
    },
    "azure_speech_tts": {
        "name": "Azure Speech TTS",
        "vendor": "Microsoft Azure",
        "category": "Voice AI",
        "capability": "Text-to-speech",
        "description": "Neural voices for bot replies.",
        "docsUrl": "https://learn.microsoft.com/azure/ai-services/speech-service/",
        "brandInitial": "TT",
        "brandColor": "bg-indigo-100 text-indigo-700",
        "capabilities": ["neural voices", "SSML"],
        "fields": [
            {"key": "speechKey", "label": "Speech key", "secret": True},
            {"key": "region", "label": "Region", "secret": False},
            {"key": "defaultVoice", "label": "Default voice", "secret": False},
        ],
        "env_map": {
            "speechKey": "AZURE_SPEECH_KEY",
            "region": "AZURE_SPEECH_REGION",
            "defaultVoice": "AZURE_SPEECH_TTS_VOICE_DEFAULT",
        },
    },
    "twilio": {
        "name": "Twilio",
        "vendor": "Twilio",
        "category": "Telephony",
        "capability": "PSTN / Media Streams",
        "description": "Inbound/outbound voice transport for the collections line.",
        "docsUrl": "https://www.twilio.com/docs",
        "brandInitial": "Tw",
        "brandColor": "bg-rose-100 text-rose-700",
        "capabilities": ["media streams", "PSTN"],
        "fields": [
            # The SID is half of Twilio basic auth: never served in clear.
            {"key": "accountSid", "label": "Account SID", "secret": True},
            {"key": "authToken", "label": "Auth token", "secret": True},
        ],
        "env_map": {
            "accountSid": "TWILIO_ACCOUNT_SID",
            "authToken": "TWILIO_AUTH_TOKEN",
        },
    },
    "whatsapp": {
        "name": "WhatsApp Cloud API",
        "vendor": "Meta",
        "category": "Messaging",
        "capability": "WhatsApp business messaging",
        "description": "Inbound webhook + outbound agent/bot messages.",
        "docsUrl": "https://developers.facebook.com/docs/whatsapp/",
        "brandInitial": "WA",
        "brandColor": "bg-emerald-100 text-emerald-700",
        "capabilities": ["webhooks", "templates"],
        "fields": [
            {"key": "phoneNumberId", "label": "Phone number ID", "secret": False},
            {"key": "wabaId", "label": "WABA ID", "secret": False},
            {"key": "accessToken", "label": "System-user token", "secret": True},
        ],
        "env_map": {
            "phoneNumberId": "WHATSAPP_PHONE_NUMBER_ID",
            "wabaId": "WHATSAPP_WABA_ID",
            "accessToken": "WHATSAPP_TOKEN",
        },
    },
}


def _env_values(provider_id: str) -> dict[str, str]:
    meta = _PROVIDER_META[provider_id]
    out: dict[str, str] = {}
    for field_key, env_name in meta["env_map"].items():
        raw = (os.getenv(env_name) or "").strip()
        field = next((f for f in meta["fields"] if f["key"] == field_key), None)
        if field and field.get("secret"):
            out[field_key] = _mask_secret(bool(raw))
        else:
            out[field_key] = raw
    return out


def _provider_config_id(provider_id: str, environment: str) -> str:
    """Surrogate id for a new provider_configs row.

    Includes the tenant so ids stay unique across tenants; the durable identity
    (and upsert conflict target) is (provider_id, tenant_id, environment).
    """
    return f"pcfg-{db.current_tenant()}-{provider_id}-{environment}"


def _provider_config_rows(environment: str) -> dict[str, dict[str, Any]]:
    """All provider_configs rows for this tenant/env, keyed by provider_id.

    One query for the whole screen — the per-provider variant opened a
    connection per provider on every Integrations page load.
    """
    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT provider_id, enabled, health, latency_ms
                    FROM provider_configs
                    WHERE tenant_id = :tenant AND environment = :env
                    """
                ),
                {"tenant": db.current_tenant(), "env": environment},
            )
        )
    return {str(r["provider_id"]): dict(r) for r in rows}


# Distinguishes "caller supplied no config data" from "the batched lookup found
# no row for this provider". Without it, every unconfigured provider in
# list_providers re-ran _provider_config_rows(), defeating the batching.
_CONFIG_ROW_UNSET: Any = object()


def _provider_health(
    provider_id: str,
    environment: str = "sandbox",
    *,
    config_row: dict[str, Any] | None = _CONFIG_ROW_UNSET,
) -> tuple[str, int, bool]:
    meta = _PROVIDER_META[provider_id]
    env = environment if environment in {"sandbox", "production"} else "sandbox"
    configured = all(
        (os.getenv(env_name) or "").strip()
        for field in meta["fields"]
        if field.get("secret")
        for env_name in [meta["env_map"].get(field["key"])]
        if env_name
    )
    # Non-secret-only providers (unlikely) — any mapped env counts.
    if not any(f.get("secret") for f in meta["fields"]):
        configured = any((os.getenv(v) or "").strip() for v in meta["env_map"].values())
    enabled_default = configured
    row = (
        _provider_config_rows(env).get(provider_id)
        if config_row is _CONFIG_ROW_UNSET
        else config_row
    )
    if row and row.get("enabled") is not None:
        enabled_default = bool(row["enabled"]) and configured
    if not configured:
        return "unconfigured", 0, False
    health = (row or {}).get("health") or "healthy"
    latency = int((row or {}).get("latency_ms") or 0)
    return health if enabled_default else "unconfigured", latency, enabled_default


def list_providers(environment: str = "sandbox") -> list[dict[str, Any]]:
    # Both environments up front. `enabled`, `health` and `latency_ms` live in
    # provider_configs keyed by (tenant, environment) and patch_provider_enabled
    # writes one environment at a time — copying the requested env's status into
    # both perEnv entries made a sandbox toggle read back as a production one.
    rows_by_env = {
        "sandbox": _provider_config_rows("sandbox"),
        "production": _provider_config_rows("production"),
    }
    out: list[dict[str, Any]] = []
    for pid in LIVE_PROVIDER_IDS:
        meta = _PROVIDER_META[pid]
        values = _env_values(pid)

        def _per(for_env: str, pid: str = pid, values: dict[str, Any] = values) -> dict[str, Any]:
            health, latency, enabled = _provider_health(
                pid, for_env, config_row=rows_by_env[for_env].get(pid)
            )
            return {
                "values": values,
                # Credentials are process-wide env vars, so `values` is shared;
                # only the DB-backed status is per-environment. The region is
                # what the environment says or nothing: a displayed default
                # that the runtime did not use is a lie on a data-residency
                # screen.
                "region": values.get("region") or None,
                "health": health,
                "latencyMs": latency,
                "enabled": enabled,
                "usageStats": [
                    {"label": "Source", "value": "env"},
                    {"label": "Secrets", "value": "ops vault"},
                    {"label": "Editable", "value": "no"},
                ],
                "costMonth": "—",
                "unitLabel": "ops",
                "credentialsLocked": True,
            }

        out.append(
            {
                "id": pid,
                "name": meta["name"],
                "vendor": meta["vendor"],
                "category": meta["category"],
                "capability": meta["capability"],
                "description": meta["description"],
                "docsUrl": meta["docsUrl"],
                "brandInitial": meta["brandInitial"],
                "brandColor": meta["brandColor"],
                "capabilities": meta["capabilities"],
                "fields": meta["fields"],
                "perEnv": {
                    "sandbox": _per("sandbox"),
                    "production": _per("production"),
                },
            }
        )
    return out


def patch_provider_enabled(provider_id: str, environment: str, enabled: bool) -> dict[str, Any]:
    if provider_id not in LIVE_PROVIDER_IDS:
        raise KeyError("provider_not_found")
    env = environment if environment in {"sandbox", "production"} else "sandbox"
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO tenants (id, name, created_at, updated_at)
                VALUES (:id, :name, now(), now())
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": db.current_tenant(), "name": db.current_tenant()},
        )
        conn.execute(
            text(
                """
                INSERT INTO providers (id, name, category, created_at, updated_at)
                VALUES (:id, :name, :cat, now(), now())
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, updated_at = now()
                """
            ),
            {
                "id": provider_id,
                "name": _PROVIDER_META[provider_id]["name"],
                "cat": _PROVIDER_META[provider_id]["category"],
            },
        )
        tenant = db.current_tenant()
        conn.execute(
            text(
                """
                INSERT INTO provider_configs (
                  id, provider_id, tenant_id, environment, values, health,
                  latency_ms, enabled, credential_ref, created_at, updated_at
                ) VALUES (
                  :id, :pid, :tenant, :env, '{}'::jsonb, :health,
                  0, :enabled, :cref, now(), now()
                )
                ON CONFLICT (provider_id, tenant_id, environment) DO UPDATE SET
                  enabled = EXCLUDED.enabled,
                  health = EXCLUDED.health,
                  updated_at = now()
                """
            ),
            {
                "id": _provider_config_id(provider_id, env),
                "pid": provider_id,
                "tenant": tenant,
                "env": env,
                "health": "healthy" if enabled else "unconfigured",
                "enabled": enabled,
                "cref": f"env://{provider_id}",
            },
        )
    providers = list_providers(env)
    return next(p for p in providers if p["id"] == provider_id)


def test_provider(provider_id: str, environment: str = "sandbox") -> dict[str, Any]:
    if provider_id not in LIVE_PROVIDER_IDS:
        raise KeyError("provider_not_found")
    env = environment if environment in {"sandbox", "production"} else "sandbox"
    meta = _PROVIDER_META[provider_id]
    t0 = time.perf_counter()
    missing = [
        env_name
        for field in meta["fields"]
        if field.get("secret")
        for env_name in [meta["env_map"].get(field["key"])]
        if env_name and not (os.getenv(env_name) or "").strip()
    ]
    ok = not missing
    latency = int((time.perf_counter() - t0) * 1000) + (12 if ok else 3)
    message = "Connection config present" if ok else f"Missing env: {', '.join(missing)}"
    entry = {
        "id": _id("itest"),
        "at": utc_now().isoformat(),
        "providerId": provider_id,
        "env": env,
        "ok": ok,
        "latencyMs": latency,
        "message": message,
        "payload": None,
    }
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO providers (id, name, category, created_at, updated_at)
                VALUES (:id, :name, :cat, now(), now())
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": provider_id,
                "name": meta["name"],
                "cat": meta["category"],
            },
        )
        tenant = db.current_tenant()
        # Tenant-scoped read: keying by the surrogate id alone read (and then
        # overwrote) whichever tenant happened to own that row.
        existing_enabled = conn.execute(
            text(
                """
                SELECT enabled FROM provider_configs
                WHERE provider_id = :pid AND tenant_id = :tenant AND environment = :env
                """
            ),
            {"pid": provider_id, "tenant": tenant, "env": env},
        ).scalar()
        enabled_val = bool(existing_enabled) if existing_enabled is not None else False
        # RETURNING id: an existing row may still carry the legacy
        # (tenant-less) surrogate id, and integration_test_logs FKs to it.
        cid = conn.execute(
            text(
                """
                INSERT INTO provider_configs (
                  id, provider_id, tenant_id, environment, values, health,
                  latency_ms, enabled, credential_ref, created_at, updated_at
                ) VALUES (
                  :id, :pid, :tenant, :env, '{}'::jsonb, :health,
                  :lat, :enabled, :cref, now(), now()
                )
                ON CONFLICT (provider_id, tenant_id, environment) DO UPDATE SET
                  health = EXCLUDED.health,
                  latency_ms = EXCLUDED.latency_ms,
                  updated_at = now()
                RETURNING id
                """
            ),
            {
                "id": _provider_config_id(provider_id, env),
                "pid": provider_id,
                "tenant": tenant,
                "env": env,
                "health": "healthy" if ok else "degraded",
                "lat": latency,
                "enabled": enabled_val,
                "cref": f"env://{provider_id}",
            },
        ).scalar()
        conn.execute(
            text(
                """
                INSERT INTO integration_test_logs (
                  id, config_id, status, latency_ms, payload_summary, error, created_at
                ) VALUES (
                  :id, :cid, :status, :lat, CAST(:payload AS jsonb), :err, now()
                )
                """
            ),
            {
                "id": entry["id"],
                "cid": cid,
                "status": "ok" if ok else "error",
                "lat": latency,
                "payload": json.dumps({"message": message}),
                "err": None if ok else message,
            },
        )
    return entry


def list_provider_test_logs(provider_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT l.id, l.status, l.latency_ms, l.error, l.created_at, l.payload_summary,
                           c.environment, c.provider_id
                    FROM integration_test_logs l
                    JOIN provider_configs c ON c.id = l.config_id
                    WHERE c.provider_id = :pid AND c.tenant_id = :tenant
                    ORDER BY l.created_at DESC
                    LIMIT :limit
                    """
                ),
                {"pid": provider_id, "tenant": db.current_tenant(), "limit": limit},
            )
        )
    out = []
    for r in rows:
        at = r["created_at"]
        out.append(
            {
                "id": r["id"],
                "at": at.isoformat() if isinstance(at, datetime) else str(at),
                "providerId": r["provider_id"],
                "env": r["environment"],
                "ok": r["status"] == "ok",
                "latencyMs": int(r["latency_ms"] or 0),
                "message": r["error"] or "ok",
                "payload": None,
            }
        )
    return out
