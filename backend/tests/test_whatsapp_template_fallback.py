"""WHATSAPP_FALLBACK_TEMPLATE_* resolution order.

.env.example documented this pair from the day the WhatsApp block was written
and nothing read either variable. The three names actually consumed are
purpose-specific — WHATSAPP_PTP_TEMPLATE_NAME, WHATSAPP_BOUNCE_TEMPLATE_NAME,
WHATSAPP_TREATMENT_TEMPLATE_NAME — so an operator who worked down the file
top-to-bottom configured a fallback, believed sends outside Meta's 24h service
window were covered, and got nothing: no template resolved means the send does
not happen at all.

The resolution order these tests pin is the whole fix. There is one more thing
they defend that is easy to lose: the language belongs to the template that was
actually chosen. Pairing a purpose-specific template with the fallback's
language would be a quieter version of the same bug.
"""

from __future__ import annotations

import pytest

import promise_fulfillment as pf

PTP_NAME = "WHATSAPP_PTP_TEMPLATE_NAME"
PTP_LANG = "WHATSAPP_PTP_TEMPLATE_LANG"


@pytest.fixture(autouse=True)
def _clean_template_env(monkeypatch: pytest.MonkeyPatch):
    """Start from nothing set, whatever the developer's .env happens to hold.

    ``load_env()`` is forced first so this fixture's snapshot is symmetric. It
    is once-only (``_LOADED``) and non-destructive (``if key not in
    os.environ``), so blanking a key *before* the first load would make dotenv
    skip that key permanently, and monkeypatch would then delete the blank at
    teardown — leaving the variable unset for the rest of the process where it
    would otherwise have carried its .env value. Loading first means every key
    already exists, so monkeypatch restores rather than deletes.
    """
    from env_loader import load_env

    load_env()
    for name in (PTP_NAME, PTP_LANG, pf.FALLBACK_TEMPLATE_NAME_ENV, pf.FALLBACK_TEMPLATE_LANG_ENV):
        monkeypatch.setenv(name, "")


def test_the_purpose_specific_template_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PTP_NAME, "ptp_confirm_v3")
    monkeypatch.setenv(PTP_LANG, "en_IN")
    monkeypatch.setenv(pf.FALLBACK_TEMPLATE_NAME_ENV, "generic_fallback")
    monkeypatch.setenv(pf.FALLBACK_TEMPLATE_LANG_ENV, "hi_IN")

    assert pf.resolve_template(PTP_NAME, PTP_LANG) == ("ptp_confirm_v3", "en_IN")


def test_the_fallback_fills_an_unset_purpose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(pf.FALLBACK_TEMPLATE_NAME_ENV, "generic_fallback")
    monkeypatch.setenv(pf.FALLBACK_TEMPLATE_LANG_ENV, "hi_IN")

    assert pf.resolve_template(PTP_NAME, PTP_LANG) == ("generic_fallback", "hi_IN")


def test_neither_set_resolves_to_no_template(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pre-existing behaviour, unchanged: no template, so no template send."""
    assert pf.resolve_template(PTP_NAME, PTP_LANG) == ("", "")


def test_the_language_belongs_to_the_template_that_was_chosen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Purpose template set, its language not. It must NOT borrow the fallback's
    # language — that would send a template registered in one language tagged
    # as another, which Meta rejects.
    monkeypatch.setenv(PTP_NAME, "ptp_confirm_v3")
    monkeypatch.setenv(pf.FALLBACK_TEMPLATE_NAME_ENV, "generic_fallback")
    monkeypatch.setenv(pf.FALLBACK_TEMPLATE_LANG_ENV, "hi_IN")

    assert pf.resolve_template(PTP_NAME, PTP_LANG) == ("ptp_confirm_v3", "en_US")


def test_a_fallback_without_a_language_defaults_to_en_us(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(pf.FALLBACK_TEMPLATE_NAME_ENV, "generic_fallback")

    assert pf.resolve_template(PTP_NAME, PTP_LANG) == ("generic_fallback", "en_US")


@pytest.mark.parametrize(
    "name_env, lang_env",
    [
        ("WHATSAPP_PTP_TEMPLATE_NAME", "WHATSAPP_PTP_TEMPLATE_LANG"),
        ("WHATSAPP_BOUNCE_TEMPLATE_NAME", "WHATSAPP_BOUNCE_TEMPLATE_LANG"),
        ("WHATSAPP_TREATMENT_TEMPLATE_NAME", "WHATSAPP_TREATMENT_TEMPLATE_LANG"),
    ],
)
def test_every_documented_purpose_honours_the_fallback(
    monkeypatch: pytest.MonkeyPatch, name_env: str, lang_env: str
) -> None:
    """All three purposes .env.example documents, not just the one that was easy."""
    monkeypatch.setenv(name_env, "")
    monkeypatch.setenv(lang_env, "")
    monkeypatch.setenv(pf.FALLBACK_TEMPLATE_NAME_ENV, "generic_fallback")

    assert pf.resolve_template(name_env, lang_env)[0] == "generic_fallback"


def test_the_send_path_uses_the_resolved_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    """enqueue_whatsapp_paylink must resolve the same way the gates do.

    The gate and the send read the template independently. If only one of them
    learned about the fallback, a bounce notice would pass the "we have a
    template" check and then be enqueued with no template name.
    """
    monkeypatch.setenv(pf.FALLBACK_TEMPLATE_NAME_ENV, "generic_fallback")
    monkeypatch.setenv(pf.FALLBACK_TEMPLATE_LANG_ENV, "en_IN")

    sent: dict[str, object] = {}

    class _FakeWaOut:
        @staticmethod
        def enqueue_agent_send(conn, **kwargs):
            sent.update(kwargs)

    class _FakeDb:
        @staticmethod
        def _open_whatsapp_conversation(conn, customer_id):
            return "CONV-UT"

        @staticmethod
        def _id(prefix):
            return f"{prefix}-UT"

    class _FakeConn:
        def execute(self, *_args, **_kwargs):
            return None

    import sys

    monkeypatch.setitem(sys.modules, "whatsapp_outbound", _FakeWaOut)
    monkeypatch.setitem(sys.modules, "db", _FakeDb)

    pf.enqueue_whatsapp_paylink(
        _FakeConn(),
        customer_id="CUST-UT",
        intent={"amount": 2500, "pay_url": "https://pay.example.com/x"},
        to_phone="+919000000001",
        body="body",
        use_template=True,
        template_env_name=PTP_NAME,
        template_env_lang=PTP_LANG,
        template_params=["2,500", "2026-09-01", "https://pay.example.com/x"],
    )

    assert sent["template_name"] == "generic_fallback"
    assert sent["template_lang"] == "en_IN"
