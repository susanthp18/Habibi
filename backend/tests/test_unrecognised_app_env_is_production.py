"""Unrecognised APP_ENV is production; absent credentials refuse.

``_IS_PROD`` used to be a two-string allowlist (``prod`` / ``production``), so
``APP_ENV=staging`` — and any typo — silently disabled eight fail-closed
controls while ``env_utils`` correctly refused the committed dev keys. Absent
``API_KEY`` was then a *mode* (auth off), not a refusal.

This file pins the inverted reading. The four acceptance criteria for
``APP_ENV=staging`` cannot be asserted by monkeypatching ``main._IS_PROD``:
that is the workaround two existing tests already use, and it is what left
the import-time freeze unexercised. A subprocess (and the
``APP_ENV=production`` CI job) freeze it for real.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

def test_is_prod_has_one_owner_and_it_is_an_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the assignment and the owner. A comment would keep passing after a
    revert; so would a second copy of the list beside ``env_utils.is_prod``."""
    import env_utils

    src = (BACKEND / "main.py").read_text(encoding="utf-8")
    assert "_IS_PROD = is_prod()" in src
    actor = (BACKEND / "actor_context.py").read_text(encoding="utf-8")
    assert "return is_prod()" in actor
    # The list is read the allow-list way round: only a declared non-production
    # name is not production, and anything unrecognised is.
    for name in ("dev", "test", "local", "ci"):
        monkeypatch.setenv("APP_ENV", name)
        assert env_utils.is_prod() is False, name
    for name in ("staging", "prod", "production", "porduction", ""):
        monkeypatch.setenv("APP_ENV", name)
        monkeypatch.delenv("ENV", raising=False)
        assert env_utils.is_prod() is (name != ""), name
    middleware_src = src[
        src.index("class ApiKeyMiddleware") : src.index("class RequestIdMiddleware")
    ]
    assert "auth_required = _IS_PROD or bool(single or key_map) or entra.configured()" in middleware_src


def test_ci_production_job_freezes_is_prod_without_monkeypatch() -> None:
    """When the process itself is production, the freeze must already be True.

    The main suite sets ``APP_ENV=dev`` and two tests setattr ``_IS_PROD``.
    This test is the other half: no monkeypatch, import-time value only.
    """
    import env_utils

    env = env_utils.env_name()
    if not env_utils.is_prod():
        pytest.skip("import-time freeze is asserted by the APP_ENV=production CI job")

    import main as app_main

    assert app_main._IS_PROD is True
    assert app_main._APP_ENV == env
    assert app_main.app.docs_url is None
    assert app_main.app.redoc_url is None
    assert app_main.app.openapi_url is None


def test_staging_is_production_at_import_time(tmp_path: Path) -> None:
    """APP_ENV=staging requires a key, rejects unsigned Twilio, refuses an
    unauthenticated WS upgrade, and does not publish /docs.

    Process env is empty of APP_ENV; staging sits only in a temp .env so this
    is the bare-metal path WP-012 opened, not a Compose injection.
    """
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=staging\nWP013_CANARY=from-temp-dotenv\n", encoding="utf-8")
    probe = f"""
import asyncio
import os
from pathlib import Path
from starlette.responses import Response

for key in (
    "APP_ENV",
    "WP013_CANARY",
    "API_KEY",
    "API_KEY_MAP",
    "ALLOW_UNHARDENED_PRODUCTION",
    "ALLOW_ACTOR_HEADER",
    "TWILIO_AUTH_TOKEN",
    "VOICE_WS_PROXY_SECRET",
):
    os.environ.pop(key, None)

import env_loader
env_loader._ENV_FILE = Path({str(env_file)!r})
env_loader._LOADED = False

import main
from routers import telephony as telephony_routes
import actor_context
actor_context.reload_api_key_map()

print("WP013_APP_ENV=" + main._APP_ENV)
print("WP013_IS_PROD=" + str(main._IS_PROD))
print("WP013_CANARY=" + (os.environ.get("WP013_CANARY") or ""))
print("WP013_DOCS=" + str(main.app.docs_url))
print("WP013_REDOC=" + str(main.app.redoc_url))
print("WP013_OPENAPI=" + str(main.app.openapi_url))

try:
    main._assert_hardening_gate()
    print("WP013_HARDENING=passed")
except RuntimeError:
    print("WP013_HARDENING=refused")
print("WP013_INACTIVE=" + ";".join(main._inactive_hardening_controls()))

has_auth = bool(
    (os.getenv("API_KEY") or "").strip() or actor_context.parse_api_key_map()
)
print("WP013_REFUSES_CREDENTIALS=" + str(main._IS_PROD and not has_auth))
print("WP013_ALLOW_ACTOR_HEADER=" + str(actor_context._allow_actor_header()))
print("WP013_APP_IS_PROD=" + str(actor_context._app_is_prod()))

class _TwilioReq:
    headers = {{}}
    url = type("U", (), {{"path": "/twilio/voice/incoming", "query": ""}})()

print("WP013_TWILIO_UNSIGNED=" + str(telephony_routes._twilio_signature_ok(_TwilioReq(), {{}})))

class _WS:
    headers = {{}}
    query_params = {{}}

print("WP013_WS_AUTH=" + str(telephony_routes._voice_ws_upgrade_authorized(_WS())))

class _Req:
    method = "GET"
    url = type("U", (), {{"path": "/conversations"}})()
    headers = {{}}

class _Health:
    method = "GET"
    url = type("U", (), {{"path": "/health"}})()
    headers = {{}}

async def _next(request):
    return Response("ok", status_code=200)

mw = main.ApiKeyMiddleware(app=lambda *_a, **_k: None)
crm = asyncio.run(mw.dispatch(_Req(), _next))
health = asyncio.run(mw.dispatch(_Health(), _next))
print("WP013_CRM_STATUS=" + str(crm.status_code))
print("WP013_HEALTH_STATUS=" + str(health.status_code))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    lines = {
        line.split("=", 1)[0].removeprefix("WP013_"): line.split("=", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("WP013_")
    }
    assert lines.get("CANARY") == "from-temp-dotenv"
    assert lines.get("APP_ENV") == "staging"
    assert lines.get("IS_PROD") == "True"
    assert lines.get("DOCS") == "None"
    assert lines.get("REDOC") == "None"
    assert lines.get("OPENAPI") == "None"
    # The gate reads the database's controls; a production-named process is
    # refused exactly when one is off, and boots when every control is on.
    assert lines.get("HARDENING") == ("refused" if lines.get("INACTIVE") else "passed")
    assert lines.get("REFUSES_CREDENTIALS") == "True"
    assert lines.get("ALLOW_ACTOR_HEADER") == "False"
    assert lines.get("APP_IS_PROD") == "True"
    assert lines.get("TWILIO_UNSIGNED") == "False"
    assert lines.get("WS_AUTH") == "False"
    assert lines.get("CRM_STATUS") == "401"
    assert lines.get("HEALTH_STATUS") == "200"


def test_a_typo_is_production_at_import_time(tmp_path: Path) -> None:
    """``dvelopment`` is not a laptop name. The two-string allowlist treated it as one."""
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=dvelopment\n", encoding="utf-8")
    probe = f"""
import os
from pathlib import Path

for key in ("APP_ENV", "API_KEY", "API_KEY_MAP", "ALLOW_UNHARDENED_PRODUCTION"):
    os.environ.pop(key, None)

import env_loader
env_loader._ENV_FILE = Path({str(env_file)!r})
env_loader._LOADED = False

import main
print("WP013_APP_ENV=" + main._APP_ENV)
print("WP013_IS_PROD=" + str(main._IS_PROD))
print("WP013_DOCS=" + str(main.app.docs_url))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    lines = {
        line.split("=", 1)[0].removeprefix("WP013_"): line.split("=", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("WP013_")
    }
    assert lines.get("APP_ENV") == "dvelopment"
    assert lines.get("IS_PROD") == "True"
    assert lines.get("DOCS") == "None"
