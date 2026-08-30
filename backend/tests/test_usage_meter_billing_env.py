"""``usage_meter``'s environment bucket is not the promoted ``env_name``.

Cycle 15 moved ``NON_PROD_ENVS`` / ``env_name`` onto ``env_utils`` and folded
the copies in ``skills/sign`` and ``vault/seal`` onto it. ``usage_meter`` looked
like the last unfolded copy. It is not one: it answers a different question, and
folding it onto ``env_utils.env_name`` would have changed the value written into
``usage_events.environment`` in three separate ways.

1. Different column. ``db._BILLING_ENVS`` accepts only ``production`` and
   ``sandbox``, so this has to bucket, not report. ``env_name()`` returns
   whatever the environment says — ``staging`` reaches the database as itself
   and ``billing_overview`` then raises ``invalid_env``.
2. Different default. Unset bills as ``production``; ``env_name()`` assumes a
   laptop and says ``dev``. Under the shared default, an unconfigured box's
   metered spend would file under ``sandbox`` and quietly leave the invoice.
3. Different allow-list. ``NON_PROD_ENVS`` counts ``test``/``testing``/``ci`` as
   non-production, which is right for "may this box use the committed dev key?"
   and wrong for money: a CI box that meters a real Azure call has spent real
   money.

What *is* shared is the allow-list itself, and this file pins that it is shared
by derivation rather than copied — so the two cannot drift on the four names
they agree about, while the three they disagree about stay named and visible.
"""

from __future__ import annotations

import pytest

import env_utils
import usage_meter


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BILLING_ENV", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)


# --- the shared half --------------------------------------------------------


def test_the_sandbox_bucket_is_derived_from_the_shared_allow_list() -> None:
    """Not a fourth hand-written copy of the same four strings."""
    assert usage_meter._SANDBOX_BILLING_ENVS == env_utils.NON_PROD_ENVS - {
        "test",
        "testing",
        "ci",
    }
    assert usage_meter._SANDBOX_BILLING_ENVS == {"dev", "development", "local", "sandbox"}


def test_the_private_env_name_copy_is_gone() -> None:
    """The name that made this look like an unfolded duplicate.

    Renamed rather than deleted, because the function still has to exist —
    it just is not the same question ``env_utils.env_name`` answers, and while
    it shared that name every reader had to re-derive that for themselves.
    """
    assert not hasattr(usage_meter, "_env_name")
    assert callable(usage_meter._billing_env)


# --- the divergent half, pinned so a later fold cannot happen silently ------


def test_an_unset_environment_bills_as_production() -> None:
    """Opposite default to ``env_utils.env_name()``, on purpose."""
    assert env_utils.env_name() == "dev"
    assert usage_meter._billing_env() == "production"


@pytest.mark.parametrize("env", ["test", "testing", "ci"])
def test_a_test_runner_still_bills_as_production(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    """The three names the two allow-lists disagree about.

    ``env_allows_dev_key()`` says yes for all three — a CI box may sign with the
    committed key. Its Azure bill is still real.
    """
    monkeypatch.setenv("APP_ENV", env)
    assert env_utils.env_allows_dev_key() is True
    assert usage_meter._billing_env() == "production"


@pytest.mark.parametrize("env", ["sandbox", "dev", "development", "local", "SANDBOX", " Dev "])
def test_the_declared_sandbox_names_bill_as_sandbox(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    monkeypatch.setenv("APP_ENV", env)
    assert usage_meter._billing_env() == "sandbox"


@pytest.mark.parametrize("env", ["production", "prod", "staging", "uat", "dvelopment"])
def test_everything_else_bills_as_production(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    """Including ``staging`` and a typo — neither may reach the column raw."""
    monkeypatch.setenv("APP_ENV", env)
    assert usage_meter._billing_env() == "production"


def test_billing_env_wins_over_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The input ``env_utils.env_name()`` has no way to express.

    A sandbox tenant metered on a production deployment is the reason this
    override exists; the shared helper knows only ``APP_ENV``/``ENV``.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("BILLING_ENV", "sandbox")
    assert usage_meter._billing_env() == "sandbox"

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("BILLING_ENV", "production")
    assert usage_meter._billing_env() == "production"


def test_bare_env_is_not_a_billing_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """``env_name()`` falls back to ``ENV``; billing deliberately does not.

    Folding would have picked this fallback up for free and flipped the metered
    environment on any box that sets ``ENV`` without ``APP_ENV``. Pinned so the
    narrower input set is a decision rather than an omission someone tidies up.
    """
    monkeypatch.setenv("ENV", "sandbox")
    assert env_utils.env_name() == "sandbox"
    assert usage_meter._billing_env() == "production"


# --- and the value actually lands in the column -----------------------------


def test_the_bucket_is_always_a_value_the_billing_reader_accepts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The constraint that makes this a bucket and not a name.

    ``db.billing_overview`` raises ``invalid_env`` for anything outside this
    set, and ``usage_events.environment`` is what it filters on.
    """
    import db

    for env in ["", "production", "staging", "dev", "test", "sandbox", "hunter2", "prod"]:
        monkeypatch.setenv("APP_ENV", env)
        assert usage_meter._billing_env() in db._BILLING_ENVS


def test_an_explicit_environment_argument_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """``record_usage()`` only falls back to the bucket; callers may override it."""
    monkeypatch.setenv("APP_ENV", "production")
    captured: list[dict] = []
    monkeypatch.setattr(usage_meter, "_ensure_flusher", lambda: None)
    monkeypatch.setattr(usage_meter, "_tenant_id", lambda: "t-billing-env")

    with usage_meter._buffer_lock:
        usage_meter._buffer.clear()
    try:
        usage_meter.record_usage(service_id="llm_chat", units=1, cost_inr=1, environment="sandbox")
        usage_meter.record_usage(service_id="llm_chat", units=1, cost_inr=1)
        with usage_meter._buffer_lock:
            captured = [dict(e) for e in usage_meter._buffer]
    finally:
        with usage_meter._buffer_lock:
            usage_meter._buffer.clear()

    assert [e["environment"] for e in captured] == ["sandbox", "production"]
