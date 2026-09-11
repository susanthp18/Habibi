"""Knowledge base.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import asyncio
import db
import json
import kb_rate_limit
import kb_retrieve
import storage

from fastapi import APIRouter
from fastapi import (
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from schemas import (
    KbChunkResponse,
    KbDeleteDocumentResponse,
    KbDocumentPatchRequest,
    KbDocumentResponse,
    KbFaqCreateRequest,
    KbFaqPatchRequest,
    KbFaqResponse,
    KbGapLinkRequest,
    KbGapResponse,
    KbIndexJobResponse,
    KbIngestSourceDbResponse,
    KbPurgeRequest,
    KbPurgeResponse,
    KbReindexAllResponse,
    KbReindexResponse,
    KbRetrieveRequest,
    KbRetrieveResponse,
    KbSnapshotCreateRequest,
    KbSnapshotResponse,
    KbStatsResponse,
    KbUploadResponse,
)
from schemas import AgentStudioSkillResponse

from api_support import _read_upload_capped, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.post(
    "/kb/gaps/{gap_id}/promote-skill",
    response_model=AgentStudioSkillResponse,
    response_model_exclude_unset=True,
)
def promote_kb_gap_to_skill(gap_id: str):
    from agent_core.skills.gardener import assert_unsigned, draft_from_gap
    from agent_core.skills.persist import create_draft_skill

    gaps = {g["id"]: g for g in db.list_kb_gaps()}
    gap = gaps.get(gap_id)
    if gap is None:
        raise HTTPException(status_code=404, detail="kb_gap_not_found")
    draft = draft_from_gap(
        question=str(gap.get("question") or gap.get("text") or ""),
        intent=gap.get("topIntent") or gap.get("top_intent") or gap.get("intent"),
        gap_id=gap_id,
    )
    assert_unsigned(draft)
    return create_draft_skill(
        {
            "slug": draft["slug"],
            "description": draft["frontmatter"].get("description"),
            "allowed_tools": draft["allowed_tools"],
            "body": draft["body"],
            "frontmatter": draft["frontmatter"],
            "origin": "gardener",
        }
    )

@router.post("/kb/retrieve", response_model=KbRetrieveResponse)
def kb_retrieve_endpoint(payload: KbRetrieveRequest):
    """Test / runtime retrieval against embedded kb_chunks + faq_pairs."""
    try:
        return kb_retrieve.retrieve(
            query=payload.query,
            top_k=payload.topK,
            include_draft_answer=payload.includeDraftAnswer,
            source=payload.source,
        )
    except kb_rate_limit.RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.exception("kb_retrieve_failed")
        raise HTTPException(status_code=502, detail="kb_retrieve_failed") from None

@router.get("/kb/stats", response_model=KbStatsResponse)
def kb_stats():
    return db.get_kb_stats()

@router.get("/kb/documents", response_model=list[KbDocumentResponse])
def kb_list_documents(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_kb_documents(limit=limit, offset=offset)

@router.get("/kb/documents/{document_id}", response_model=KbDocumentResponse)
def kb_get_document(document_id: str):
    doc = db.get_kb_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="kb_document_not_found")
    return doc

@router.get("/kb/documents/{document_id}/chunks", response_model=list[KbChunkResponse])
def kb_list_chunks(
    document_id: str,
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    if not db.get_kb_document(document_id):
        raise HTTPException(status_code=404, detail="kb_document_not_found")
    return db.list_kb_chunks(document_id, limit=limit, offset=offset)

@router.patch("/kb/documents/{document_id}", response_model=KbUploadResponse)
def kb_patch_document(document_id: str, payload: KbDocumentPatchRequest):
    try:
        result = db.patch_kb_document(document_id, payload.model_dump(exclude_none=True))
        return {"document": result["document"], "jobId": result.get("jobId")}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        # A DB/storage outage is not a client error, and str(exc) on a driver
        # exception leaks connection details into the response body.
        logger.exception("kb_patch_document_failed document=%s", document_id)
        raise HTTPException(status_code=502, detail="kb_patch_failed") from None

@router.post("/kb/documents/{document_id}/reindex", response_model=KbReindexResponse)
def kb_reindex_document(document_id: str):
    try:
        return db.reindex_kb_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.delete("/kb/documents/{document_id}", response_model=KbDeleteDocumentResponse)
def kb_delete_document(document_id: str):
    try:
        return db.delete_kb_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/kb/documents/purge", response_model=KbPurgeResponse)
def kb_purge_documents(payload: KbPurgeRequest):
    try:
        return db.purge_kb_documents(scope=payload.scope, confirm=payload.confirm)
    except ValueError as exc:
        msg = str(exc)
        if msg == "confirm_required":
            raise HTTPException(status_code=400, detail="confirm must be true") from exc
        raise HTTPException(status_code=400, detail=msg) from exc

@router.post("/kb/ingest/source-db", response_model=KbIngestSourceDbResponse)
def kb_ingest_source_db(product: str | None = Query(default=None)):
    """Re-ingest policy/benefits/FAQs from disk source_db/ (same as CLI)."""
    try:
        return db.ingest_kb_from_source_db(product=product)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        # Static detail: the underlying exception carries DSNs, file paths and
        # Azure error bodies that must not reach an API client.
        logger.exception("kb_ingest_source_db failed product=%s", product)
        raise HTTPException(status_code=502, detail="kb_ingest_failed") from exc

@router.post("/kb/reindex-all", response_model=KbReindexAllResponse)
def kb_reindex_all():
    result = db.reindex_all_kb_documents()
    # Snapshot hook — freeze post-queue corpus pointer for sandbox readiness.
    try:
        snap = db.create_kb_snapshot(label=f"After reindex-all ({result.get('count', 0)} jobs)")
        result["snapshot"] = snap
    except Exception:
        # Reindex itself succeeded; a missing snapshot only costs sandbox
        # reproducibility — but it must not disappear silently.
        logger.warning(
            "kb_snapshot_after_reindex_failed jobs=%s", result.get("count", 0), exc_info=True
        )
        result["snapshot"] = None
    return result

@router.get("/kb/index-jobs/{job_id}", response_model=KbIndexJobResponse)
def kb_get_index_job(job_id: str):
    job = db.get_kb_index_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="kb_index_job_not_found")
    return job

@router.post("/kb/documents", response_model=KbUploadResponse)
async def kb_upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    type: str = Form("policy"),
    chunkSize: int = Form(512),
    overlap: int = Form(64),
    indexNow: bool = Form(True),
    tags: str = Form("[]"),
):
    try:
        tag_list = json.loads(tags) if tags else []
        if not isinstance(tag_list, list):
            raise ValueError("tags must be a JSON array")
        data = await _read_upload_capped(file)
        # Sync MinIO + DB off the event loop.
        result = await asyncio.to_thread(
            db.create_kb_document_from_upload,
            filename=file.filename or "upload.txt",
            data=data,
            content_type=file.content_type or "application/octet-stream",
            title=title,
            doc_type=type,
            chunk_size=chunkSize,
            overlap=overlap,
            index_now=indexNow,
            tags=[str(t) for t in tag_list],
        )
        return result
    except storage.StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.exception("kb_upload_failed")
        raise HTTPException(status_code=502, detail="kb_upload_failed") from None

@router.post("/kb/documents/{document_id}/versions", response_model=KbUploadResponse)
async def kb_new_version(document_id: str, file: UploadFile = File(...)):
    try:
        data = await _read_upload_capped(file)
        return await asyncio.to_thread(
            db.create_kb_document_version,
            document_id,
            filename=file.filename or "upload.txt",
            data=data,
            content_type=file.content_type or "application/octet-stream",
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except storage.StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.exception("kb_version_failed")
        raise HTTPException(status_code=502, detail="kb_version_failed") from None

@router.get("/kb/faqs", response_model=list[KbFaqResponse])
def kb_list_faqs(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_kb_faqs(limit=limit, offset=offset)

@router.post("/kb/faqs", response_model=KbFaqResponse)
def kb_create_faq(payload: KbFaqCreateRequest):
    try:
        return db.create_kb_faq(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.patch("/kb/faqs/{faq_id}", response_model=KbFaqResponse)
def kb_patch_faq(faq_id: str, payload: KbFaqPatchRequest):
    try:
        return db.patch_kb_faq(faq_id, payload.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

# 204 with no body by design. Listed in tests/test_route_structure.py::_UNTYPED_BY_DESIGN.
@router.delete("/kb/faqs/{faq_id}", status_code=204, response_class=Response)
def kb_delete_faq(faq_id: str):
    try:
        db.delete_kb_faq(faq_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)

@router.get("/kb/gaps", response_model=list[KbGapResponse])
def kb_list_gaps():
    return db.list_kb_gaps()

@router.post("/kb/gaps/{gap_id}/link", response_model=KbGapResponse)
def kb_link_gap(gap_id: str, payload: KbGapLinkRequest):
    """Link a gap to exactly one of FAQ / KB doc / prompt version."""
    try:
        return db.link_kb_gap(gap_id, payload.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        if msg == "gap_link_exactly_one_target":
            raise HTTPException(status_code=409, detail=msg) from exc
        raise HTTPException(status_code=400, detail=msg) from exc

@router.get("/kb/snapshots", response_model=list[KbSnapshotResponse])
def kb_list_snapshots():
    return db.list_kb_snapshots()

@router.post("/kb/snapshots", response_model=KbSnapshotResponse)
def kb_create_snapshot(payload: KbSnapshotCreateRequest | None = None):
    label = payload.label if payload else None
    return db.create_kb_snapshot(label=label)

