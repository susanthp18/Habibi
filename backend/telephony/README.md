# Telephony (Asterisk)

Habibi's on-prem PSTN path: Asterisk behind the bank's SBC, the bot reached over
`chan_websocket`. Design: [`docs/design/enterprise-sip-telephony.md`](../../docs/design/enterprise-sip-telephony.md).
What broke before this was proven end to end:
[`docs/design/asterisk-telephony-findings.md`](../../docs/design/asterisk-telephony-findings.md).

## How a call works

```
softphone / SBC ──SIP──► Asterisk ──Stasis(habibi)──► asterisk_controller (ARI)
                             │                          ├─ Local/bot@to-bot ──► Dial(WebSocket/habibi_bot)
                             │                          ├─ mixing bridge + bridge recording
                             └── WebSocket ─────────────┴─► voice  /ws/asterisk  → Pipecat bot
```

- **The controller owns the call** (`backend/voice/asterisk_controller.py`), one
  process per PBX: it answers only once the bot's leg is up, bridges the two,
  records the bridge, turns the hangup cause into the attempt's final state, and
  performs warm transfers.
- **One id everywhere.** The SIP channel id is `call_attempts.provider_call_id`,
  `voice_sessions.provider_call_id`, the transfer target and the recording name.
  An outbound leg is created as `att-<attempt id>`.
- **Identity** travels in one inherited channel variable, `__HABIBI_CTX`, so the
  bot knows the borrower, the attempt and the objective.
- **Config is rendered from env** by `render_config.py`. A bank cutover sets
  `ASTERISK_TRUNK_*` and changes no code. See `.env.example`.

## Laptop staging with a softphone

1. **Set the env** (`backend/.env`): `ASTERISK_ARI_USER/PASSWORD`,
   `ASTERISK_WS_USER/PASSWORD`, `ASTERISK_SOFTPHONES=1001:<pw>,1002:<pw>`,
   `ASTERISK_AGENT_EXTENSIONS=1002`, and `ASTERISK_EXTERNAL_IP` set to the
   address of the adapter the phone uses (the hotspot IP, not the Docker one).
   Asterisk refuses to start if the credentials are missing.
2. **Start the stack:**
   ```
   docker compose -f docker-compose.yml -f docker-compose.dev.yml \
     -f docker-compose.telephony.yml up -d asterisk asterisk_controller voice api bot_worker
   ```
   `asterisk_controller` is only healthy once the ARI app is connected *and*
   Asterisk has loaded the bot's `websocket_client`.
3. **Run the relay** (Windows + Docker Desktop only): `python telephony/sip_lan_relay.py`.
   Docker Desktop will not deliver LAN SIP into a container, so SIP is published
   on localhost and this forwards `0.0.0.0:5060` to it. It prints the addresses a
   phone can use. Leave it running.
4. **Windows Firewall:** inbound UDP 5060 must be allowed for the python.exe
   running the relay, on the profile of the network the phone is on. A laptop
   hotspot is usually **Public**, office Wi-Fi **Private**, and the rules that
   exist may cover only one of them:
   ```powershell
   New-NetFirewallRule -DisplayName "Habibi SIP relay" -Direction Inbound `
     -Program "C:\path\to\python.exe" -Protocol UDP -LocalPort 5060 `
     -Profile Any -Action Allow
   ```
5. **Zoiper:** skip the wizard's auto-detect (its probes are not SIP and Asterisk
   drops them, so every transport shows red). Use *Finish* and edit the account:
   - **Username:** `1001` — the extension only, never `1001@host`
   - **Password:** the one in `ASTERISK_SOFTPHONES`
   - **Domain / host:** the laptop address from step 1, port 5060, transport UDP
   - **STUN:** off
   Wait for *Registered*, then dial `1000` to reach the bot.

## Tests

- Unit: `tests/test_asterisk_*.py`, `tests/test_render_config.py`,
  `tests/test_telephony_provider.py`.
- End to end, real SIP calls through scripted phones — inbound, outbound, busy,
  rejected, no-answer, unroutable, DTMF, silence, transfer, concurrency:
  ```
  docker compose -f docker-compose.yml -f docker-compose.dev.yml \
    -f docker-compose.telephony.yml -f docker-compose.telephony-e2e.yml up -d
  # then, on the same network, with TELEPHONY_E2E=1:
  python -m pytest tests/e2e_telephony
  ```
  It places real calls through the real bot and models: see
  `tests/e2e_telephony/conftest.py`.
- Run it against an isolated stack and a **copy** of the database (the dev one is
  behind head), and not while the full backend suite is running: the scenarios
  that assert on what the bot heard depend on real-time audio, and under that
  load one call in five loses a transcript.

## Not yet proven

- SIP TLS / SRTP, and a real bank SBC trunk (config is rendered, never dialled).
- Number-pool caller ID over a trunk (`send_pai` is set; no trunk to test on).
- Outbound IVR traversal: Pipecat emits `OutputDTMFFrame`, and `chan_websocket`
  has no command for it — it would need ARI `/channels/{id}/dtmf` on the SIP leg.
