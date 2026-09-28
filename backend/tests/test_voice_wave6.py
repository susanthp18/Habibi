"""Wave 6 reconstructibility: transcript, sentiment, closer, AMD, analysis drops."""

from __future__ import annotations


def test_sentiment_correction_keys_the_transcript_turn(monkeypatch) -> None:
    """A late LLM correction must not rewrite a newer sparkline point."""
    from voice import persist

    captured: list[tuple[str, dict]] = []

    class _Result:
        rowcount = 1

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            captured.append((str(sql), dict(params or {})))
            return _Result()

    monkeypatch.setattr("db.engine.begin", lambda: _Conn())
    persist.update_turn_understanding(
        interaction_id="IX-W6",
        turn_index=3,
        intent="hardship",
        intent_score=0.9,
        sentiment=-0.4,
    )
    sentiment_sql, sentiment_params = captured[1]
    assert "interaction_transcript" in sentiment_sql
    assert "turn_index" in sentiment_params
    assert sentiment_params["turn_index"] == 3
    assert "ORDER BY at_sec DESC" not in sentiment_sql.replace("\n", " ")


def test_obligation_insert_stores_verbatim() -> None:
    import call_closer

    captured: list[tuple[str, dict]] = []

    class _Conn:
        def execute(self, sql, params=None):
            captured.append((str(sql), dict(params or {})))
            return None

    call_closer._record_obligations(
        _Conn(),
        attempt={
            "id": "CA-OB",
            "tenant_id": "T1",
            "customer_id": "C1",
            "interaction_id": "IX-OB",
            "ended_at": None,
        },
        tools=[
            {
                "tool_name": "request_callback",
                "result_ok": True,
                "args": {
                    "preferredAt": "2026-01-06T18:00:00Z",
                    "verbatim": "I'll call you Tuesday at six",
                },
            }
        ],
    )
    sql, params = captured[0]
    assert "verbatim" in sql.lower()
    assert params["verbatim"] == "I'll call you Tuesday at six"


def test_obligation_insert_uses_empty_verbatim_when_missing() -> None:
    import call_closer

    captured: list[dict] = []

    class _Conn:
        def execute(self, sql, params=None):
            captured.append(dict(params or {}))
            return None

    call_closer._record_obligations(
        _Conn(),
        attempt={
            "id": "CA-OB2",
            "tenant_id": "T1",
            "customer_id": "C1",
            "interaction_id": "IX-OB2",
            "ended_at": None,
        },
        tools=[
            {
                "tool_name": "request_documents",
                "result_ok": True,
                "args": {"document": "income_proof"},
            }
        ],
    )
    assert captured[0]["verbatim"] == ""


def test_closer_claim_sql_defers_active_interactions() -> None:
    import call_closer

    captured: list[str] = []

    class _Conn:
        def execute(self, sql, params=None):
            captured.append(str(sql))

            class _R:
                def mappings(self):
                    return self

                def first(self):
                    return None

            return _R()

    call_closer.claim_one(_Conn())
    sql = captured[0]
    assert "status = 'active'" in sql
    assert "NOT EXISTS" in sql
    assert "make_interval(secs => :grace)" in sql
