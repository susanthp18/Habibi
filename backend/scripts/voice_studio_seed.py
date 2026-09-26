"""Provision PayInt Voice Studio for this tenant: tools, the collections agent,
the dialler's API key, telephony, and the objective binding.

Idempotent: missing starter assets are created. Existing edited tools, agents,
published definitions and live routing are left untouched. No secret is printed.

What it creates in the engine (as the system actor, via the internal API):
  * credential  "PayInt hooks"          bearer = VOICE_STUDIO_HOOK_TOKEN
  * HTTP tools  verify_identity, account_position, promise_to_pay,
                request_callback, flag_dispute  -> /voice-studio/hooks/tools/*
  * transfer    transfer_to_human (dynamic)     -> /voice-studio/hooks/transfer
  * agent       "Collections - overdue reminder": greeting (inbound pre-call
                lookup), identity, position, resolution, closings, API
                trigger, post-call webhook -> /voice-studio/hooks/run-completed
  * API key     "PayInt dialler"       -> VOICE_STUDIO_API_KEY in --env-file
  * telephony   Twilio from TWILIO_*, with TWILIO_PHONE_NUMBER as caller id
Every approved tool that exists is validated (endpoint, credential, context
parameters) whether or not an agent uses it yet.

Routing is never changed silently. Missing outbound/WhatsApp bindings are
reported; --create-bindings creates them through voice_studio_routing.assign,
the same preflighted and audited path as the Agent routing screen. Inbound
phone routing is only ever set on that screen.

    docker exec collections_api python -m scripts.voice_studio_seed --actor priya-nair
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from env_loader import load_env
from env_utils import env_str

AGENT_NAME = "Collections - overdue reminder"
INBOUND_AGENT_NAME = "Inbound - customer help"
WHATSAPP_AGENT_NAME = "WhatsApp - customer help"
CREDENTIAL_NAME = "PayInt hooks"
API_KEY_NAME = "PayInt dialler"
TELEPHONY_NAME = "PayInt Twilio"
BANK = "BigTapp Bank"

CTX = [  # engine-injected ids every tool receives (never chosen by the model).
    # Optional ones that are absent render empty and are dropped by the engine.
    ("workflow_run_id", "number", "{{initial_context.workflow_run_id}}", True),
    ("agent_id", "string", "{{initial_context.agent_id}}", False),
    ("attempt_id", "string", "{{initial_context.attempt_id}}", False),
    ("customer_id", "string", "{{initial_context.customer_id}}", False),
    ("account_id", "string", "{{initial_context.account_id}}", False),
    # Stamped by the engine on real calls and API triggers, and by WhatsApp;
    # absent = an editor test, which voice_studio answers without real records.
    ("direction", "string", "{{initial_context.direction}}", False),
    ("rehearsal", "string", "{{initial_context.rehearsal}}", False),
    # WhatsApp threads: the tools act on the thread's own interaction.
    ("channel", "string", "{{initial_context.channel | fallback:voice}}", False),
    ("interaction_id", "string", "{{initial_context.interaction_id}}", False),
    ("conversation_id", "string", "{{initial_context.conversation_id}}", False),
]

TOOLS: list[dict[str, Any]] = [
    {
        "name": "verify_identity",
        "description": "Verify the caller is the account holder. Call with the four digits they say.",
        "parameters": [
            {"name": "method", "type": "string", "required": True,
             "description": "phone_last4 (last four digits of the registered mobile); inbound may use account_tail."},
            {"name": "value", "type": "string", "required": True,
             "description": "The four digits exactly as the caller said them."},
        ],
    },
    {
        "name": "account_position",
        "description": "Get the verified customer's overdue amount, days past due, minimum due and any open promise.",
        "parameters": [],
    },
    {
        "name": "promise_to_pay",
        "description": "Record the customer's promise to pay. Only after they commit to an amount and a date.",
        "parameters": [
            {"name": "amount", "type": "number", "required": True, "description": "Amount in rupees."},
            {"name": "date", "type": "string", "required": True, "description": "Payment date, YYYY-MM-DD."},
            {"name": "reason", "type": "string", "required": False,
             "description": "Only when this changes an existing promise: customer_requested_delay, salary_delayed, "
                            "medical, dispute_raised, partial_payment_agreed or other."},
        ],
    },
    {
        "name": "request_callback",
        "description": "Book a callback when the customer asks to be called back or cannot talk now.",
        "parameters": [
            {"name": "when", "type": "string", "required": True,
             "description": "Callback time as ISO date-time, as agreed with the customer."},
            {"name": "reason", "type": "string", "required": False, "description": "Short reason."},
        ],
    },
    {
        "name": "flag_dispute",
        "description": "Open a dispute when the customer says a charge or the amount is wrong.",
        "parameters": [
            {"name": "type", "type": "string", "required": True,
             "description": "One of: amount_mismatch, not_my_transaction, already_paid, service_issue, other."},
            {"name": "summary", "type": "string", "required": True, "description": "One sentence."},
        ],
    },
]

GLOBAL_PROMPT = f"""You are Kaia, an assistant speaking on behalf of {BANK}.
It is now {{{{current_time_Asia/Kolkata}}}} ({{{{current_weekday_Asia/Kolkata}}}}); resolve dates the customer says against this.
This is an outbound phone call about the private mission below.
Speak in short, warm, plain sentences, one question at a time, in the customer's language.
Never use Markdown, lists or symbols.
Follow fair-practice rules: be respectful, never threaten, never mention legal action, never
call the customer names, and never discuss the account with anyone but the account holder.
Until verify_identity returns verified, do not reveal why you are calling: never say the words collections, overdue,
payment, due or debt, and share no account detail (amount, dues, account number).
Never read out full account or phone numbers; the last four digits at most.
Say amounts in rupees naturally, for example "twelve thousand five hundred rupees".
If the customer is distressed, mentions hardship, illness or job loss, acknowledge it and offer a callback
from a specialist. If they ask for a person, threaten legal action or become abusive, say you will
connect them to a colleague and use transfer_to_human straight away, even before verification.
If they ask you not to call again, acknowledge it, say you will note it, and close politely.
Never invent facts; if you do not know, say you will have someone follow up.
Treat the inner tool data.ok as the action result. Never say a promise, callback or
dispute was recorded when it is false, even if the HTTP request itself succeeded.
On promise_revision_cap, stop retrying and offer a colleague. When a callback
already exists, explain its existing time rather than booking it again.
Why this call was placed (private: never say any of it until verify_identity returns verified):
{{{{mission_brief | fallback:The customer may have an overdue payment.}}}}"""

NODES = {
    "start": {
        "name": "Greeting",
        "prompt": (
            "Greet, ask to speak with {{first_name | fallback:the account holder}}, "
            "say you are Kaia from " + BANK + " and that the call may be recorded. Do not say why you are calling, and never mention "
            "an account, amount or overdue payment before identity is verified: say only that it is about an important matter "
            "for them. Once they confirm they are the right person, take the Right person path."
        ),
    },
    "verify": {
        "name": "Verify identity",
        "prompt": (
            "Before anything about the account, verify the customer. Ask for the last four digits of the "
            "mobile number registered with the bank and call verify_identity with method phone_last4. As soon as it returns verified true, take the "
            "Verified path straight away, before saying anything about the account. If it is not verified and attempts remain, "
            "ask once more. Never tell them which digits are right. Call verify_identity only with four digits the customer "
            "has just given you; until then, just ask for them."
        ),
    },
    "position": {
        "name": "Explain the overdue amount",
        "prompt": (
            "Call account_position. Tell the customer, in one or two sentences, the overdue amount and how many days it is past due, "
            "and the minimum due if there is one. Ask whether they are able to pay. If they dispute the amount, use flag_dispute."
        ),
    },
    "resolve": {
        "name": "Agree next step",
        "prompt": (
            "Aim for a promise to pay: agree an amount (at least the minimum due) and a date within the next seven days, "
            "read them back, and as soon as they confirm, call promise_to_pay with the amount in rupees and the date as YYYY-MM-DD "
            "(resolved against today's date). If they cannot commit, or the promise cannot be changed, offer a callback: first ask what time suits "
            "them, then call request_callback once, with that time. If the tool fails, do not claim the action was recorded "
            "or take a success path. On promise_revision_cap, do not retry; offer a colleague. If a callback already exists, "
            "do not submit the same callback again. If they already paid, thank them and note it with flag_dispute type already_paid."
        ),
    },
    "end_done": {"name": "Close - agreed", "prompt": "Confirm what was agreed in one sentence, thank them, and say goodbye."},
    "end_failed": {"name": "Close - action failed", "prompt": "Say clearly that the promise, callback or dispute was not recorded. Apologise, offer a human follow-up, and close without a confirmation."},
    "end_unverified": {
        "name": "Close - not verified",
        "prompt": "Explain you cannot discuss the account without verification, suggest they call the number on their card, thank them, and say goodbye.",
    },
    "end_wrong": {
        "name": "Close - wrong person",
        "prompt": "Apologise for the trouble, do not mention why you called, and say goodbye.",
    },
}

EDGES = [
    ("start", "verify", "Right person", "The account holder confirms they are on the outbound call."),
    ("start", "end_wrong", "Wrong person", "The person says the account holder is not available or it is a wrong number."),
    ("verify", "position", "Verified", "verify_identity has returned verified true."),
    ("verify", "end_unverified", "Not verified", "Verification failed with no attempts left, or the caller refuses to verify."),
    ("position", "resolve", "Discuss payment", "The customer has heard the amount and the conversation turns to paying."),
    ("resolve", "end_done", "Agreed", "The most recent promise, callback or dispute action returned data.ok true."),
    ("resolve", "end_failed", "Action failed", "The action was rejected and no successful alternative was recorded; explain the failure without confirming it."),
]

# These are starter definitions only. An operator owns subsequent edits and
# publishing in the visual builder; rerunning this script never replaces them.
INBOUND_GLOBAL_PROMPT = f"""You are Kaia answering an inbound call for {BANK}.
Say the call may be recorded. Ask why the caller is calling, then follow that
reason. Do not assume an overdue payment or start a collections conversation.
Before sharing account-specific information or changing a record, verify the
caller with verify_identity. Never reveal a balance, due date or account detail
to an unverified person. General public information may be answered from the
approved knowledge base without verification. If the request is unsupported,
unclear, or asks for a person, offer a human handoff. Speak briefly and ask one
question at a time. Never claim a tool action succeeded unless it returned ok true.
If an action fails, explain that it was not recorded and offer a safe next step.
"""
INBOUND_NODES = {
    "start": {"name": "Ask why they called", "prompt": (
        "Greet the caller, disclose recording, and ask how you can help. Do not "
        "mention collections, an overdue balance, or a payment unless the caller raises it."
    )},
    "general": {"name": "General information", "prompt": (
        "Answer only general public questions using the approved knowledge base. "
        "For an account-specific question, move to verification first. If the answer "
        "is unavailable, offer a colleague rather than inventing it."
    )},
    "verify": {"name": "Verify identity", "prompt": (
        "Ask for the last four digits of the registered mobile number and call "
        "verify_identity with method phone_last4. Continue to account help only "
        "after verified is true. Never reveal whether a guessed digit is correct."
    )},
    "help": {"name": "Help with the requested account matter", "prompt": (
        "Address only the caller's stated reason. Use account_position if their "
        "question needs it; do not announce overdue details unprompted. Agree and "
        "read back a promise or callback before calling the tool. Say it was "
        "recorded only when the tool returns ok true. If a promise revision is "
        "capped, do not retry it or promise a new one; offer hardship review "
        "or a colleague. If a callback was already booked, confirm its existing "
        "time rather than booking it again."
    )},
    "end_done": {"name": "Close - helped", "prompt": "Summarise the actual outcome, thank the caller, and say goodbye."},
    "end_failed": {"name": "Close - action failed", "prompt": "Say the requested action was not recorded. Offer a human follow-up; never claim it succeeded."},
    "end_unverified": {"name": "Close - not verified", "prompt": "Do not discuss the account. Offer a safe human follow-up and say goodbye."},
}
INBOUND_EDGES = [
    ("start", "general", "General question", "The caller asks for public information, not their account."),
    ("start", "verify", "Account question", "The caller requests account-specific information or an account action."),
    ("general", "verify", "Account question", "The caller now asks about their own account."),
    ("general", "end_done", "Answered", "The general question was answered or a handoff was offered."),
    ("verify", "help", "Verified", "verify_identity returned verified true."),
    ("verify", "end_unverified", "Not verified", "The caller refused or exhausted verification."),
    ("help", "end_done", "Resolved", "The request was answered without a write, or the most recent action returned data.ok true."),
    ("help", "end_failed", "Action failed", "The tool rejected the action and no successful alternative was recorded."),
]

WHATSAPP_GLOBAL_PROMPT = f"""You are Kaia replying to a customer in WhatsApp for {BANK}.
They wrote to us; do not say you are calling or mention call recording. Ask what
they need and reply in two or three plain, short sentences. Before discussing
an account or changing it, verify using the last four digits of the account
number, not the registered phone number. Never invent facts or say an action
was recorded unless its tool returned ok true. Offer a human follow-up when
the request is unsupported or a tool rejects it.
"""
WHATSAPP_NODES = {
    "start": {"name": "Ask how to help", "prompt": "Acknowledge their message and ask what they need. Do not mention calling or recording."},
    "verify": {"name": "Verify account", "prompt": (
        "For account-specific help, ask for the last four digits of their account "
        "number and call verify_identity with method account_tail. Do not use "
        "their mobile digits as the verification factor."
    )},
    "help": {"name": "Resolve request", "prompt": (
        "Answer only the customer's request. Use the relevant approved tool. "
        "Confirm a promise or callback only after ok true. If a promise revision "
        "is capped, offer a colleague rather than retrying."
    )},
    "end_done": {"name": "Close", "prompt": "Briefly confirm the actual outcome and close."},
    "end_failed": {"name": "Close - action failed", "prompt": "Say clearly that the requested action was not recorded and offer a human follow-up."},
    "end_unverified": {"name": "Close - not verified", "prompt": "Do not reveal account details; offer a colleague."},
}
WHATSAPP_EDGES = [
    ("start", "verify", "Account help", "The customer needs account-specific help."),
    ("start", "end_done", "General help", "A general question was answered or handed off."),
    ("verify", "help", "Verified", "verify_identity returned verified true."),
    ("verify", "end_unverified", "Not verified", "The customer refused or exhausted verification."),
    ("help", "end_done", "Resolved", "The request was answered without a write, or the most recent action returned data.ok true."),
    ("help", "end_failed", "Action failed", "The tool rejected the action and no successful alternative was recorded."),
]


class Engine:
    def __init__(self, actor: str) -> None:
        import db

        secret = env_str("AGENTSTUDIO_INTERNAL_SECRET")
        if not secret:
            sys.exit("AGENTSTUDIO_INTERNAL_SECRET is not set")
        self.base = env_str("AGENTSTUDIO_ENGINE_URL", "http://agentstudio_engine:8000").rstrip("/") + "/api/v1"
        self.headers = {"X-Internal-Secret": secret, "X-User-Id": actor, "X-Org-Id": db.current_tenant()}

    def __call__(self, method: str, path: str, json: Any = None) -> Any:
        r = httpx.request(method, self.base + path, json=json, headers=self.headers, timeout=60)
        if r.status_code >= 400:
            sys.exit(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else None


def _param(p: dict[str, Any]) -> dict[str, Any]:
    return {"name": p["name"], "type": p["type"], "description": p.get("description", ""), "required": p["required"]}


def _preset() -> list[dict[str, Any]]:
    return [{"name": n, "type": t, "value_template": v, "required": r} for n, t, v, r in CTX]


def ensure_credential(engine: Engine, token: str) -> str:
    existing = {c["name"]: c for c in engine("GET", "/credentials/")}
    body = {"name": CREDENTIAL_NAME, "description": "Voice Studio -> PayInt hooks",
            "credential_type": "bearer_token", "credential_data": {"token": token}}
    if CREDENTIAL_NAME in existing:
        if existing[CREDENTIAL_NAME].get("credential_type") != "bearer_token":
            sys.exit("PayInt hooks credential has the wrong type; review it in Voice Studio")
        return existing[CREDENTIAL_NAME]["uuid"]
    return engine("POST", "/credentials/", body)["uuid"]


def ensure_tool(engine: Engine, existing: dict[str, Any], name: str, description: str, definition: dict[str, Any]) -> str:
    body = {"name": name, "description": description, "definition": definition}
    if name in existing:
        return existing[name]["tool_uuid"]
    return engine("POST", "/tools/", body)["tool_uuid"]


def ensure_tools(engine: Engine, hooks: str, credential: str) -> dict[str, str]:
    existing = {t["name"]: t for t in engine("GET", "/tools/")}
    uuids = {}
    for spec in TOOLS:
        uuids[spec["name"]] = ensure_tool(
            engine, existing, spec["name"], spec["description"],
            {"type": "http_api", "config": {
                "method": "POST",
                "url": f"{hooks}/tools/{spec['name']}",
                "credential_uuid": credential,
                "parameters": [_param(p) for p in spec["parameters"]],
                "preset_parameters": _preset(),
                "timeout_ms": 10000,
            }},
        )
    uuids["transfer_to_human"] = ensure_tool(
        engine, existing, "transfer_to_human", "Transfer the call to a person on the collections team.",
        {"type": "transfer_call", "config": {
            "destination_source": "dynamic",
            "destination": "",
            "timeout": 30,
            "resolver": {
                "type": "http",
                "url": f"{hooks}/transfer",
                "credential_uuid": credential,
                "timeout_ms": 5000,
                "wait_message": "One moment, I'm connecting you to a colleague.",
                "parameters": [{"name": "reason", "type": "string", "required": False,
                                "description": "Why the caller needs a person."}],
                "preset_parameters": _preset(),
            },
        }},
    )
    return uuids


def knowledge_documents(engine: Engine) -> list[str]:
    """Every ready knowledge-base document (scripts/voice_studio_kb_import.py)."""
    docs = engine("GET", "/knowledge-base/documents?limit=100")["documents"]
    return [d["document_uuid"] for d in docs if d.get("processing_status") == "completed"]


def build_definition(
    tools: dict[str, str], hooks: str, credential: str, trigger_path: str, documents: list[str],
    channel: str = "outbound",
) -> dict[str, Any]:
    outbound_tools = {
        "start": [],
        "verify": ["verify_identity", "transfer_to_human"],
        "position": ["account_position", "flag_dispute", "transfer_to_human"],
        "resolve": ["promise_to_pay", "request_callback", "flag_dispute", "transfer_to_human"],
    }
    inbound_tools = {
        "start": ["transfer_to_human"], "general": ["transfer_to_human"],
        "verify": ["verify_identity", "transfer_to_human"],
        "help": ["account_position", "promise_to_pay", "request_callback", "flag_dispute", "transfer_to_human"],
    }
    whatsapp_tools = {
        "start": ["transfer_to_human"], "verify": ["verify_identity", "transfer_to_human"],
        "help": ["account_position", "promise_to_pay", "request_callback", "flag_dispute", "transfer_to_human"],
    }
    specs = {
        "outbound": (NODES, EDGES, GLOBAL_PROMPT, outbound_tools),
        "inbound": (INBOUND_NODES, INBOUND_EDGES, INBOUND_GLOBAL_PROMPT, inbound_tools),
        "whatsapp": (WHATSAPP_NODES, WHATSAPP_EDGES, WHATSAPP_GLOBAL_PROMPT, whatsapp_tools),
    }
    spec_nodes, spec_edges, global_prompt, node_tools = specs[channel]
    kinds = {"start": "startCall", "end_done": "endCall", "end_failed": "endCall",
             "end_unverified": "endCall", "end_wrong": "endCall"}
    nodes = [{
        "id": "global", "type": "globalNode", "position": {"x": 0, "y": -220},
        "data": {"name": "Persona and rules", "prompt": global_prompt},
    }]
    for i, (key, node) in enumerate(spec_nodes.items()):
        data: dict[str, Any] = {"name": node["name"], "prompt": node["prompt"], "add_global_prompt": True}
        if key in node_tools:
            data["tool_uuids"] = [tools[t] for t in node_tools[key]]
        kb_nodes = {"outbound": ("position", "resolve"), "inbound": ("general", "help"),
                    "whatsapp": ("help",)}[channel]
        if key in kb_nodes and documents:
            # Product questions come up once the account is open; answered
            # from the knowledge base, never before verification.
            data["document_uuids"] = documents
        if key == "start" and channel == "inbound":
            data.update({
                "pre_call_fetch_mode": "inbound",
                "pre_call_fetch_url": f"{hooks}/precall",
                "pre_call_fetch_credential_uuid": credential,
            })
        nodes.append({"id": key, "type": kinds.get(key, "agentNode"),
                      "position": {"x": 320 * (i % 4), "y": 200 * (i // 4)}, "data": data})
    nodes.append({"id": "trigger", "type": "trigger", "position": {"x": -320, "y": 0},
                  "data": {"name": "API trigger", "trigger_path": trigger_path, "enabled": True}})
    nodes.append({"id": "webhook", "type": "webhook", "position": {"x": -320, "y": 220},
                  "data": {"name": "PayInt: file the call", "enabled": True, "http_method": "POST",
                           "endpoint_url": f"{hooks}/run-completed", "credential_uuid": credential,
                           "payload_template": {"workflow_run_id": "{{workflow_run_id}}",
                                                "workflow_id": "{{workflow_id}}",
                                                "recording_url": "{{recording_url}}"}}})
    edges = [{"id": f"e-{a}-{b}", "source": a, "target": b,
              "data": {"label": label, "condition": cond, "allow_failed_action": b == "end_failed"}}
             for a, b, label, cond in spec_edges]
    return {"nodes": nodes, "edges": edges}


def ensure_agent(engine: Engine, tools: dict[str, str], hooks: str, credential: str,
                 *, name: str = AGENT_NAME, channel: str = "outbound") -> tuple[int, str]:
    documents = knowledge_documents(engine)
    listed = engine("GET", "/workflow/fetch?status=active")
    listed = listed if isinstance(listed, list) else [listed]
    match = next((w for w in listed if w.get("name") == name), None)
    trigger_path = uuid.uuid4().hex
    if match:
        full = engine("GET", f"/workflow/fetch/{match['id']}")
        for node in (full.get("workflow_definition") or {}).get("nodes", []):
            if node.get("type") == "trigger" and node.get("data", {}).get("trigger_path"):
                trigger_path = node["data"]["trigger_path"]
        # Published definitions are operator-owned; never replace or republish.
        return int(match["id"]), trigger_path
    definition = build_definition(tools, hooks, credential, trigger_path, documents, channel)
    created = engine("POST", "/workflow/create/definition", {"name": name, "workflow_definition": definition})
    return int(created["id"]), trigger_path


def write_env(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pattern = re.compile(rf"^{re.escape(key)}=")
    lines = [ln for ln in lines if not pattern.match(ln)] + [f"{key}={value}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_api_key(engine: Engine, env_file: Path) -> None:
    current = env_str("VOICE_STUDIO_API_KEY")
    keys = engine("GET", "/user/api-keys") or []
    if current and any(current.startswith(k.get("key_prefix", "~")) and k.get("is_active") for k in keys):
        print("api key: present")
        return
    created = engine("POST", "/user/api-keys", {"name": API_KEY_NAME})
    write_env(env_file, "VOICE_STUDIO_API_KEY", created["api_key"])
    os.environ["VOICE_STUDIO_API_KEY"] = created["api_key"]
    print(f"api key: created, written to {env_file} (restart the api to load it)")


def ensure_telephony(engine: Engine) -> None:
    sid, token, number = env_str("TWILIO_ACCOUNT_SID"), env_str("TWILIO_AUTH_TOKEN"), env_str("TWILIO_PHONE_NUMBER")
    if not (sid and token and number):
        print("telephony: TWILIO_* not set, skipped")
        return
    configs = engine("GET", "/organizations/telephony-configs") or {}
    configs = configs.get("configurations", configs) if isinstance(configs, dict) else configs
    match = next((c for c in configs if c.get("name") == TELEPHONY_NAME), None)
    body = {"name": TELEPHONY_NAME, "is_default_outbound": True,
            "config": {"provider": "twilio", "account_sid": sid, "auth_token": token}}
    config_id = match["id"] if match else engine("POST", "/organizations/telephony-configs", body)["id"]
    numbers = engine("GET", f"/organizations/telephony-configs/{config_id}/phone-numbers") or {}
    numbers = numbers.get("phone_numbers", numbers) if isinstance(numbers, dict) else numbers
    row = next((n for n in numbers if (n.get("address") or "").replace(" ", "") == number), None)
    if row is None:
        engine("POST", f"/organizations/telephony-configs/{config_id}/phone-numbers", {
            "address": number, "label": "PayInt caller id", "is_default_caller_id": True,
        })
    print(f"telephony: twilio config {config_id} ready; inbound routing unchanged")


def missing_bindings(wanted: list[str]) -> list[str]:
    import db

    with db.engine.connect() as conn:
        have = {r[0] for r in conn.execute(text(
            "SELECT objective FROM voice_studio_agents WHERE tenant_id = :t"
        ), {"t": db.current_tenant()})}
    return [o for o in wanted if o not in have]


def bind(workflow_id: int, objectives: list[str], actor: str, *, create: bool) -> None:
    """Report missing bindings; with create, add them through the audited routing path."""
    import voice_studio_routing

    for objective in missing_bindings(objectives):
        channel = "whatsapp" if objective == "whatsapp" else "outbound"
        if not create:
            print(f"binding missing: {objective} (activate it in Voice Studio routing, or rerun with --create-bindings)")
            continue
        voice_studio_routing.assign(workflow_id, channel, objective=objective, actor=actor)
        print(f"binding created and audited: {objective} -> engine agent {workflow_id}")


def validate_tools(engine: Engine, tools: dict[str, str], credential: str) -> None:
    """Fail loudly if any approved tool no longer matches its approved shape."""
    import voice_studio_routing

    active = {str(t["tool_uuid"]): t for t in engine("GET", "/tools/?status=active")}
    problems = []
    for name, tool_uuid in tools.items():
        tool = active.get(tool_uuid)
        if tool is None:
            problems.append(f"{name}: not active")
            continue
        problems += [f"{name}: {e}" for e in voice_studio_routing._check_tool(tool, credential)]
    if problems:
        sys.exit("approved tools failed validation:\n  " + "\n  ".join(problems))
    print(f"tools validated: {', '.join(tools)}")


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--actor", required=True, help="users.id recorded as the engine user")
    parser.add_argument("--hooks-url", default=env_str("VOICE_STUDIO_HOOKS_URL", "http://api:8000/voice-studio/hooks"),
                        help="where the engine reaches our hooks")
    parser.add_argument("--objectives", default="dpd_reminder,promise_followup,broken_promise",
                        help="comma-separated outbound objectives given a binding when missing")
    parser.add_argument("--env-file", default="/app/.env", help="where to store VOICE_STUDIO_API_KEY")
    parser.add_argument("--route-inbound", action="store_true",
                        help="retired: use the audited Voice Studio routing screen")
    parser.add_argument("--create-bindings", action="store_true",
                        help="create missing outbound/WhatsApp bindings (preflighted and audited)")
    args = parser.parse_args()
    if args.route_inbound:
        parser.error("--route-inbound no longer changes live routing; use Voice Studio routing after publishing")

    token = env_str("VOICE_STUDIO_HOOK_TOKEN")
    if not token:
        sys.exit("VOICE_STUDIO_HOOK_TOKEN is not set")
    engine = Engine(args.actor)
    hooks = args.hooks_url.rstrip("/")
    credential = ensure_credential(engine, token)
    tools = ensure_tools(engine, hooks, credential)
    validate_tools(engine, tools, credential)
    workflow_id, _ = ensure_agent(engine, tools, hooks, credential)
    inbound_id, _ = ensure_agent(engine, tools, hooks, credential, name=INBOUND_AGENT_NAME, channel="inbound")
    whatsapp_id, _ = ensure_agent(engine, tools, hooks, credential,
                                  name=WHATSAPP_AGENT_NAME, channel="whatsapp")
    print(f"agents: outbound={workflow_id}, inbound={inbound_id}, whatsapp={whatsapp_id}; existing definitions unchanged")
    import voice_studio_routing

    active_tools = {str(t["tool_uuid"]): t for t in engine("GET", "/tools/?status=active")}
    for channel, agent_id in (("outbound", workflow_id), ("inbound", inbound_id), ("whatsapp", whatsapp_id)):
        versions = engine("GET", f"/workflow/{agent_id}/versions") or []
        published = next((v for v in versions if v.get("status") == "published"), None)
        if not published:
            sys.exit(f"{channel} agent {agent_id} has no published definition; review it in Voice Studio")
        checked = voice_studio_routing.validate_definition(
            published.get("workflow_json") or {}, channel=channel,
            active_tools=active_tools, credential_uuid=credential,
        )
        if not checked["ok"]:
            sys.exit(f"{channel} agent {agent_id} failed routing preflight: {'; '.join(checked['errors'])}")
        print(f"{channel}: published definition {published['id']} preflight passed")
        for warning in checked["warnings"]:
            print(f"{channel}: review before routing: {warning}")
    ensure_api_key(engine, Path(args.env_file))
    ensure_telephony(engine)
    bind(workflow_id, ["*"] + [o.strip() for o in args.objectives.split(",") if o.strip()],
         args.actor, create=args.create_bindings)
    bind(whatsapp_id, ["whatsapp"], args.actor, create=args.create_bindings)
    print("inbound phone routing is set only on the Voice Studio routing screen")


if __name__ == "__main__":
    main()
