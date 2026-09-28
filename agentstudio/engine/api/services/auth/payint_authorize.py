"""AgentStudio: every use of an engine API key is re-checked with PayInt.

A key authenticates as the PayInt user who created it, outside the host
gateway's permission check. So each use asks PayInt's
``/voice-studio/hooks/authorize`` whether that user is still active and still
holds the permission this request needs; deactivating someone, or taking a
permission away, stops their keys at once.

Fails closed. Configured by ``PAYINT_AUTHORIZE_URL`` and ``PAYINT_HOOK_TOKEN``;
unset, nothing is checked (a stock engine).
"""

import os
import time

import httpx
from fastapi import HTTPException
from loguru import logger

from api.db import db_client

_TTL_S = 30.0
_cache: dict[tuple, tuple[float, bool, str]] = {}


def _host_id(provider_id: str | None, prefix: str) -> str | None:
    value = provider_id or ""
    return value[len(prefix):] if value.startswith(prefix) else None


def enabled() -> bool:
    return bool(os.getenv("PAYINT_AUTHORIZE_URL", "").strip())


async def authorize(user_provider_id: str | None, organization_id: int, method: str, path: str) -> None:
    if not enabled():
        return
    url = os.getenv("PAYINT_AUTHORIZE_URL", "").strip()
    user_id = _host_id(user_provider_id, "host:")
    organization = await db_client.get_organization_by_id(organization_id)
    tenant_id = _host_id(getattr(organization, "provider_id", None), "tenant:")
    if not user_id or not tenant_id:
        raise HTTPException(status_code=403, detail="API key is not owned by a PayInt user")

    key = (user_id, tenant_id, method, path)
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        allowed, reason = hit[1], hit[2]
    else:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    url,
                    json={"user_id": user_id, "tenant_id": tenant_id, "method": method, "path": path},
                    headers={"Authorization": f"Bearer {os.getenv('PAYINT_HOOK_TOKEN', '')}"},
                )
                resp.raise_for_status()
                answer = resp.json()
        except Exception as e:
            logger.error(f"PayInt authorize unavailable; refusing API key use: {e}")
            raise HTTPException(status_code=503, detail="Permission could not be checked") from e
        allowed, reason = bool(answer.get("allowed")), str(answer.get("reason") or "forbidden")
        _cache[key] = (time.monotonic() + _TTL_S, allowed, reason)
    if not allowed:
        raise HTTPException(status_code=403, detail=reason)
