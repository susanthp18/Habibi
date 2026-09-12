from __future__ import annotations

from typing import Any

import pytest

from agent_core.cards.compile import CompileReport, GateResult
from agent_core.fleet.compile import compile_bundle, digest, parity_report
from agent_core.tools.gates import GATE_IDENTITY, enforce_human_gate
from agent_core.tools.grant import TEXT, VOICE, ToolGrant
from sandbox_runtime import simulate_sandbox_tool


def _report() -> CompileReport:
    return CompileReport(
        bot_id="collections",
        gates=[GateResult(gate="G0", name="schema", status="pass")],
        card={},
    )


def test_compiled_bundle_is_deterministic_and_self_hashing() -> None:
    first = compile_bundle(
        report=_report(),
        prompt="system",
        persona={"tone": "calm"},
        guardrails={"maxTurns": 3},
        flow={"nodes": [], "edges": []},
        prompt_version_id="pv-1",
    )
    second = compile_bundle(
        report=_report(),
        prompt="system",
        persona={"tone": "calm"},
        guardrails={"maxTurns": 3},
        flow={"edges": [], "nodes": []},
        prompt_version_id="pv-1",
    )

    assert first == second
    unhashed = first.model_dump(mode="json")
    unhashed.pop("bundle_hash")
    assert first.bundle_hash == digest(unhashed)
    assert parity_report(
        live_prompt="system",
        live_persona={"tone": "calm"},
        live_guardrails={"maxTurns": 3},
        live_flow={"nodes": [], "edges": []},
        # A cardless voice mouth keeps the flow-control floor (ADR-0002,
        # amended): that is what the live runtime builds and what the bundle
        # must agree with.
        live_tools=sorted(ToolGrant.for_card(None, (), channel=VOICE).allowed),
        bundle=first,
        bot_id="collections",
        prompt_version_id="pv-1",
    )["ok"]


def test_compile_bundle_is_stable_under_concurrent_calls() -> None:
    from concurrent.futures import ThreadPoolExecutor

    def once(_: int) -> str:
        return compile_bundle(
            report=_report(),
            prompt="system",
            persona={"tone": "calm"},
            guardrails={"maxTurns": 3},
            flow={"nodes": [], "edges": []},
            prompt_version_id="pv-1",
        ).bundle_hash

    with ThreadPoolExecutor(max_workers=8) as pool:
        hashes = list(pool.map(once, range(16)))
    assert len(set(hashes)) == 1


def test_shared_human_gates_fail_closed() -> None:
    assert (
        enforce_human_gate(
            "create_promise_to_pay",
            card={},
            identity_verified=False,
        )
        == GATE_IDENTITY
    )
    # `require: floor` is retired: no floor ledger ever existed, so it blocked
    # forever while the regulator export said a supervisor approved it. A
    # stored value reads as the half that is enforced -- identity.
    floor_card = {"human_gates": [{"tool_name": "apply_goodwill", "require": "floor"}]}
    assert enforce_human_gate("apply_goodwill", card=floor_card, identity_verified=True) is None
    assert (
        enforce_human_gate("apply_goodwill", card=floor_card, identity_verified=False)
        == GATE_IDENTITY
    )


def test_an_unverified_caller_is_not_transferred_to_a_specialist() -> None:
    """Only intake-v1 declared this gate, and intake is not where calls land.

    BOT_ID resolves to collections, whose card declares no gate on
    handoff_to_agent — so the card every inbound call actually reaches would
    hand an unverified caller to a specialist that opens with their account in
    front of it. The floor covers it for every card, including a fleet member
    added later that forgets to declare the gate its sender holds.
    """
    assert (
        enforce_human_gate("handoff_to_agent", card={}, identity_verified=False)
        == GATE_IDENTITY
    )
    assert enforce_human_gate("handoff_to_agent", card={}, identity_verified=True) is None


def test_reaching_a_person_never_requires_passing_a_ceremony() -> None:
    """The caller failing verification is precisely who needs a human."""
    assert enforce_human_gate("escalate_to_human", card={}, identity_verified=False) is None


def test_sandbox_never_dispatches_writes_or_connectors() -> None:
    ok, write = simulate_sandbox_tool(
        "create_promise_to_pay", {"amount": 1000}
    )
    assert ok is True
    assert write["simulated"] is True
    assert "would write" in write["effect"]

    ok, connector = simulate_sandbox_tool("ext.crm.lookup", {})
    assert ok is False
    assert connector["error"] == "sandbox_connector_blocked"

    import inspect
    import sandbox_runtime

    source = inspect.getsource(sandbox_runtime._run_sandbox_tool_loop)
    assert "execute_tool(" not in source
    assert "record_tool_call(" not in source


def test_frozen_connectors_are_text_only() -> None:
    from agent_core.cards.defaults import COLLECTIONS_BOT_ID, card_dump
    from agent_core.cards.schema import parse_card

    raw = card_dump(COLLECTIONS_BOT_ID)
    raw["connectors"] = [
        {"connector_id": "crm", "allow_prefixes": ["ext.crm."]}
    ]
    card = parse_card(raw)
    frozen = ["ext.crm.lookup"]
    # A connector tool enters the grant only through a pack that offers it
    # (CONNECTORS-17); the channel rule is tested with such a pack attached.
    from dataclasses import replace

    from agent_core.skills.pack import pack_for_slug

    pack = pack_for_slug("ptp-negotiate")
    packs = [replace(pack, allowed_tools=[*pack.allowed_tools, "ext.crm.lookup"])]

    assert "ext.crm.lookup" in ToolGrant.for_card(
        card,
        packs,
        channel=TEXT,
        frozen_connector_tools=frozen,
    ).allowed
    assert "ext.crm.lookup" not in ToolGrant.for_card(
        card,
        packs,
        channel=VOICE,
        frozen_connector_tools=frozen,
    ).allowed
    assert "ext.crm.lookup" not in ToolGrant.for_card(
        card, [], channel=TEXT, frozen_connector_tools=frozen
    ).allowed, "no pack offers it, so the grant does not hold it"


def test_exact_skill_version_is_part_of_the_signed_row_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_core.skills.persist as persist

    class CaptureConnection:
        params: dict[str, Any] = {}

        def execute(self, _statement: object, params: dict[str, Any]) -> object:
            self.params = params
            return object()

    conn = CaptureConnection()
    monkeypatch.setattr(persist.db, "_one", lambda _rows: {"id": "sv-2"})
    row = persist._latest_signed_version(
        conn,
        slug="ptp-negotiate",
        version="2.0.0",
    )

    assert row == {"id": "sv-2"}
    assert conn.params["ver"] == "2.0.0"


def test_generic_prompt_body_requires_agent_edit_only_when_card_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import main
    from routers import agent_studio as studio_routes

    monkeypatch.setattr(main.db, "_actor_user_id", lambda: "prompt-author")
    monkeypatch.setattr(main.authz, "has_permission", lambda *_args: False)

    studio_routes._require_agent_edit_for_card({"prompt": "ordinary prompt edit"})
    with pytest.raises(Exception) as denied:
        studio_routes._require_agent_edit_for_card({"agentCard": {}})
    assert getattr(denied.value, "status_code", None) == 403


def test_a2a_registration_rejects_invalid_certificate_text() -> None:
    from agent_core.a2a import fingerprint_certificate

    with pytest.raises(ValueError, match="a2a_cert_pem_invalid"):
        fingerprint_certificate(
            "-----BEGIN CERTIFICATE-----\nnot-base64\n-----END CERTIFICATE-----"
        )


class _Rows:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row


class _Connection:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, *_args: object, **_kwargs: object) -> _Rows:
        return _Rows(self.row)


class _Engine:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    def connect(self) -> _Connection:
        return _Connection(self.row)


@pytest.mark.parametrize(
    ("partner", "code"),
    [
        (
            {
                "id": "p-1",
                "tenant_id": "tenant-a",
                "bot_id": "bot-b",
                "status": "active",
            },
            "a2a_bot_mismatch",
        ),
        (
            {
                "id": "p-1",
                "tenant_id": "tenant-b",
                "bot_id": "bot-a",
                "status": "active",
            },
            "a2a_partner_unknown",
        ),
    ],
)
def test_a2a_partner_cannot_cross_bot_or_tenant(
    monkeypatch: pytest.MonkeyPatch,
    partner: dict[str, Any],
    code: str,
) -> None:
    import agent_core.a2a as a2a

    monkeypatch.setenv("A2A_ENABLED", "true")
    monkeypatch.setenv("A2A_TRUSTED_PROXY_CIDRS", "127.0.0.1/32")
    monkeypatch.setattr(a2a, "_partners_have_bot_id", lambda _conn: True)
    monkeypatch.setattr(a2a.db, "engine", _Engine(partner))
    monkeypatch.setattr(a2a.db, "_one", lambda rows: rows.row)
    monkeypatch.setattr(a2a.db, "current_tenant", lambda: "tenant-a")

    with pytest.raises(PermissionError, match=code):
        a2a.require_partner(
            {
                "x-ssl-client-verify": "SUCCESS",
                "x-ssl-client-dn": "CN=partner",
                "x-ssl-client-fingerprint": "ab" * 32,
            },
            bot_id="bot-a",
            client_host="127.0.0.1",
        )
