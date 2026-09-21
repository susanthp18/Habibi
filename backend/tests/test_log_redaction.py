"""Logs exist, and nothing in them is a borrower's phone number.

Two failures that compounded each other.

``setup_logging()`` returned immediately unless ``LOG_FORMAT=json``, and that
variable appeared nowhere in a 656-line ``.env.example``. Nothing else
configured the root logger in ``api``, so every
``logger.info`` was discarded and WARNING+ fell to ``logging.lastResort``
unformatted. A shadow run you cannot read is not a shadow run.

And because redaction lived *inside* the JSON formatter, it never ran either.
So the obvious fix — install a plain handler so INFO survives — would have
created an indefinitely-retained, well-indexed store of borrower phone numbers
in a different format. Redaction is a filter on the handler for that reason: it
does not care which formatter is installed, and it covers loguru's
``InterceptHandler`` on the voice path, which had no scrubbing of any kind.
"""

from __future__ import annotations

import io
import json
import logging

import pytest

import observability
import pii_redact

#: A number in the form `outbound.place` actually passes as `to_phone`. The old
#: detector required a literal "+91" and matched none of it.
BARE = "9876543210"


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch):
    """A root logger with one stream handler, restored afterwards."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    buf = io.StringIO()
    root.handlers = [logging.StreamHandler(buf)]
    try:
        yield buf
    finally:
        root.handlers, root.level = saved_handlers, saved_level


# --- the sub-gate: the detector has to match what is actually stored ---------


@pytest.mark.parametrize(
    "raw",
    [
        BARE,
        "919876543210",
        "+919876543210",
        "+91 98765 43210",
        "+91-98765-43210",
        "098765 43210",
    ],
)
def test_every_written_form_of_an_indian_mobile_is_masked(raw: str) -> None:
    assert BARE not in pii_redact.redact_text(f"dialling {raw}")
    assert "••" in pii_redact.redact_text(f"dialling {raw}")


@pytest.mark.parametrize(
    "raw",
    [
        "1234567890",  # not a mobile: Indian mobiles start 6-9
        "50100234567890",  # a 14-digit account number
        "amount 45000",
        "2026-09-05",
    ],
)
def test_the_detector_does_not_bite_things_that_are_not_phones(raw: str) -> None:
    """Widening this pattern must not start masking amounts and account ids."""
    assert pii_redact.redact_text(raw) == raw


def test_a_card_is_still_the_card_detectors_job() -> None:
    """Order matters: card runs before phone, so a 16-digit card is not eaten."""
    assert pii_redact.redact_text("4111 1111 1111 1111") == "**** **** **** 1111"


def test_lowercase_pan_is_masked() -> None:
    raw = "pan abcde1234f on file"
    out = pii_redact.redact_text(raw)
    assert "abcde1234f" not in out.lower()
    assert "[REDACTED-PAN]" in out
    assert pii_redact.redact_text("ABCDE1234F") == "[REDACTED-PAN]"


def test_unspaced_aadhaar_is_masked() -> None:
    spaced = pii_redact.redact_text("aadhaar 1234 5678 9012")
    unspaced = pii_redact.redact_text("aadhaar 123456789012")
    assert "1234 5678 9012" not in spaced
    assert "123456789012" not in unspaced
    assert "9012" in unspaced


def test_ifsc_is_masked_after_card_and_pan() -> None:
    out = pii_redact.redact_text("transfer to HDFC0001234")
    assert "HDFC0001234" not in out
    assert "[REDACTED-IFSC]" in out
    # PAN is 10 chars and must not be stolen by the 11-char IFSC pattern.
    assert pii_redact.redact_text("ABCDE1234F") == "[REDACTED-PAN]"
    assert "[REDACTED-IFSC]" not in pii_redact.redact_text("ABCDE1234F")


def test_labelled_pin_and_address_are_masked_free_text_is_not() -> None:
    pin = pii_redact.redact_text("pincode 400001 please")
    assert "400001" not in pin
    assert "******" in pin
    labelled = pii_redact.redact_text("addr: 12 MG Road, Bandra")
    assert "12 MG Road" not in labelled
    assert "[REDACTED-ADDRESS]" in labelled
    spoken = pii_redact.redact_text("I live near the station, last four 4821")
    assert "I live near the station" in spoken
    assert "4821" in spoken
    assert pii_redact.redact_text("account 99887766") == "account 99887766"


# --- logs exist at all ------------------------------------------------------


def test_info_survives_when_log_format_is_unset(captured, monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole defect: this used to return before installing anything."""
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    observability.setup_logging()
    logging.getLogger("demo").info("hello")
    assert "hello" in captured.getvalue()


def test_the_plain_formatter_is_still_the_default(captured, monkeypatch: pytest.MonkeyPatch) -> None:
    """Switching a developer's terminal to JSON would not be an improvement."""
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    observability.setup_logging()
    logging.getLogger("demo").info("hello")
    with pytest.raises(json.JSONDecodeError):
        json.loads(captured.getvalue().strip())


# --- and nothing in them is PII ---------------------------------------------


def test_the_plain_path_scrubs_the_message(captured, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redaction used to be a property of the JSON formatter, so this leaked."""
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    observability.setup_logging()
    logging.getLogger("demo").info("dialling %s", BARE)
    assert BARE not in captured.getvalue()


def test_interpolated_args_are_scrubbed_not_just_the_template(
    captured, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``logger.info("dialling %s", phone)`` keeps the number in record.args.

    A scrub of ``record.msg`` alone would mask nothing here, which is why the
    filter renders the message and clears the args.
    """
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    observability.setup_logging()
    logging.getLogger("demo").info("dialling %s", BARE)
    assert BARE not in captured.getvalue()
    assert "••" in captured.getvalue()


def test_extra_fields_are_scrubbed(captured, monkeypatch: pytest.MonkeyPatch) -> None:
    """`extra` is where a phone number most often reaches a log line."""
    monkeypatch.setenv("LOG_FORMAT", "json")
    observability.setup_logging()
    logging.getLogger("demo").info("reached", extra={"to": BARE})
    payload = json.loads(captured.getvalue().strip())
    assert BARE not in json.dumps(payload)
    assert "••" in payload["to"]


@pytest.mark.parametrize("fmt", ["", "json"])
def test_tracebacks_are_scrubbed(captured, monkeypatch: pytest.MonkeyPatch, fmt: str) -> None:
    """A traceback carries the arguments that raised."""
    monkeypatch.setenv("LOG_FORMAT", fmt)
    observability.setup_logging()
    try:
        raise ValueError(f"{BARE} is not a valid amount")
    except ValueError:
        logging.getLogger("demo").exception("dial failed")
    assert BARE not in captured.getvalue()


def test_a_failing_scrubber_withholds_the_text_rather_than_emitting_it(
    captured, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old behaviour was ``except Exception: pass`` — emit it raw.

    That is exactly backwards: the scrubber is most likely to raise on input it
    did not expect, which is the input most likely to be worth withholding.
    """
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    observability.setup_logging()

    def _explode(_text):
        raise RuntimeError("detector blew up")

    monkeypatch.setattr(pii_redact, "redact_text", _explode)
    logging.getLogger("demo").info("dialling %s", BARE)

    out = captured.getvalue()
    assert BARE not in out
    assert observability.REDACTION_FAILED in out


# --- the voice half of the stream -------------------------------------------


def test_loguru_messages_are_scrubbed_including_pipecats_own() -> None:
    """Pipecat logs straight to loguru and never touches stdlib.

    A stdlib filter cannot see those records, so ``install()`` also registers a
    loguru patcher. Before that, this half of the stream had no scrubbing at all.
    """
    from loguru import logger

    from voice import log_bridge

    buf = io.StringIO()
    logger.remove()
    logger.add(buf, format="{message}")
    try:
        log_bridge.install()
        logger.info(f"pipecat dialling {BARE}")
        logging.getLogger("product").info("dialling %s", BARE)
        out = buf.getvalue()
    finally:
        logger.remove()
        logger.configure(patcher=None)
    assert BARE not in out
    assert out.count("••") >= 2, "both halves of the stream must be scrubbed"


def test_the_voice_entrypoint_installs_the_bridge() -> None:
    """The surviving voice entrypoint must install the loguru bridge."""
    from voice import bot, log_bridge

    assert bot.log_bridge is log_bridge
    assert callable(log_bridge.install)


def test_the_logging_env_vars_are_documented() -> None:
    """LOG_FORMAT appeared zero times in .env.example, which is most of why
    nobody noticed setup_logging was a no-op."""
    from tests.test_one_clock_one_environment import _template_keys

    keys = _template_keys()
    for key in ("LOG_FORMAT", "LOG_LEVEL", "SENTRY_DSN", "APP_RELEASE"):
        assert key in keys, f"{key} is undocumented"
