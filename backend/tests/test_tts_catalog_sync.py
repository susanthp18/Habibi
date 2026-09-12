"""Unit tests for TTS catalog tier derivation (no DB required)."""

from __future__ import annotations

from tts_catalog_sync import derive_price_tier, is_premium_tier, normalize_azure_voice


def test_standard_aarti():
    assert derive_price_tier("en-IN-AartiNeural", "Neural") == "standard"
    assert not is_premium_tier("standard")


def test_hd_dragon():
    assert derive_price_tier("en-US-Ava:DragonHDLatestNeural", "NeuralHD") == "hd"
    assert is_premium_tier("hd")


def test_hd_flash():
    assert derive_price_tier("en-US-JennyNeuralHDFlash", "Neural") == "hd_flash"
    assert is_premium_tier("hd_flash")


def test_turbo():
    assert derive_price_tier("en-US-AlloyTurboMultilingualNeural", "Neural") == "turbo"


def test_normalize_aarti():
    row = normalize_azure_voice(
        {
            "ShortName": "en-IN-AartiNeural",
            "DisplayName": "Aarti",
            "LocalName": "Aarti",
            "Gender": "Female",
            "Locale": "en-IN",
            "LocaleName": "English (India)",
            "VoiceType": "Neural",
            "Status": "GA",
            "SampleRateHertz": "48000",
        }
    )
    assert row is not None
    assert row["price_tier"] == "standard"
    assert row["is_premium"] is False
    assert row["display_name"] == "Aarti"


def test_soft_removal_is_scoped_to_the_provider_it_fetched(db_tx, monkeypatch) -> None:
    """The sync only ever fetches Azure, but the plausibility check and the
    removal UPDATE were catalog-wide.

    Live data: 774 Azure names measured against 2288 live rows across four
    providers, so `plausible` was false on every admin Refresh — the removal was
    skipped, a warning was logged, and the UI still toasted success while
    retired Azure voices kept being dialled. Had the ratio ever passed, the
    unscoped UPDATE would have marked every Cartesia, Fish and Deepgram voice
    removed in a single click.
    """
    import tts_catalog_sync
    from sqlalchemy import text as _text

    import db

    def _row(short_name: str, provider: str) -> None:
        db_tx.execute(
            _text(
                """
                INSERT INTO tts_voice_catalog
                    (short_name, display_name, locale, provider_id, removed_at)
                VALUES (:s, :s, 'en-IN', :p, NULL)
                """
            ),
            {"s": short_name, "p": provider},
        )

    # Control the catalog so the 80% plausibility gate can actually open.
    db_tx.execute(_text("DELETE FROM tts_voice_catalog"))
    kept = [f"en-IN-Probe{i}Neural" for i in range(4)]
    stale = "en-IN-ProbeRetiredNeural"
    for name in [*kept, stale]:
        _row(name, "azure")
    _row("fish-probe-voice", "fish")

    monkeypatch.setattr(
        tts_catalog_sync,
        "fetch_azure_voices",
        lambda **_: [
            {
                "ShortName": name,
                "DisplayName": name,
                "LocalName": name,
                "Gender": "Female",
                "Locale": "en-IN",
                "LocaleName": "English (India)",
                "VoiceType": "Neural",
                "Status": "GA",
            }
            for name in kept
        ],
    )

    result = tts_catalog_sync.run_sync(db.engine, source="azure")
    assert result.get("error") is None

    def _removed(short_name: str):
        return db_tx.execute(
            _text("SELECT removed_at FROM tts_voice_catalog WHERE short_name = :s"),
            {"s": short_name},
        ).scalar()

    # 4 fetched vs 4 live Azure clears the 80% gate, so removal really ran.
    assert result.get("softRemoved") == 1
    assert _removed(stale) is not None
    # The whole point: another provider's voice is not this sync's business.
    assert _removed("fish-probe-voice") is None


def test_the_admin_refresh_reaches_every_provider(db_tx, monkeypatch, api_headers) -> None:
    """The Refresh button ran the Azure sync only, so Cartesia, Deepgram,
    ElevenLabs and Fish each had a registry entry, a chip, and zero voices
    behind it. One click now runs both halves, and the response says what each
    provider contributed."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text as _text

    import main as app_main
    import provider_voice_sync
    import tts_catalog_sync

    monkeypatch.setattr(tts_catalog_sync, "fetch_azure_voices", lambda **_: [])
    monkeypatch.setattr(
        provider_voice_sync,
        "ADAPTERS",
        {
            "fish": lambda: [
                {
                    "short_name": "fish:probe-voice",
                    "display_name": "Probe",
                    "local_name": "Probe",
                    "gender": "Neutral",
                    "locale": "und",
                    "locale_name": "Undetermined",
                    "styles": [],
                    "provider_id": "fish",
                    "raw": {},
                }
            ]
        },
    )

    res = TestClient(app_main.app, headers=api_headers).post("/tts-voices/catalog/sync")
    assert res.status_code == 200, res.text
    assert res.json()["providers"] == {"fish": 1}
    assert (
        db_tx.execute(
            _text("SELECT provider_id FROM tts_voice_catalog WHERE short_name = 'fish:probe-voice'")
        ).scalar()
        == "fish"
    )
