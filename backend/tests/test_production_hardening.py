"""Wave-0/1 production hardening regressions (identity, auth, routing, sandbox)."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_twilio_auth_exempt_matches_voice_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Twilio webhook paths bypass API-key auth; lookalike paths do not.

    Driven through the real ApiKeyMiddleware rather than a local copy of its
    predicate — an inline reimplementation would keep passing after the
    middleware's matching rule changed.
    """
    from fastapi.testclient import TestClient

    import main as app_main

    prefixes = app_main._AUTH_EXEMPT_PREFIXES
    # Signature-validated Twilio voice webhooks are exempt. A blanket
    # "/twilio" left POST /twilio/voice/outbound dialling arbitrary PSTN
    # numbers for anyone on the internet.
    assert "/twilio/voice/incoming" in prefixes
    assert "/twilio/voice/fallback" in prefixes
    assert "/twilio/voice/stream-status" in prefixes
    assert "/twilio/voice/call-status" in prefixes
    assert "/twilio" not in prefixes
    assert "/twilio/voice/incoming/" not in prefixes  # trailing slash breaks startswith

    import actor_context

    monkeypatch.setenv("API_KEY", "test-key-auth-exempt")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    actor_context.reload_api_key_map()
    client = TestClient(app_main.app)
    try:
        # Exempt: reaches the route (signature validation rejects it, not auth).
        res = client.post("/twilio/voice/incoming", data={})
        assert res.status_code != 401, res.text
        assert client.post("/twilio/voice/fallback", data={}).status_code != 401
        assert client.post("/twilio/voice/stream-status", data={}).status_code != 401
        assert client.post("/twilio/voice/call-status", data={}).status_code != 401

        # A path that merely shares the prefix is NOT exempt.
        res = client.get("/twilio-admin/secrets")
        assert res.status_code == 401, res.text

        # The control-plane routes under /twilio are NOT exempt: outbound places
        # a real billable call, status leaks the number and media-stream URL.
        assert (
            client.post("/twilio/voice/outbound", json={"to": "+10000000000"}).status_code
            == 401
        )
        assert client.get("/twilio/voice/status").status_code == 401

        # Regular CRM route still requires the key.
        assert client.get("/conversations").status_code == 401
    finally:
        # Restore the environment BEFORE rebuilding the cache, and do it even
        # when an assertion fails: reloading first cached the map for this
        # test's own stripped environment, leaking into every later test.
        monkeypatch.undo()
        actor_context.reload_api_key_map()


def test_politics_guardrail_ignores_third_party() -> None:
    from agent_core.guardrails import evaluate_guardrails

    flags = evaluate_guardrails(
        customer_text="I want third party insurance coverage for my car.",
        bot_text="I can help with third party motor cover.",
        intent="product_inquiry",
        guardrails={"refusePoliticsReligion": True},
        turn_index=2,
        elapsed_seconds=10,
        customer_bot_exchanges=1,
    )
    assert "politics-religion" not in flags
    assert "politics-religion-engaged" not in flags


def test_politics_guardrail_still_flags_elections() -> None:
    from agent_core.guardrails import evaluate_guardrails

    flags = evaluate_guardrails(
        customer_text="Who should I vote for in the election?",
        bot_text="ok",
        intent="other",
        guardrails={"refusePoliticsReligion": True},
        turn_index=1,
        elapsed_seconds=1,
        customer_bot_exchanges=0,
    )
    assert "politics-religion" in flags


def test_routing_numeric_missing_field_is_false() -> None:
    import db

    assert (
        db._routing_eval_condition(
            {"field": "avgSentiment", "op": "<", "value": -0.35},
            {},
        )
        is False
    )
    assert (
        db._routing_eval_condition(
            {"field": "avgSentiment", "op": "<", "value": -0.35},
            {"avgSentiment": "hot"},
        )
        is False
    )
    assert (
        db._routing_eval_condition(
            {"field": "avgSentiment", "op": "<", "value": -0.35},
            {"avgSentiment": -0.9},
        )
        is True
    )


def _file_backed_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """voice_session_store pinned to the filesystem backend under tmp_path."""
    import voice_session_store

    monkeypatch.setattr(voice_session_store, "_SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(voice_session_store, "_backend", "file")
    return voice_session_store


def test_voice_sandbox_rejects_path_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import voice_sandbox

    _file_backed_store(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="invalid_session_id"):
        voice_sandbox.session_path("../etc/passwd")
    with pytest.raises(ValueError, match="invalid_session_id"):
        voice_sandbox.read_session("VS-notahex!!")


def test_voice_sandbox_accepts_canonical_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import voice_sandbox

    _file_backed_store(tmp_path, monkeypatch)
    sid = "VS-ABCDEF0123"
    path = voice_sandbox.session_path(sid)
    assert path.parent == tmp_path
    voice_sandbox.write_session(sid, {"ok": True})
    assert voice_sandbox.read_session(sid) == {"ok": True}


def test_voice_session_id_discriminates_transport_ids() -> None:
    """A pipecat-minted uuid4 must never be treated as a sandbox session id.

    The standalone runner sets ``runner_args.session_id = str(uuid4())`` for
    every offer. Accepting it raised ``invalid_session_id`` on every Live call
    and dropped persona / KB snapshot / tuning.
    """
    import voice_session_store as store

    assert store.is_session_id("VS-ABCDEF0123")
    assert not store.is_session_id("a1424818-183c-4c40-a317-acd6c5d36c64")
    assert not store.is_session_id("VS-abcdef0123")  # lowercase hex
    assert not store.is_session_id("VS-ABCDEF012")  # too short
    assert not store.is_session_id("")
    assert not store.is_session_id(None)


def test_voice_session_store_mutate_is_atomic_and_reports_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _file_backed_store(tmp_path, monkeypatch)
    sid = "VS-0123456789"

    assert store.mutate(sid, lambda cur: cur) is None  # missing, not an error

    store.write(sid, {"tuning": {"llm": {"temperature": 0.1}}, "status": "starting"})
    updated = store.mutate(sid, lambda cur: {**cur, "status": "live"})
    assert updated["status"] == "live"
    assert updated["tuning"] == {"llm": {"temperature": 0.1}}
    assert store.read(sid)["status"] == "live"


def test_voice_session_store_mutate_propagates_handler_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller's own exception must not be reported as a store outage."""
    store = _file_backed_store(tmp_path, monkeypatch)
    sid = "VS-0123456789"
    store.write(sid, {"status": "starting"})

    def _boom(_cur: dict) -> dict:
        raise KeyError("caller_bug")

    with pytest.raises(KeyError, match="caller_bug"):
        store.mutate(sid, _boom)


def test_sandbox_session_id_from_runner_args() -> None:
    """Only a canonical id is accepted, from any of the three body shapes."""
    import json as _json
    from types import SimpleNamespace

    from voice.bot import _sandbox_session_id_from
    from voice_session_store import is_session_id

    def _resolve(*, body=None, session_id=None) -> str | None:
        args = SimpleNamespace(body=body, session_id=session_id)
        return _sandbox_session_id_from(args, is_session_id)

    # SmallWebRTC requestData → runner_args.body
    assert _resolve(body={"sessionId": "VS-ABCDEF0123"}) == "VS-ABCDEF0123"
    assert _resolve(body={"session_id": "VS-ABCDEF0123"}) == "VS-ABCDEF0123"
    # /start runner path nests it one level deeper
    assert _resolve(body={"body": {"sessionId": "VS-ABCDEF0123"}}) == "VS-ABCDEF0123"
    # raw JSON string body
    assert _resolve(body=_json.dumps({"sessionId": "VS-ABCDEF0123"})) == "VS-ABCDEF0123"
    # embedded host threads our id through session_id
    assert _resolve(session_id="VS-ABCDEF0123") == "VS-ABCDEF0123"

    # The standalone runner's uuid4 is not a sandbox session.
    assert _resolve(session_id="a1424818-183c-4c40-a317-acd6c5d36c64") is None
    assert _resolve(body={}) is None
    assert _resolve(body="not json") is None
    assert _resolve() is None


def test_offer_url_carries_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """The offer URL is the channel the stock pipecat runner actually honours.

    Its /api/offer binds the body to the SmallWebRTCRequest dataclass, whose
    field is ``request_data``; the JS transport only ever sends camelCase
    ``requestData``, so FastAPI drops it. The route's ``session_id`` query
    parameter is threaded into runner_args.session_id instead.
    """
    import voice_sandbox

    monkeypatch.setattr(voice_sandbox, "_WEBRTC_PUBLIC", "/voice-rtc/api/offer")
    assert (
        voice_sandbox._offer_url_for("VS-ABCDEF0123")
        == "/voice-rtc/api/offer?session_id=VS-ABCDEF0123"
    )

    # An operator-supplied URL that already has a query keeps it.
    monkeypatch.setattr(voice_sandbox, "_WEBRTC_PUBLIC", "https://edge/api/offer?region=in")
    assert (
        voice_sandbox._offer_url_for("VS-ABCDEF0123")
        == "https://edge/api/offer?region=in&session_id=VS-ABCDEF0123"
    )


def test_embedded_host_reads_session_id_from_body_or_query() -> None:
    """Both hosting modes must resolve the id the same way."""
    from voice.host import _session_id_from

    assert _session_id_from({"sessionId": "VS-ABCDEF0123"}) == "VS-ABCDEF0123"
    assert _session_id_from({"session_id": "VS-ABCDEF0123"}) == "VS-ABCDEF0123"
    # Body wins when both are present, query is the fallback.
    assert _session_id_from({"sessionId": "VS-AAAAAAAAAA"}, "VS-BBBBBBBBBB") == "VS-AAAAAAAAAA"
    assert _session_id_from(None, "VS-BBBBBBBBBB") == "VS-BBBBBBBBBB"
    assert _session_id_from(None, None) is None


def test_rtvi_function_call_report_level_is_a_map() -> None:
    """RTVIObserver looks levels up with ``.get("*")`` — a bare enum crashes it.

    Passing the enum raised ``'RTVIFunctionCallReportLevel' object has no
    attribute 'get'`` inside the observer task on the first tool call of every
    call, so no llm-function-call-* event ever reached the client.
    """
    pytest.importorskip("pipecat.processors.frameworks.rtvi")
    from pipecat.processors.frameworks.rtvi import RTVIObserverParams

    default = RTVIObserverParams().function_call_report_level
    assert isinstance(default, dict), "upstream contract changed — revisit voice/bot.py"
    assert "*" in default


def test_interleave_stereo_truncates_odd_bytes() -> None:
    from voice.recording import _interleave_stereo

    # 3 bytes on user (odd) must not raise / mis-align int16 view.
    out = _interleave_stereo(b"\x01\x02\x03", b"\x04\x05")
    assert len(out) % 4 == 0  # stereo int16 frames


def test_webhook_url_rejects_private(monkeypatch: pytest.MonkeyPatch) -> None:
    import ops_screens

    with pytest.raises(ValueError):
        ops_screens._validate_webhook_url("http://127.0.0.1/hooks")
    with pytest.raises(ValueError):
        ops_screens._validate_webhook_url("https://192.168.1.1/hooks")
    ops_screens._validate_webhook_url("https://hooks.example.com/crm")


def test_storage_requires_minio_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    import storage

    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "")
    monkeypatch.setenv("MINIO_SECRET_KEY", "")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(storage, "load_env", lambda: None)
    with pytest.raises(storage.StorageConfigError):
        storage._cfg()


def test_whatsapp_definite_client_error_classification() -> None:
    import whatsapp as wa

    assert wa.is_definite_client_error("whatsapp_token_expired")
    assert wa.is_definite_client_error("whatsapp_send_failed:400:{\"error\":{}}")
    assert not wa.is_definite_client_error("whatsapp_send_failed:network:timed out")
    assert not wa.is_definite_client_error("whatsapp_send_failed:503:upstream")


def test_whatsapp_ambiguous_transport_error() -> None:
    import whatsapp as wa

    assert wa.is_ambiguous_transport_error("whatsapp_send_failed:network:reset")
    assert wa.is_ambiguous_transport_error("whatsapp_send_failed:503:busy")
    assert not wa.is_ambiguous_transport_error("whatsapp_send_failed:400:bad request")


def test_billing_as_of_uses_utc_date() -> None:
    from datetime import date, datetime, timezone
    from unittest.mock import patch

    import db

    fake_now = datetime(2026, 7, 25, 22, 30, tzinfo=timezone.utc)
    with patch("db.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        assert db._billing_as_of() == date(2026, 7, 25)


def test_amd_voicemail_script_constant() -> None:
    from voice import amd

    assert hasattr(amd, "VOICEMAIL_SCRIPT")
    assert "Priya" in amd.VOICEMAIL_SCRIPT
    assert not hasattr(amd, "VOICMAIL_SCRIPT")


def test_result_to_llm_canonical_keys_win() -> None:
    from agent_core.tools.domain import ToolResult

    r = ToolResult(ok=True, data={"ok": False, "error": "stale", "say": "old"}, spoken_summary="new")
    out = r.to_llm()
    assert out["ok"] is True
    assert out["say"] == "new"
    assert out.get("error") != "stale"


def test_hindi_payment_alone_not_language_switch() -> None:
    from voice.safety import detect_language_signal

    assert detect_language_signal("I want to make a payment today") is None
    assert detect_language_signal("haan theek hai") == "hi-IN"


class _FakeResult:
    def __init__(self, rows: list[tuple] | None = None) -> None:
        self._rows = rows or []

    def fetchall(self) -> list[tuple]:
        return self._rows


class _FakeConn:
    """Minimal stateful stand-in for a SQLAlchemy Connection.

    Applies kb_ingest._mark_job_failed's document UPDATE against an in-memory
    table so the *behaviour* is asserted, not the SQL text. A source-string
    assertion passes for any rewrite that keeps the substring and fails for any
    equivalent rewrite that does not — neither of which says anything about
    whether indexed documents survive a failed reindex.
    """

    def __init__(self, docs: dict[str, str], chunked: set[str]) -> None:
        self.docs = docs
        self.chunked = chunked
        self.jobs: dict[str, str] = {}

    def execute(self, statement, params=None):  # noqa: ANN001 - test double
        sql = " ".join(str(statement).split())
        params = params or {}
        if "UPDATE kb_index_jobs" in sql:
            self.jobs[params["id"]] = "failed"
            return _FakeResult()
        if "UPDATE kb_documents" in sql:
            doc_id = params["id"]
            current = self.docs.get(doc_id)
            if current is None or current in ("indexed", "stale"):
                return _FakeResult()
            # CASE ... WHEN EXISTS (chunks) THEN status ELSE 'failed'
            if doc_id not in self.chunked:
                self.docs[doc_id] = "failed"
            return _FakeResult()
        raise AssertionError(f"unexpected statement: {sql}")


def test_kb_mark_job_failed_preserves_indexed_status() -> None:
    """A failed reindex must not blank a document that still serves chunks."""
    import kb_ingest

    docs = {
        "doc-indexed": "indexed",
        "doc-stale": "stale",
        # Mid-reindex (enqueue_index_job sets 'indexing') but chunks remain.
        "doc-indexing-with-chunks": "indexing",
        # Never successfully indexed and has no chunks.
        "doc-fresh": "indexing",
    }
    conn = _FakeConn(docs, chunked={"doc-indexed", "doc-stale", "doc-indexing-with-chunks"})

    for doc_id in list(docs):
        kb_ingest._mark_job_failed(conn, f"job-{doc_id}", doc_id, "embed failed")

    # Protected statuses are untouched.
    assert docs["doc-indexed"] == "indexed"
    assert docs["doc-stale"] == "stale"
    # Serviceable chunks keep the document out of 'failed'.
    assert docs["doc-indexing-with-chunks"] == "indexing"
    # Nothing to serve → 'failed' is correct.
    assert docs["doc-fresh"] == "failed"
    # Every job row is recorded as failed regardless.
    assert set(conn.jobs.values()) == {"failed"}


def test_upload_cap_helper_exists() -> None:
    import main as app_main

    assert callable(app_main._read_upload_capped)
    assert app_main._MAX_UPLOAD_BYTES > 0


def test_circuit_breaker_ignores_caller_errors() -> None:
    from circuit_breaker import CircuitBreaker

    class CallerError(ValueError):
        pass

    b = CircuitBreaker("t", failure_threshold=1, ignore_exceptions=(CallerError,))
    with pytest.raises(CallerError):
        b.call(lambda: (_ for _ in ()).throw(CallerError("nope")))
    assert b.snapshot()["failures"] == 0


def test_coach_status_rejects_unknown() -> None:
    import followups_db as f

    with pytest.raises(ValueError, match="invalid_coaching_status"):
        f._require_coach_status("canceled")
    assert f._require_coach_status("completed") == "done"


def test_request_documents_rejects_invalid_type() -> None:
    from agent_core.tools import domain

    r = domain.request_documents(customer_id="c1", document_type="not-a-type")
    assert r.ok is False
    assert r.error == "invalid_document_type"


def test_abuse_lexicon_shared_with_guardrails() -> None:
    from agent_core.guardrails import evaluate_guardrails
    from agent_core.sentiment import ABUSE_LEXICON

    assert "stfu" in ABUSE_LEXICON
    flags = evaluate_guardrails(
        customer_text="you idiot shut up",
        bot_text="ok",
        intent="other",
        guardrails={"escalateAbuse": True},
        turn_index=1,
        elapsed_seconds=1,
        customer_bot_exchanges=0,
    )
    assert "auto-escalate" in flags


def test_deployment_env_dedupe() -> None:
    from agent_core import deployment

    seen: list[str] = []

    def fake_get(*, bot_id=None, environment="production"):
        seen.append(environment)
        return None

    import db

    original = db.get_active_deployment
    db.get_active_deployment = fake_get  # type: ignore[assignment]
    try:
        try:
            deployment.load_active_bundle(
                "production",
                fallback_environments=("production", "sandbox"),
            )
        except KeyError:
            pass
        assert seen == ["production", "sandbox"]
    finally:
        db.get_active_deployment = original  # type: ignore[assignment]


def test_twilio_signature_fail_closed_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    import main as app_main

    monkeypatch.setattr(app_main, "_IS_PROD", True)

    class _Req:
        headers: dict[str, str] = {}
        url = type("U", (), {"path": "/twilio/voice/incoming"})()

    # No auth token → fail closed in production.
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")
    from voice import twilio_ops

    monkeypatch.setattr(twilio_ops, "auth_token", lambda: "")
    assert app_main._twilio_signature_ok(_Req(), {}) is False  # type: ignore[arg-type]
