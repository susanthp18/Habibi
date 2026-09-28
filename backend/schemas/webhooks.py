"""Webhook endpoints and deliveries.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, UrlConstraints

# Webhook targets carry signed CRM events off-platform — HTTPS is enforced at
# the schema boundary so a plaintext URL is a 422 with a field-level error
# rather than a generic 400 from db_webhooks._validate_webhook_url.
HttpsUrl = Annotated[AnyHttpUrl, UrlConstraints(allowed_schemes=["https"])]


class WebhookRetryPolicyRequest(BaseModel):
    """How a failed delivery is retried; the same three fields the response reports."""

    attempts: int = Field(default=3, ge=1, le=8)
    backoff: Literal["exponential", "linear"] = "exponential"
    maxAgeHours: int = Field(default=24, ge=1, le=72)


class WebhookHeaderRequest(BaseModel):
    """One header sent with every delivery."""

    key: str = Field(min_length=1)
    value: str


class WebhookEndpointUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    url: HttpsUrl
    target: str = "Custom"
    events: list[str] = []
    algo: Literal["HMAC-SHA256", "hmac-sha256"] = "HMAC-SHA256"
    retry: WebhookRetryPolicyRequest = Field(default_factory=WebhookRetryPolicyRequest)
    headers: list[WebhookHeaderRequest] = []
    status: Literal["active", "paused", "broken"] | None = None


class WebhookEndpointPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expectedVersion: int | None = Field(default=None, ge=1)

    name: str | None = None
    url: HttpsUrl | None = None
    target: str | None = None
    events: list[str] | None = None
    algo: Literal["HMAC-SHA256", "hmac-sha256"] | None = None
    retry: WebhookRetryPolicyRequest | None = None
    headers: list[WebhookHeaderRequest] | None = None
    status: Literal["active", "paused", "broken"] | None = None


# ── Webhooks (db_webhooks) ───────────────────────────────────────────────────


class EventTypeSampleResponse(BaseModel):
    schemaVersion: int
    event: str
    tenant: str
    at: str
    data: dict[str, Any]


class EventTypeResponse(BaseModel):
    key: str
    category: str
    description: str
    supported: bool
    sample: EventTypeSampleResponse


class WebhookRetryPolicyResponse(BaseModel):
    attempts: int
    backoff: str
    maxAgeHours: int


class WebhookHeaderResponse(BaseModel):
    key: str
    value: str


class WebhookEndpointResponse(BaseModel):
    id: str
    name: str
    url: str
    target: str
    status: str
    subscriptionsConfirmed: bool
    destinationTested: bool
    configurationVersion: int
    events: list[str]
    algo: str
    secret: str
    secretRef: str
    retry: WebhookRetryPolicyResponse
    headers: list[WebhookHeaderResponse]
    createdAt: int
    #: Plaintext, present on create and rotate-secret only.
    secretOnce: str | None = None


class WebhookConfirmRequest(BaseModel):
    configurationVersion: int = Field(ge=1)


class WebhookDeliveryResponse(BaseModel):
    id: str
    endpointId: str
    event: str
    status: str
    httpStatus: int
    latencyMs: int
    attempt: int
    maxAttempts: int
    at: int
    payload: dict[str, Any]
    responseBody: str | None = None
    mode: str


class WhatsAppWebhookResultResponse(BaseModel):
    """One inbound message or status callback; the keys depend on the outcome."""

    status: str
    reason: str | None = None
    waMessageId: str | None = None
    messageId: str | None = None
    conversationId: str | None = None
    customerId: str | None = None
    providerRef: str | None = None
    delivery: str | None = None


class WhatsAppWebhookResponse(BaseModel):
    ok: bool
    results: list[WhatsAppWebhookResultResponse]
