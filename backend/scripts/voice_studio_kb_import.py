"""Load the product corpus into PayInt Voice Studio's knowledge base.

The same source files our KB was built from (SOURCE_DB_ROOT: policy/*.md,
benefits/*.txt, FAQ/*.txt) are uploaded to the engine, parsed and embedded
there (self-hosted parser, the tenant's own embedding model), so agents can
answer product questions mid-call. Re-running skips files already present
(matched by filename) unless --replace is given.

    docker exec collections_api python -m scripts.voice_studio_kb_import --actor priya-nair

Afterwards re-run scripts/voice_studio_seed.py to attach the documents to the
collections agent.
"""

from __future__ import annotations

import argparse
import mimetypes
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from env_loader import load_env
from env_utils import env_str
from scripts.voice_studio_seed import Engine

FOLDERS = ("policy", "benefits", "FAQ")


def _upload(url: str, data: bytes, content_type: str) -> None:
    """PUT to a presigned storage URL. The URL names the storage's public host;
    from inside the compose network the request goes to MINIO_ENDPOINT with the
    signed Host header kept, so the signature still verifies."""
    parts = urlsplit(url)
    internal = env_str("AGENTSTUDIO_MINIO_INTERNAL", "http://minio:9000").rstrip("/")
    target = f"{internal}{parts.path}?{parts.query}"
    r = httpx.put(target, content=data, headers={"Host": parts.netloc, "Content-Type": content_type}, timeout=120)
    if r.status_code >= 300:
        sys.exit(f"storage upload failed ({r.status_code}): {r.text[:300]}")


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--actor", required=True)
    parser.add_argument("--root", default=env_str("SOURCE_DB_ROOT", "/source_db"))
    parser.add_argument("--replace", action="store_true", help="re-upload files that already exist")
    args = parser.parse_args()

    engine = Engine(args.actor)
    existing = {d["filename"]: d for d in engine("GET", "/knowledge-base/documents?limit=100")["documents"]}
    root = Path(args.root)
    queued = []
    for folder in FOLDERS:
        for path in sorted((root / folder).glob("*")):
            if not path.is_file() or path.suffix.lower() not in (".md", ".txt"):
                continue
            if path.name in existing and not args.replace:
                continue
            if path.name in existing:
                engine("DELETE", f"/knowledge-base/documents/{existing[path.name]['document_uuid']}")
            mime = mimetypes.guess_type(path.name)[0] or "text/plain"
            slot = engine("POST", "/knowledge-base/upload-url", {"filename": path.name, "mime_type": mime})
            _upload(slot["upload_url"], path.read_bytes(), mime)
            engine("POST", "/knowledge-base/process-document",
                   {"document_uuid": slot["document_uuid"], "s3_key": slot["s3_key"], "retrieval_mode": "chunked"})
            queued.append(path.name)
    print(f"queued {len(queued)} document(s)")

    deadline = time.time() + 600
    while queued and time.time() < deadline:
        docs = {d["filename"]: d for d in engine("GET", "/knowledge-base/documents?limit=100")["documents"]}
        pending = [n for n in queued if docs.get(n, {}).get("processing_status") in ("pending", "processing")]
        if not pending:
            break
        time.sleep(3)
    docs = engine("GET", "/knowledge-base/documents?limit=100")["documents"]
    failed = [d for d in docs if d["processing_status"] == "failed"]
    done = [d for d in docs if d["processing_status"] == "completed"]
    print(f"knowledge base: {len(done)} ready, {len(failed)} failed")
    for d in failed:
        print(f"  failed: {d['filename']}: {d.get('processing_error')}")


if __name__ == "__main__":
    main()
