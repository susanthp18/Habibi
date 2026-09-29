"""A retrieval names every document it searched, not just the chunks it kept."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.workflow.tools import knowledge_base


@pytest.mark.asyncio
async def test_retrieval_lists_the_documents_searched(monkeypatch):
    db = SimpleNamespace(
        get_full_text_documents=AsyncMock(return_value=[]),
        get_document_filenames=AsyncMock(return_value=["Car_FAQs.txt", "Travel_FAQs.txt"]),
    )
    search = AsyncMock(return_value=[
        {"chunk_text": "Buy travel cover online.", "filename": "Travel_FAQs.txt", "similarity": 0.53},
    ])
    monkeypatch.setattr(knowledge_base, "db_client", db)
    monkeypatch.setattr(
        knowledge_base, "build_embedding_service",
        AsyncMock(return_value=SimpleNamespace(search_similar_chunks=search)),
    )

    result = await knowledge_base._perform_retrieval(
        "what insurance do you offer", 1, ["u1", "u2"], 3, embeddings_api_key="k",
    )

    assert [c["filename"] for c in result["chunks"]] == ["Travel_FAQs.txt"]
    assert result["documents_searched"] == ["Car_FAQs.txt", "Travel_FAQs.txt"]
    db.get_document_filenames.assert_awaited_once_with(organization_id=1, document_uuids=["u1", "u2"])


@pytest.mark.asyncio
async def test_a_named_product_narrows_the_search_to_its_files(monkeypatch):
    """Run 68: "Travel exclusions" over all thirty files ranked Choice's and Car's
    exclusions above Travel's own clauses."""
    named = AsyncMock(side_effect=[["u2"], []])
    db = SimpleNamespace(
        get_full_text_documents=AsyncMock(return_value=[]),
        get_document_filenames=AsyncMock(return_value=["Travel_policy.md"]),
        get_document_uuids_named=named,
    )
    search = AsyncMock(return_value=[])
    monkeypatch.setattr(knowledge_base, "db_client", db)
    monkeypatch.setattr(knowledge_base, "ensure_tracing", lambda: False)
    monkeypatch.setattr(
        knowledge_base, "build_embedding_service",
        AsyncMock(return_value=SimpleNamespace(search_similar_chunks=search)),
    )

    await knowledge_base.retrieve_from_knowledge_base(
        "exclusions", 1, ["u1", "u2"], embeddings_api_key="k", documents="Travel_",
    )
    assert named.await_args.kwargs["prefix"] == "Travel"
    assert search.await_args.kwargs["document_uuids"] == ["u2"]

    await knowledge_base.retrieve_from_knowledge_base(
        "exclusions", 1, ["u1", "u2"], embeddings_api_key="k", documents="Nothing",
    )
    assert search.await_args.kwargs["document_uuids"] == ["u1", "u2"]  # unknown: everything, not nothing
