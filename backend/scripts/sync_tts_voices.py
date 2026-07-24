"""CLI: sync Azure TTS voice catalog into Postgres.

Usage (from backend/):
  .venv/Scripts/python -m scripts.sync_tts_voices
  .venv/Scripts/python -m scripts.sync_tts_voices --from-json ../azure_tts_voices.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("DB_PROCESS_ROLE", "worker")

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from env_loader import load_env

load_env()

import db  # noqa: E402
from tts_catalog_sync import run_sync  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Azure TTS voice catalog")
    parser.add_argument(
        "--from-json",
        type=str,
        default=None,
        help="Import from JSON dump instead of calling Azure",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reserved for future use (always runs sync)",
    )
    args = parser.parse_args()

    if args.from_json:
        summary = run_sync(db.engine, source="json_import", json_path=args.from_json)
    else:
        summary = run_sync(db.engine, source="azure")

    print(json.dumps(summary, indent=2, default=str))
    if summary.get("error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
