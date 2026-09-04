"""Fail when a dated constant is within 30 days of becoming stale.

Two fixtures have already aged out through a wall-clock guard
(``promised_date`` in ``test_contact_policy``, ``PROMISE_DATE`` in
``test_voice_write_idempotency``). Fish TTS documented a free-tier end
date and the model was never flipped. A ``policy_rule_sets`` row that
expires with no successor silently drops the platform to hardcoded
fallbacks. Relative dates cannot age out; this file is the net for
everything that still can.

A hit is loud 30 days before it fires, so the next instance of the
class is a test failure rather than a red baseline. An ISO assignment
that has already slipped into the past stays loud too — that is the
shape of both bombs, and a lookahead that goes quiet on D-day is how
the class recurs.

An exception is a written, reviewed decision: ``_ALLOWLIST`` keyed by
``(relative_path, identifier)``. A name that happens to contain
``VERSION`` is not an exemption. Expiry comments are future-lookahead
only, so an already-fired date does not re-red this suite — the Fish TTS
free-tier sentence stays in the source as history now that WP-032 has
flipped the default to the paid model.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

HORIZON_DAYS = 30

_SKIP_DIRS = {
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "alembic",
    "htmlcov",
}

# Consulted only when ``hits_in(..., rel=...)`` is supplied, so a
# synthetic snippet cannot hide behind a path it does not have.
_ALLOWLIST: dict[tuple[str, str], str] = {
    (
        "agent_core/mcp_http/protocol.py",
        "PROTOCOL_VERSION",
    ): (
        "MCP specification revision shaped like a date; it is a protocol "
        "identity, not an expiry, and will never lapse."
    ),
}

# Leading whitespace is required: the original PROMISE_DATE bomb was
# column-0, but the next one will not be, and ``^`` without ``\s*``
# would let every indented assignment through.
_ASSIGN_ISO = re.compile(
    r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*[\"'](\d{4}-\d{2}-\d{2})[\"']",
    re.M,
)
_ASSIGN_CTOR = re.compile(
    r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(?:datetime|date)\(\s*(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})",
    re.M,
)
_PROMISE_KWARG = re.compile(
    r"\b(?:promised_date|promise_date|promisedDate)\s*=\s*[\"'](\d{4}-\d{2}-\d{2})[\"']"
)
# Same-line only. DOTALL would let "sunsetted" on one line claim a
# measured date forty characters later, which is how Cartesia's already-
# remediated sonic-2 comments would keep the class "open" forever.
_EXPIRY_BEFORE = re.compile(
    r"(?:free\s+through|expires?(?:\s+on)?|lapses|sunset(?:ted)?)"
    r".{0,40}?(\d{4}-\d{2}-\d{2})",
    re.I,
)
_EXPIRY_AFTER = re.compile(
    r"(\d{4}-\d{2}-\d{2}).{0,40}?(?:lapses|expires|sunset)",
    re.I,
)

_NAMED_TARGETS = (
    "agent_core/providers/fish_tts.py",
    "scripts/seed_policy_rules.py",
    ".env.example",
)


def _parse_iso(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _in_lookahead(when: date, today: date, horizon: int) -> bool:
    return today <= when <= today + timedelta(days=horizon)


def _already_stale_or_upcoming(when: date, today: date, horizon: int) -> bool:
    return when <= today + timedelta(days=horizon)


def _allowlisted(rel: str | None, name: str) -> bool:
    return rel is not None and (rel, name) in _ALLOWLIST


def hits_in(
    source: str,
    *,
    today: date,
    horizon: int = HORIZON_DAYS,
    rel: str | None = None,
) -> list[str]:
    """Return human-readable hits for one file's contents.

    ``rel`` is the path relative to ``backend/``. The allowlist is
    consulted only when it is supplied.
    """
    found: list[str] = []

    for match in _ASSIGN_ISO.finditer(source):
        name, raw = match.group(1), match.group(2)
        if _allowlisted(rel, name):
            continue
        when = _parse_iso(raw)
        # ISO assignments are the PROMISE_DATE bomb: they fail the
        # moment they slip into the past, so already-stale literals
        # count as well as ones inside the lookahead.
        if when is not None and _already_stale_or_upcoming(when, today, horizon):
            line = source[: match.start()].count("\n") + 1
            found.append(f"L{line}: {name}={raw} (dated constant)")

    for match in _ASSIGN_CTOR.finditer(source):
        name = match.group(1)
        if _allowlisted(rel, name):
            continue
        when = date(int(match.group(2)), int(match.group(3)), int(match.group(4)))
        if _in_lookahead(when, today, horizon):
            line = source[: match.start()].count("\n") + 1
            found.append(f"L{line}: {name}={when.isoformat()} (dated constructor)")

    for match in _PROMISE_KWARG.finditer(source):
        raw = match.group(1)
        when = _parse_iso(raw)
        if when is not None and _already_stale_or_upcoming(when, today, horizon):
            line = source[: match.start()].count("\n") + 1
            found.append(f"L{line}: promised_date={raw} (wall-clock fixture)")

    for pattern in (_EXPIRY_BEFORE, _EXPIRY_AFTER):
        for match in pattern.finditer(source):
            raw = match.group(1)
            when = _parse_iso(raw)
            if when is not None and _in_lookahead(when, today, horizon):
                line = source[: match.start()].count("\n") + 1
                found.append(f"L{line}: {raw} (expiry comment)")

    return found


def _iter_sources() -> list[Path]:
    out: list[Path] = []
    env_example = BACKEND / ".env.example"
    if env_example.is_file():
        out.append(env_example)
    for path in BACKEND.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        out.append(path)
    return out


def test_the_scan_flags_a_promise_literal_inside_the_horizon() -> None:
    """Otherwise a broken regex would keep the tree scan vacuously green."""
    today = date(2026, 9, 3)
    hits = hits_in(
        'PROMISE_DATE = "2026-09-14"\n',
        today=today,
    )
    assert hits, "lookahead must catch a dated constant 11 days out"
    hits = hits_in(
        '    PROMISE_DATE = "2026-09-14"\n',
        today=today,
    )
    assert hits, "an indented dated constant must not slip the ^ anchor"
    hits = hits_in(
        'PROMISE_DATE = "2026-09-14"\n',
        today=date(2026, 9, 15),
    )
    assert hits, "an assignment that has already aged out must stay loud"
    hits = hits_in(
        'create_promise_to_pay(promised_date="2026-09-01")\n',
        today=today,
    )
    assert hits, "a past promise fixture is already a red test"


def test_the_scan_flags_fish_tts_and_the_policy_cliff_inside_the_horizon() -> None:
    today = date(2026, 8, 15)
    hits = hits_in(
        "#: **Free through 2026-08-31**, per Fish's announcement.\n",
        today=today,
    )
    assert hits, "Fish TTS end-date comments are the class that already fired"

    hits = hits_in(
        "V2_FROM = datetime(2027, 1, 1, tzinfo=timezone.utc)\n",
        today=date(2026, 12, 10),
    )
    assert hits, "policy_rule_sets.effective_to is a silent fallback cliff"


def test_the_live_fish_tts_sources_are_caught_inside_the_horizon() -> None:
    """Synthetic snippets can drift from the files they claim to protect."""
    today = date(2026, 8, 15)
    fish = (BACKEND / "agent_core" / "providers" / "fish_tts.py").read_text(
        encoding="utf-8"
    )
    assert hits_in(fish, today=today), (
        "fish_tts.py free-through comment must be visible to the scanner"
    )
    env = (BACKEND / ".env.example").read_text(encoding="utf-8")
    assert hits_in(env, today=today), (
        ".env.example free-through comment must be visible to the scanner"
    )


def test_a_lapsed_expiry_comment_does_not_re_red_the_suite() -> None:
    """Expiry comments are future-lookahead only.

    WP-032 has landed: the Fish default is the paid ``s2.1-pro``. The dated
    sentence stays in the source because it records why the default changed,
    and a scanner that re-flagged it would punish keeping the history.
    """
    today = date(2026, 9, 3)
    fish = (BACKEND / "agent_core" / "providers" / "fish_tts.py").read_text(
        encoding="utf-8"
    )
    assert hits_in(fish, today=today) == [], (
        "a lapsed expiry comment kept as history must not re-red this suite"
    )
    env = (BACKEND / ".env.example").read_text(encoding="utf-8")
    assert hits_in(env, today=today) == [], (
        "already-lapsed .env.example free-through must not re-red this suite"
    )


def test_the_live_policy_rule_set_cliff_is_caught_inside_the_horizon() -> None:
    seed = (BACKEND / "scripts" / "seed_policy_rules.py").read_text(encoding="utf-8")
    hits = hits_in(seed, today=date(2026, 12, 10))
    assert hits, "V2_FROM in seed_policy_rules.py is the effective_to cliff"
    assert hits_in(seed, today=date(2026, 9, 3)) == [], (
        "V2_FROM is 2027-01-01; a September clock must not trip it"
    )


def test_the_allowlist_not_a_version_name_regex_exempts_protocol_version() -> None:
    """Without rel the snippet is a hit; with it, only the named path is clean.

    That is what proves the allowlist, not a name regex, is doing the work.
    A real expiry whose identifier contains VERSION must stay loud.
    """
    today = date(2026, 9, 3)
    snippet = 'PROTOCOL_VERSION = "2025-11-25"\n'
    assert hits_in(snippet, today=today), (
        "without rel, PROTOCOL_VERSION is a dated constant — the allowlist "
        "is path-keyed and cannot fire on a snippet"
    )
    assert hits_in(
        snippet,
        today=today,
        rel="agent_core/mcp_http/protocol.py",
    ) == [], "the one allowlisted (path, name) pair must be clean"
    assert hits_in(
        snippet,
        today=today,
        rel="agent_core/other.py",
    ), "a different path must not inherit the PROTOCOL_VERSION exemption"
    assert hits_in(
        'LICENSE_VERSION_VALID_UNTIL = "2026-09-10"\n',
        today=today,
    ), "a real expiry whose name contains VERSION must stay loud"

    rel = "agent_core/mcp_http/protocol.py"
    source = (BACKEND / rel).read_text(encoding="utf-8")
    assert hits_in(source, today=today), (
        "without rel, the live PROTOCOL_VERSION assignment is a hit"
    )
    assert hits_in(source, today=today, rel=rel) == []


def test_the_scan_ignores_frozen_clocks_and_far_dates() -> None:
    today = date(2026, 9, 3)
    # Frozen corpus clocks are constructors in the past; the constructor
    # scan is future-lookahead only, so they are origins, not bombs.
    assert hits_in(
        "NOW = datetime(2026, 8, 14, 6, 0, tzinfo=timezone.utc)\n",
        today=today,
    ) == []
    assert hits_in(
        "V2_FROM = datetime(2027, 1, 1, tzinfo=timezone.utc)\n",
        today=today,
    ) == []
    assert hits_in(
        'holdUntil = "2026-09-21"\n',
        today=today,
    ) == []
    # Historical constructors (V1_FROM = 2020-01-01) are origins, not bombs.
    assert hits_in(
        "V1_FROM = datetime(2020, 1, 1, tzinfo=timezone.utc)\n",
        today=today,
    ) == []


def test_dated_constants_are_not_within_30_days_of_expiry() -> None:
    today = date.today()
    sources = _iter_sources()
    rels = {path.relative_to(BACKEND).as_posix() for path in sources}
    missing = [name for name in _NAMED_TARGETS if name not in rels]
    assert not missing, (
        "tree scan skipped the named targets — these tests would go vacuous: "
        + ", ".join(missing)
    )
    offenders: list[str] = []
    for path in sources:
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = path.relative_to(BACKEND).as_posix()
        for hit in hits_in(source, today=today, rel=rel):
            offenders.append(f"{rel}:{hit}")
    assert offenders == [], (
        "dated constant(s) within "
        f"{HORIZON_DAYS} days of {today.isoformat()}; convert to "
        "date.today() + timedelta(...) or publish a successor:\n"
        + "\n".join(offenders)
    )
