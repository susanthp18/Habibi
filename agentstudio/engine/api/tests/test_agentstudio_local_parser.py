"""AgentStudio: knowledge-base documents are parsed on the box, in the MPS shape."""

import json

import pytest

from api.services import knowledge_base_local_parser as parser


def _write(tmp_path, name, content):
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return str(path)


def _assert_chunk_shape(result):
    assert result["mode"] == "chunked"
    assert result["docling_metadata"]["parser"] == parser.PARSER_NAME
    for i, chunk in enumerate(result["chunks"]):
        assert chunk["chunk_index"] == i
        assert chunk["chunk_text"].strip()
        assert chunk["contextualized_text"].endswith(chunk["chunk_text"])
        assert isinstance(chunk["chunk_metadata"], dict)
        assert chunk["token_count"] >= 1


def test_markdown_keeps_headings_as_context(tmp_path):
    path = _write(tmp_path, "fees.md", "# Fees\n\nLate fee is 500.\n\n## Grace\n\nThree days.")
    result = parser.process_document(path, "fees.md")
    _assert_chunk_shape(result)
    assert [c["chunk_metadata"]["headings"] for c in result["chunks"]] == [["Fees"], ["Grace"]]
    assert result["chunks"][1]["contextualized_text"] == "Grace\nThree days."


def test_long_text_is_packed_under_the_token_limit(tmp_path):
    body = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(20))
    result = parser.process_document(_write(tmp_path, "long.txt", body), "long.txt", max_tokens=128)
    _assert_chunk_shape(result)
    assert len(result["chunks"]) > 5
    assert all(c["token_count"] <= 128 for c in result["chunks"])


def test_docx_headings_and_tables(tmp_path):
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_heading("Car Protect 360", level=1)
    doc.add_paragraph("Covers accidental damage.")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text = "Premium", "12,000"
    path = str(tmp_path / "policy.docx")
    doc.save(path)
    result = parser.process_document(path, "policy.docx")
    _assert_chunk_shape(result)
    text = " ".join(c["contextualized_text"] for c in result["chunks"])
    assert "Car Protect 360" in text and "Premium | 12,000" in text


def test_pdf_text_is_extracted_per_page(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    path = str(tmp_path / "blank.pdf")
    with open(path, "wb") as fh:
        writer.write(fh)
    with pytest.raises(ValueError, match="OCR"):
        parser.process_document(path, "blank.pdf")


def test_html_and_json(tmp_path):
    html = "<html><script>x()</script><h2>Refunds</h2><p>Within 7 days.</p></html>"
    result = parser.process_document(_write(tmp_path, "r.html", html), "r.html")
    assert result["chunks"][0]["contextualized_text"] == "Refunds\nWithin 7 days."
    data = parser.process_document(_write(tmp_path, "d.json", json.dumps({"a": 1})), "d.json")
    assert '"a": 1' in data["chunks"][0]["chunk_text"]


def test_full_document_mode_and_unsupported_types(tmp_path):
    path = _write(tmp_path, "faq.md", "# Q\n\nA.")
    result = parser.process_document(path, "faq.md", retrieval_mode="full_document")
    assert result == {
        "mode": "full_document",
        "docling_metadata": result["docling_metadata"],
        "full_text": "## Q\n\nA.",
    }
    with pytest.raises(ValueError, match="Unsupported"):
        parser.process_document(_write(tmp_path, "x.doc", b"\xd0\xcf"), "x.doc")
