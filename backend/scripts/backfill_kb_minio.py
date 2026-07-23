"""Backfill disk source_path originals into MinIO + kb_source_files.

Usage:
  .venv/Scripts/python -m scripts.backfill_kb_minio
  .venv/Scripts/python -m scripts.backfill_kb_minio --limit 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db
from env_loader import load_env
import storage


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description="Backfill KB disk sources into MinIO")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    storage.ensure_bucket()
    result = db.backfill_kb_sources_to_minio(limit=args.limit)
    print(result)


if __name__ == "__main__":
    main()
