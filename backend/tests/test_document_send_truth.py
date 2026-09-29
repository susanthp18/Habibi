"""A document request is `sent` only when a person records sending it.

PayInt has no document renderer and no document sender. The desk's "Generate &
send" PATCHed `status: sent` with a random file size, and creating a request
wrote a `document_files` row pointing at a MinIO object nobody uploaded. Now a
PATCH cannot claim a render or a send, and the one recordable delivery attempt
is a person's manual send, taken through the contact policy.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

import db_documents

MANUAL_SEND = {"status": "sent", "provider": "manual"}


def _new_request(conn) -> str:
    customer_id = conn.execute(
        text(
            """
            SELECT a.customer_id FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE c.id <> 'UNKNOWN-CALLER'
            ORDER BY a.id LIMIT 1
            """
        )
    ).scalar()
    if customer_id is None:
        pytest.skip("seed has no customer with an account")
    # filename/mimeType are what the desk used to send to get a file row.
    return db_documents.create_document_request(
        {
            "customerId": customer_id,
            "docType": "account_statement",
            "deliveryChannel": "whatsapp",
            "filename": "account_statement.pdf",
            "mimeType": "application/pdf",
        }
    )["id"]


def _request_row(conn, doc_id: str):
    return conn.execute(
        text(
            "SELECT status, sent_at, generated_at, size_kb, attempts "
            "FROM document_requests WHERE id = :id"
        ),
        {"id": doc_id},
    ).mappings().one()


def _attempts(conn, doc_id: str) -> int:
    return conn.execute(
        text("SELECT count(*) FROM document_delivery_attempts WHERE request_id = :id"),
        {"id": doc_id},
    ).scalar()


def test_a_new_request_claims_no_file(db_tx) -> None:
    doc_id = _new_request(db_tx)
    files = db_tx.execute(
        text("SELECT count(*) FROM document_files WHERE request_id = :id"), {"id": doc_id}
    ).scalar()
    assert files == 0
    row = _request_row(db_tx, doc_id)
    assert row["generated_at"] is None and row["size_kb"] is None


@pytest.mark.parametrize("status", ["sent", "generating"])
def test_a_patch_cannot_claim_a_send_or_a_render(db_tx, status: str) -> None:
    doc_id = _new_request(db_tx)
    with pytest.raises(ValueError, match=f"illegal_transition:document_request:requested->{status}"):
        db_documents.patch_document_request(doc_id, {"status": status, "sizeKb": 321})
    assert _request_row(db_tx, doc_id)["status"] == "requested"


def test_a_patch_writes_no_size_or_timestamps(db_tx) -> None:
    doc_id = _new_request(db_tx)
    db_documents.patch_document_request(
        doc_id,
        {
            "status": "failed",
            "failedReason": "customer asked for a different period",
            "sizeKb": 321,
            "sentAt": "2026-09-01T10:00:00Z",
            "generatedAt": "2026-09-01T09:59:00Z",
            "attempts": 7,
        },
    )
    row = _request_row(db_tx, doc_id)
    assert row["status"] == "failed"
    assert (row["size_kb"], row["sent_at"], row["generated_at"], row["attempts"]) == (None, None, None, 0)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "queued", "provider": "manual"},
        {"status": "delivered", "provider": "manual"},
        {"status": "sent", "provider": "whatsapp_cloud"},
        {"status": "sent"},
        {},
    ],
)
def test_only_a_manual_send_is_recordable(db_tx, payload: dict) -> None:
    doc_id = _new_request(db_tx)
    with pytest.raises(ValueError, match="manual_send_confirmation_required"):
        db_documents.add_document_delivery_attempt(doc_id, payload)
    assert _attempts(db_tx, doc_id) == 0


def test_a_manual_send_is_admitted_then_recorded_once(db_tx, monkeypatch) -> None:
    admitted: list[dict] = []
    monkeypatch.setattr("contact_policy.require_admit", lambda _conn, **kw: admitted.append(kw))
    doc_id = _new_request(db_tx)

    out = db_documents.add_document_delivery_attempt(doc_id, MANUAL_SEND)

    assert out["status"] == "sent" and out["attemptNumber"] == 1
    assert [(a["source"], a["actor_kind"], a["related_id"]) for a in admitted] == [
        ("doc_delivery", "human", out["id"])
    ]
    attempt = db_tx.execute(
        text("SELECT provider, status, sent_at FROM document_delivery_attempts WHERE id = :id"),
        {"id": out["id"]},
    ).mappings().one()
    assert (attempt["provider"], attempt["status"]) == ("manual", "sent")
    assert attempt["sent_at"] is not None
    row = _request_row(db_tx, doc_id)
    assert row["status"] == "sent" and row["sent_at"] is not None and row["attempts"] == 1
    # Sent by hand, so PayInt rendered nothing and knows no size.
    assert row["generated_at"] is None and row["size_kb"] is None

    with pytest.raises(ValueError, match="document_already_sent"):
        db_documents.add_document_delivery_attempt(doc_id, MANUAL_SEND)
    assert _attempts(db_tx, doc_id) == 1


def test_a_contact_policy_refusal_records_nothing(db_tx, monkeypatch) -> None:
    def _refuse(_conn, **_kw):
        raise ValueError("channel_opted_out")

    monkeypatch.setattr("contact_policy.require_admit", _refuse)
    doc_id = _new_request(db_tx)
    with pytest.raises(ValueError, match="channel_opted_out"):
        db_documents.add_document_delivery_attempt(doc_id, MANUAL_SEND)
    assert _request_row(db_tx, doc_id)["status"] == "requested"
    assert _attempts(db_tx, doc_id) == 0


def test_a_bot_cannot_confirm_a_manual_send(db_tx, monkeypatch) -> None:
    doc_id = _new_request(db_tx)
    monkeypatch.setattr("contact_policy.require_admit", lambda _conn, **_kw: None)
    monkeypatch.setattr(db_documents, "_actor", lambda: ("bot", None, "bot-1"))
    with pytest.raises(PermissionError, match="manual_send_needs_a_person"):
        db_documents.add_document_delivery_attempt(doc_id, MANUAL_SEND)
    assert _attempts(db_tx, doc_id) == 0
