"""Vision ingest — analysis profile, identity-gated, never on the voice mouth.

A receipt photo becomes a ``document_requests`` row. OCR is best-effort on the
analysis Azure profile; creating the row does not wait on a human.
"""

from __future__ import annotations

import logging

from agent_core.platform_flags import vision_ingest_enabled
from agent_core.tools.catalog import DOCUMENT_TYPES
from agent_core.tools.domain import ToolResult

logger = logging.getLogger(__name__)

_UNKNOWN = "UNKNOWN-CALLER"
_IMAGE_TYPES = frozenset(
    {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif"}
)


def ingest_customer_document(
    *,
    customer_id: str,
    filename: str,
    mime_type: str,
    identity_verified: bool,
    interaction_id: str | None = None,
    account_id: str | None = None,
    requested_via: str = "inbox",
    size_bytes: int | None = None,
) -> ToolResult:
    if not vision_ingest_enabled():
        return ToolResult(ok=False, error="vision_ingest_disabled")
    if not identity_verified or not customer_id or customer_id == _UNKNOWN:
        return ToolResult(ok=False, error="identity_not_verified")
    mime = (mime_type or "").split(";")[0].strip().lower() or "application/octet-stream"
    if mime not in _IMAGE_TYPES and not mime.startswith("image/"):
        return ToolResult(ok=False, error="not_an_image")

    doc_type = _classify(filename, mime) or "payment_receipt"
    if doc_type not in DOCUMENT_TYPES:
        doc_type = "payment_receipt"

    import db

    payload = {
        "customerId": customer_id,
        "accountId": account_id,
        "interactionId": interaction_id,
        "docType": doc_type,
        "requestedVia": requested_via if requested_via else "vision",
        "source": "vision",
        "filename": filename or "receipt.jpg",
        "mimeType": mime,
        "deliveryChannel": "whatsapp",
    }
    if size_bytes is not None:
        payload["sizeKb"] = max(1, int(round(size_bytes / 1024)))
    try:
        row = db.create_document_request(payload)
    except Exception:
        logger.exception("vision ingest write failed")
        return ToolResult(ok=False, error="crm_write_failed")
    doc_id = row.get("id") if isinstance(row, dict) else None
    return ToolResult(
        ok=True,
        data={
            "documentRequestId": doc_id,
            "documentType": doc_type,
            "source": "vision",
            "filename": filename,
        },
        spoken_summary="receipt captured as a document request",
        entity="document_request",
        entity_id=doc_id,
        analytics=["vision_ingest"],
    )


def _classify(filename: str, mime: str) -> str | None:
    """Best-effort type. Fail closed to payment_receipt, never block the row."""
    name = (filename or "").lower()
    if "kyc" in name or "aadhaar" in name or "pan" in name:
        return "kyc_letter"
    if "statement" in name:
        return "account_statement"
    if "foreclos" in name:
        return "foreclosure_letter"
    try:
        import azure_openai

        result = azure_openai.chat_with_tools(
            [
                {
                    "role": "system",
                    "content": (
                        "Classify an uploaded collections document. Reply with exactly "
                        "one of: payment_receipt, account_statement, kyc_letter, "
                        "no_dues_certificate, interest_certificate, foreclosure_letter, "
                        "loan_schedule."
                    ),
                },
                {"role": "user", "content": f"filename={filename} mime={mime}"},
            ],
            tools=None,
            temperature=0.0,
            max_completion_tokens=20,
            profile=azure_openai.PROFILE_ANALYSIS,
        )
        text_out = ""
        if isinstance(result, dict):
            text_out = str(result.get("content") or result.get("text") or "")
        elif isinstance(result, str):
            text_out = result
        token = text_out.strip().split()[0].lower() if text_out.strip() else ""
        if token in DOCUMENT_TYPES:
            return token
    except Exception:
        logger.info("vision classify fell back to filename heuristics")
    if "receipt" in name or mime.startswith("image/"):
        return "payment_receipt"
    return None
