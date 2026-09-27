"""What an Azure multilingual speech setup may and may not ask for."""

import pytest

from api.services.configuration.azure_speech_capabilities import (
    normalize_languages,
    phrase_lists_supported,
    stt_errors,
    stt_warnings,
)
from api.services.configuration.registry import AzureSpeechSTTConfiguration


def test_primary_language_leads_and_duplicates_drop():
    assert normalize_languages("hi-IN", ["en-IN", "hi-IN", "ta-IN"]) == ["hi-IN", "en-IN", "ta-IN"]


def test_switching_needs_two_languages_and_at_most_ten():
    assert stt_errors(language="en-IN", languages=[], mode="continuous", region="southeastasia")
    many = [f"en-{c}" for c in ("US", "GB", "AU", "CA", "IN", "IE", "NZ", "ZA", "SG", "PH", "HK")]
    assert stt_errors(language="en-US", languages=many, mode="continuous", region="southeastasia")
    assert not stt_errors(language="en-IN", languages=["hi-IN", "ta-IN"], mode="continuous", region="southeastasia")


def test_mixing_within_a_sentence_refuses_tamil_and_gulf_arabic():
    errors = stt_errors(language="en-IN", languages=["ta-IN"], mode="multilingual", region="southeastasia")
    assert any("ta-IN" in e for e in errors)
    errors = stt_errors(language="en-US", languages=["ar-AE"], mode="multilingual", region="southeastasia")
    assert any("ar-AE" in e for e in errors)
    assert not stt_errors(language="en-IN", languages=["hi-IN"], mode="multilingual", region="southeastasia")
    assert stt_errors(language="en-IN", languages=["hi-IN"], mode="multilingual", region="eastus2")


def test_warnings_for_many_languages_and_missing_phrase_lists():
    warnings = stt_warnings(language="en-IN", languages=["hi-IN", "ta-IN", "ar-AE"], mode="continuous")
    assert any("reliable" in w for w in warnings)
    assert any("phrase lists" in w for w in warnings)
    assert not phrase_lists_supported(["en-IN", "ta-IN"])
    assert phrase_lists_supported(["en-IN", "hi-IN"])


def test_config_normalizes_and_rejects():
    config = AzureSpeechSTTConfiguration(
        api_key="k", region="southeastasia", language="en-IN",
        languages=["hi-IN", "ta-IN"], language_id_mode="continuous",
    )
    assert config.languages == ["en-IN", "hi-IN", "ta-IN"]
    with pytest.raises(ValueError):
        AzureSpeechSTTConfiguration(
            api_key="k", region="southeastasia", language="en-IN",
            languages=["ta-IN"], language_id_mode="multilingual",
        )


def test_arabic_amounts_are_spelled_out_and_nothing_else_is():
    from api.services.pipecat.arabic_numbers import spell_arabic_amounts

    assert "ثلاثمائة" in spell_arabic_amounts("الحد الأدنى 375 درهم.")
    assert "اثنا عشر" in spell_arabic_amounts("المبلغ المستحق 12,500 درهم.")
    assert "3750.50" in spell_arabic_amounts("المبلغ 3750.50 درهم.")
    assert "15-10-2026" in spell_arabic_amounts("قبل 15-10-2026.")
    assert spell_arabic_amounts("Your amount is 12,500 rupees.") == "Your amount is 12,500 rupees."
