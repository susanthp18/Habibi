"""What Azure Speech supports, per locale and region, for multilingual agents.

One source for configuration validation, the settings UI's hints and MCP
errors. From Azure's documentation (learn.microsoft.com, speech-service
language and region support pages, 2026-09) and our own measurements on the
southeastasia resource:

* Continuous language identification accepts up to 10 candidate locales, but
  every candidate makes switching less reliable: with four candidates we saw
  the first phrase after a switch transcribed in the previous language, and
  with three it was right every time. Hence the recommended ceiling.
* A language the caller speaks that is not a candidate is transcribed as the
  nearest candidate -- as gibberish -- so the list must be complete.
* Multilingual refinement (preview) handles mixing within a sentence but is
  slower, cannot be restricted to candidates, and drops or garbles locales
  outside its set (Tamil came back as Arabic). Continuous identification
  already transcribes Hindi-English mixing correctly in Devanagari.
"""

from __future__ import annotations

import re

# A BCP-47 locale such as "hi-IN" or "zh-Hans-CN"; also what makes a
# language safe to write into SSML.
_LOCALE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}$")

MAX_CANDIDATE_LANGUAGES = 10
RECOMMENDED_MAX_LANGUAGES = 3

#: Locales multilingual post-stream refinement supports (preview).
REFINEMENT_LOCALES = frozenset({
    "ar-SA", "cs-CZ", "da-DK", "de-DE", "el-GR", "en-AU", "en-CA", "en-GB", "en-IN",
    "en-US", "es-ES", "es-MX", "fi-FI", "fr-CA", "fr-FR", "he-IL", "hi-IN", "hu-HU",
    "id-ID", "it-IT", "ja-JP", "ko-KR", "nb-NO", "nl-NL", "pl-PL", "pt-BR", "pt-PT",
    "ru-RU", "sv-SE", "th-TH", "tr-TR", "zh-CN",
})

#: Regions offering multilingual refinement.
REFINEMENT_REGIONS = frozenset({
    "eastus", "westus", "northeurope", "centralindia", "southeastasia", "japaneast",
})

#: Locales without phrase-list support. A recognizer listening for several
#: languages only gets a phrase list when none of them is here.
NO_PHRASE_LIST_LOCALES = frozenset({"ta-IN", "ar-AE"})

#: Locales whose display transcripts garble spoken amounts, so the model is
#: given Azure's lexical form (the words as spoken). Measured: Tamil renders
#: "twelve thousand five hundred rupees" as a Tamil word followed by "₹500".
LEXICAL_LOCALES = frozenset({"ta-IN"})

LANGUAGE_ID_MODES = ("single", "continuous", "multilingual")


def normalize_languages(primary: str | None, languages: list[str] | None) -> list[str]:
    """The candidate list with the primary language first, duplicates dropped."""
    ordered = [lang.strip() for lang in ([primary] if primary else []) + list(languages or [])
               if lang and lang.strip()]
    return list(dict.fromkeys(ordered))


def stt_errors(*, language: str | None, languages: list[str] | None, mode: str,
               region: str | None) -> list[str]:
    """Reasons an Azure speech-to-text setup cannot work, empty when it can."""
    if mode not in LANGUAGE_ID_MODES:
        return [f"Unknown language detection mode {mode!r}."]
    candidates = normalize_languages(language, languages)
    errors: list[str] = []
    malformed = [lang for lang in candidates if not _LOCALE.fullmatch(lang)]
    if malformed:
        errors.append("Not a language code: " + ", ".join(malformed) + " (use e.g. hi-IN).")
    if mode == "continuous":
        if len(candidates) < 2:
            errors.append("Switching languages needs at least two languages.")
        if len(candidates) > MAX_CANDIDATE_LANGUAGES:
            errors.append(f"Azure listens for at most {MAX_CANDIDATE_LANGUAGES} languages at once.")
    if mode == "multilingual":
        unsupported = [lang for lang in candidates if lang not in REFINEMENT_LOCALES]
        if unsupported:
            errors.append("Mixing within a sentence is not available for "
                          + ", ".join(unsupported) + "; use switching between sentences.")
        if region and region not in REFINEMENT_REGIONS:
            errors.append(f"Mixing within a sentence is not offered in {region}.")
    return errors


def stt_warnings(*, language: str | None, languages: list[str] | None, mode: str) -> list[str]:
    candidates = normalize_languages(language, languages)
    warnings: list[str] = []
    if mode == "continuous" and len(candidates) > RECOMMENDED_MAX_LANGUAGES:
        warnings.append(f"More than {RECOMMENDED_MAX_LANGUAGES} languages makes switching less "
                        "reliable; give each market its own agent.")
    if mode != "single" and any(lang in NO_PHRASE_LIST_LOCALES for lang in candidates):
        warnings.append("Keyword boosting is off: Azure has no phrase lists for "
                        + ", ".join(lang for lang in candidates if lang in NO_PHRASE_LIST_LOCALES) + ".")
    if mode == "multilingual":
        warnings.append("Mixing within a sentence is an Azure preview and adds latency.")
    return warnings


def phrase_lists_supported(candidates: list[str]) -> bool:
    return not any(lang in NO_PHRASE_LIST_LOCALES for lang in candidates)
