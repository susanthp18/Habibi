"""The TTS voice catalog and previews.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401

TtsGender = Literal["Female", "Male"]


class TtsCatalogVoiceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shortName: str
    displayName: str
    localName: str = ""
    gender: str
    locale: str
    localeName: str = ""
    voiceType: str
    status: str
    priceTier: str
    isPremium: bool = False
    approxUsdPer1MChars: float | None = None
    styles: list[str] = Field(default_factory=list)
    personalities: list[str] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=list)
    wordsPerMinute: int | None = None
    sampleRateHertz: int | None = None
    modelSeries: list[str] = Field(default_factory=list)
    removedAt: str | None = None
    enabledForPicker: bool = True
    #: Which vendor this voice came from. Defaults to azure because every row
    #: that predates the provider registry was written by the Azure sync.
    providerId: str = "azure"
    raw: dict[str, Any] | None = None


class TtsCatalogListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TtsCatalogVoiceItem]
    total: int
    nextCursor: str | None = None
    lastSyncedAt: str | None = None
    defaultVoice: str
    premiumHiddenByDefault: bool = True


class TtsPriceTierResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: str
    label: str
    approxUsdPer1MChars: float | None = None
    isPremium: bool = False
    notes: str = ""


class TtsVoiceWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shortName: str
    code: str
    message: str
    fallbackVoice: str


class TtsSyncRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: str | None = None
    fetchedCount: int = 0
    upserted: int = 0
    softRemoved: int = 0
    unchanged: int = 0
    error: str | None = None
    region: str = ""
    defaultVoice: str | None = None
    startedAt: str | None = None
    finishedAt: str | None = None
    #: Rows written per non-Azure provider by the same refresh (provider_voice_sync).
    providers: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Azure Speech TTS preview (PS-4)
# ---------------------------------------------------------------------------


class TtsPreviewRequest(BaseModel):
    """Synthesize sample text for the Prompt Studio Voice tab."""

    model_config = ConfigDict(extra="forbid")

    text: str
    voiceId: str | None = None
    shortName: str | None = None
    azureVoiceName: str | None = None
    speed: float = 1.0
    pitch: int = 0
    warmth: int = 60
    pauseMs: int = 300
    style: str | None = None
    #: Model-declared controls, keyed by provider_models.params_schema.
    #: The Azure-shaped fields above stay for the existing callers; this
    #: is how a Fish voice sends temperature/latency/prosody, which have
    #: no equivalent among them. Unknown keys are dropped by the adapter,
    #: not forwarded — a knob with no transport must not reach a vendor.
    params: dict[str, Any] = Field(default_factory=dict)
    #: Take a new sample instead of returning the stored one.
    #:
    #: Previews are cached so that auditioning A, then B, then A again plays the
    #: same A both times — Cartesia, Deepgram and Fish are sampling models and
    #: were returning a different performance on every click, which made
    #: comparison meaningless. Hearing a second take is still a legitimate thing
    #: to want, so it stays available; it is just a deliberate act now rather
    #: than what happens whenever you press play twice.
    fresh: bool = False


class SttTranscribeResponse(BaseModel):
    """Azure Speech STT result — raw audio is not persisted."""

    model_config = ConfigDict(extra="forbid")

    text: str
    latencyMs: int
    language: str
    recognitionStatus: str | None = None


# ── TTS catalog counts ───────────────────────────────────────────────────────


class TtsProviderCountResponse(BaseModel):
    providerId: str
    count: int


class TtsLocaleCountResponse(BaseModel):
    locale: str
    localeName: str
    count: int
