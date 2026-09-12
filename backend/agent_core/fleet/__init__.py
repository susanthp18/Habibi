"""Compiled Fleet Phase 1 — one card, one persisted executable contract.

The compiled bundle is what a call runs; it is compared against the live
row on every load so drift is logged, never silently served.

Re-exports are resolved lazily (PEP 562), for the same reason
``agent_core.cards.__init__`` defers its own — and importing *any* submodule
runs this ``__init__`` first, so ``from agent_core.fleet.schema import
CompiledBundle`` in ``schemas.py`` was enough to reopen the cycle that
``agent_core.cards`` was rewritten to close:

    schemas
      -> agent_core.fleet.schema
        -> agent_core.fleet.__init__
          -> agent_core.fleet.compile
            -> agent_core.cards.compile   (the compiler, on every API import)

``tests/test_import_cycles.py`` pins that ``agent_core.cards.compile`` stays
out of ``sys.modules`` after a bare submodule import. Deferring here restores
that without changing the public surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only, never executed at runtime
    # PEP 484's explicit re-export form; see the note in agent_core/cards.
    from agent_core.fleet.compile import bundle_hash_valid as bundle_hash_valid
    from agent_core.fleet.compile import compile_bundle as compile_bundle
    from agent_core.fleet.compile import digest as digest
    from agent_core.fleet.compile import parity_report as parity_report
    from agent_core.fleet.schema import CompiledBundle as CompiledBundle

_EXPORTS: dict[str, str] = {
    "CompiledBundle": "agent_core.fleet.schema",
    "bundle_hash_valid": "agent_core.fleet.compile",
    "compile_bundle": "agent_core.fleet.compile",
    "digest": "agent_core.fleet.compile",
    "parity_report": "agent_core.fleet.compile",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_path), name)
    globals()[name] = value  # resolve once, then behave like a plain attribute
    return value
