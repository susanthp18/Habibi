"""Shared plumbing: the engine through ``db``, and the column probes the older
reads still need.

One module of the ``db_prompt_studio`` package (was one 3,400-line file).
Call sites stay ``db.*``; the package re-exports every name.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

_FROZEN_TOOLS_COL: bool | None = None

_CHAIN_HEADS_TABLE: bool | None = None

_COMPILED_COL: bool | None = None

_BUNDLE_HASH_COL: bool | None = None

def _column_exists(conn: Any, table: str, column: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = :t AND column_name = :c
            """
        ),
        {"t": table, "c": column},
    ).first()
    return bool(row)

def _frozen_tools_select(conn: Any) -> str:
    """``d.frozen_tools`` once migrated; NULL alias until then so SELECTs do not 500."""
    global _FROZEN_TOOLS_COL
    if _FROZEN_TOOLS_COL is None:
        _FROZEN_TOOLS_COL = _column_exists(conn, "bot_deployments", "frozen_tools")
    return "d.frozen_tools" if _FROZEN_TOOLS_COL else "NULL::jsonb AS frozen_tools"

def _compiled_select(conn: Any) -> str:
    global _COMPILED_COL
    if _COMPILED_COL is None:
        _COMPILED_COL = _column_exists(conn, "prompt_versions", "compiled")
    return "p.compiled" if _COMPILED_COL else "NULL::jsonb AS compiled"

def _bundle_hash_select(conn: Any) -> str:
    global _BUNDLE_HASH_COL
    if _BUNDLE_HASH_COL is None:
        _BUNDLE_HASH_COL = _column_exists(conn, "bot_deployments", "bundle_hash")
    return "d.bundle_hash" if _BUNDLE_HASH_COL else "NULL::text AS bundle_hash"

def _db():
    """The ``db`` module object, resolved at call time.

    Carved modules must use ``_db().engine``, never ``from db_core import
    engine``. See ``db_core._db``.
    """
    import db as d

    return d

logger = logging.getLogger(__name__)
