from types import SimpleNamespace

from pipecat.utils.run_context import run_id_var

from api.logging_config import enrich_log_record


def _record(level: int, extra: dict | None = None) -> dict:
    return {
        "level": SimpleNamespace(no=level),
        "extra": dict(extra or {}),
    }


def test_error_without_classification_gets_operator_fallback():
    token = run_id_var.set("2250")
    try:
        record = _record(40)
        enrich_log_record(record)
    finally:
        run_id_var.reset(token)

    assert record["extra"] == {
        "run_id": "2250",
        "error_owner": "operator",
        "error_type": "system_error",
        "error_source": "platform",
        "error_code": "unclassified-error",
        "classified": True,
        "classification_mode": "fallback",
    }


def test_explicit_error_classification_is_preserved():
    record = _record(
        40,
        {
            "error_owner": "user",
            "error_type": "config_error",
            "error_source": "stt",
            "error_code": "deepgram-401",
            "classified": False,
        },
    )

    enrich_log_record(record)

    assert record["extra"]["error_owner"] == "user"
    assert record["extra"]["error_type"] == "config_error"
    assert record["extra"]["error_source"] == "stt"
    assert record["extra"]["error_code"] == "deepgram-401"
    assert record["extra"]["classified"] is True
    assert record["extra"]["classification_mode"] == "explicit"


def test_partial_error_classification_falls_back_as_a_unit():
    record = _record(40, {"error_owner": "user", "error_type": "config_error"})

    enrich_log_record(record)

    assert record["extra"]["error_owner"] == "operator"
    assert record["extra"]["error_type"] == "system_error"
    assert record["extra"]["error_source"] == "platform"
    assert record["extra"]["error_code"] == "unclassified-error"
    assert record["extra"]["classification_mode"] == "fallback"


def test_token_and_phone_numbers_are_masked_in_every_line():
    """Run 88: the media socket token and the full callee and caller numbers were logged."""
    record = {**_record(20), "message": (
        "to phone number +919876543210; Selected phone number +14155550123; "
        "GET /api/v1/telephony/ws/4/1/88/0123456789abcdef0123 101; at +05:30"
    )}
    enrich_log_record(record)
    assert "9876543210" not in record["message"] and "+…3210" in record["message"]
    assert "4155550123" not in record["message"] and "+…0123" in record["message"]
    assert "0123456789abcdef" not in record["message"] and "/88/[REDACTED]" in record["message"]
    assert "+05:30" in record["message"]


def test_warning_only_gets_run_context():
    record = _record(30)

    enrich_log_record(record)

    assert record["extra"] == {"run_id": None}
