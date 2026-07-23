"""Meta WhatsApp Cloud API helpers (inbound verify + outbound send).

Inbound Meta webhooks are separate from outbound CRM webhook_endpoints.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


BASE = Path(__file__).parent


def _read_env(key: str, default: str | None = None) -> str | None:
    value = os.getenv(key)
    if value is not None and value != "":
        return value
    env_file = BASE / ".env"
    if not env_file.exists():
        return default
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k == key:
            return v if v != "" else default
    return default


def config() -> dict[str, str | None]:
    return {
        "app_id": _read_env("META_APP_ID"),
        "app_secret": _read_env("WHATSAPP_APP_SECRET"),
        "token": _read_env("WHATSAPP_TOKEN"),
        "phone_number_id": _read_env("WHATSAPP_PHONE_NUMBER_ID"),
        "waba_id": _read_env("WHATSAPP_WABA_ID"),
        "display_number": _read_env("WHATSAPP_DISPLAY_NUMBER"),
        "api_version": _read_env("WHATSAPP_API_VERSION", "v25.0"),
        "verify_token": _read_env("WHATSAPP_VERIFY_TOKEN"),
        "public_base_url": _read_env("PUBLIC_BASE_URL"),
    }


def normalize_phone(value: str | None) -> str:
    if not value:
        return ""
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits


def verify_signature(app_secret: str | None, raw_body: bytes, header: str | None) -> bool:
    """Validate X-Hub-Signature-256 = sha256=<hex>."""
    if not app_secret or not header:
        return False
    prefix = "sha256="
    if not header.startswith(prefix):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = header[len(prefix) :].strip()
    return hmac.compare_digest(expected, provided)


def send_text_message(*, to_phone: str, body: str) -> dict[str, Any]:
    """Send a free-form WhatsApp text message. Raises ValueError on API/config errors."""
    cfg = config()
    token = cfg["token"]
    phone_number_id = cfg["phone_number_id"]
    version = cfg["api_version"] or "v25.0"
    if not token or not phone_number_id:
        raise ValueError("whatsapp_not_configured")
    to = normalize_phone(to_phone)
    if not to:
        raise ValueError("whatsapp_missing_recipient")
    url = f"https://graph.facebook.com/{version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(_classify_send_error(exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"whatsapp_send_failed:network:{exc.reason}") from exc


def _classify_send_error(status: int, detail: str) -> str:
    """Map Meta Graph errors to stable machine codes the inbox UI can friendlify."""
    code = None
    subcode = None
    message = ""
    try:
        payload = json.loads(detail) if detail else {}
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict):
            code = err.get("code")
            subcode = err.get("error_subcode")
            message = str(err.get("message") or "")
    except json.JSONDecodeError:
        pass

    # OAuthException 190 = invalid/expired token; 463 = session expired.
    if status == 401 or code == 190:
        if subcode == 463 or "expired" in message.lower():
            return "whatsapp_token_expired"
        return "whatsapp_token_invalid"

    return f"whatsapp_send_failed:{status}:{detail[:400]}"


def extract_wamid(send_response: dict[str, Any]) -> str | None:
    messages = send_response.get("messages") or []
    if not messages:
        return None
    return messages[0].get("id")
