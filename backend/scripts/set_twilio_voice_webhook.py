"""Set Twilio Incoming Phone Number Voice + status callbacks to PUBLIC_BASE_URL."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from env_loader import load_env

load_env()

from twilio.rest import Client  # noqa: E402
from voice import twilio_ops  # noqa: E402


def main() -> int:
    sid = twilio_ops.account_sid()
    token = twilio_ops.auth_token()
    phone = twilio_ops.twilio_phone()
    base = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
    if not (sid and token and phone and base):
        print(
            "missing_config",
            f"sid={bool(sid)} token={bool(token)} phone={bool(phone)} base={bool(base)}",
        )
        return 1
    voice_url = f"{base}/twilio/voice/incoming"
    fallback_url = twilio_ops.voice_fallback_url() or f"{base}/twilio/voice/fallback"
    status_callback = (
        twilio_ops.call_status_callback_url() or f"{base}/twilio/voice/call-status"
    )
    client = Client(sid, token)
    nums = client.incoming_phone_numbers.list(phone_number=phone, limit=5)
    if not nums:
        digits = twilio_ops.digits_only(phone)
        nums = [
            n
            for n in client.incoming_phone_numbers.list(limit=50)
            if twilio_ops.digits_only(n.phone_number) == digits
        ]
    if not nums:
        print("phone_not_found_in_account", phone)
        return 2
    n = nums[0]
    updated = client.incoming_phone_numbers(n.sid).update(
        voice_url=voice_url,
        voice_method="POST",
        voice_fallback_url=fallback_url,
        voice_fallback_method="POST",
        status_callback=status_callback,
        status_callback_method="POST",
    )
    print("ok")
    print("phone", updated.phone_number)
    print("sid", updated.sid)
    print("voice_url", updated.voice_url)
    print("voice_method", updated.voice_method)
    print("voice_fallback_url", updated.voice_fallback_url)
    print("voice_fallback_method", updated.voice_fallback_method)
    print("status_callback", updated.status_callback)
    print("status_callback_method", updated.status_callback_method)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
