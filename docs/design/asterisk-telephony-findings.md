# Asterisk telephony: test findings (17 Sep 2026)

Findings from end-to-end tests of the Asterisk implementation described in
[`enterprise-sip-telephony.md`](enterprise-sip-telephony.md) and
[`enterprise-sip-telephony-research.md`](enterprise-sip-telephony-research.md).

**Status (18 Sep 2026): fixed, proven by real calls, and deployed to the laptop
stack.** Migrations `0146`-`0149` are applied, `.env` carries the telephony
credentials, and `collections_asterisk` + `collections_asterisk_controller` are
running the new code. What is still unproven is listed at the end. Each finding below is
marked with what happened to it. The call path is now
SIP → `Stasis(habibi)` → `voice/asterisk_controller.py`, which owns the call: the
bot's media leg, the bridge, the recording, transfer, and the attempt's final
state. A committed e2e harness (`backend/tests/e2e_telephony`, scripted SIP
phones) places real calls through the bot; all ten scenarios pass.

The findings are kept as written, because they say why each fix exists.

## How it was tested

- Test phone: a second Asterisk container (same image) registering as `1001`.
  It played a scripted borrower, synthesized with Windows SAPI: speech, a DTMF
  `1`, silence, and "I want to speak to a human". Both audio legs were recorded
  separately.
- Scratch PBX and scratch voice container on `backend_default`, with each fix
  applied one at a time so every failure could be attributed.
- 11 calls:
  - inbound
  - warm-up and warm-latency calls
  - barge-in plus transfer request
  - silent caller
  - outbound through the real `outbound.reserve` → `outbound.place`
  - busy callee
  - a non-existent extension
  - 3 concurrent calls
- Evidence from:
  - SIP traces (`pjsip set logger on`)
  - `chan_websocket` / `res_websocket_client` debug logs
  - voice logs
  - `call_attempts`, `interactions`, `interaction_media` and `voice_sessions` rows
  - the RTP counters (`pjsip show channelstats`)
  - a transcription of what the caller heard

Each finding is marked **Verified** (reproduced on a call or in isolation) or
**Code-read** (read in the code, not run).

---

## Blockers: no call works today

### B1. `websocket_client.conf` has an invalid `connection_type`: Verified

> **Outcome:** Fixed. `connection_type = per_call_config`, rendered by `telephony/render_config.py`; `test_render_config` pins it.
- `telephony/asterisk/websocket_client.conf` sets `connection_type = per_call`.
  Valid values are `persistent` and `per_call_config`.
- Asterisk has refused the `habibi_bot` object on every start since 09:30:
  `Error parsing connection_type=per_call` → `Could not create an object of type 'websocket_client' with id 'habibi_bot'`.
- Every call fails with `WebSocket client connection 'habibi_bot' not found` and hangs up.
- The design doc (§4b) already had the correct value.

### B2. The voice `/ws/asterisk` routes reject every connection with 403: Verified

> **Outcome:** Fixed. `WebSocket` is imported at module level in `voice/asterisk_ws.py`; `test_asterisk_ws_route` connects over the real route.
- `voice/asterisk_ws.py` declares both handlers with `websocket: Any`, so FastAPI
  treats `websocket` as a required **query parameter** and closes with 1008:
  `{'type': 'missing', 'loc': ['query', 'websocket']}`.
- The module has `from __future__ import annotations`, so the annotation is a
  string. A `WebSocket` import *inside* the function still fails (verified).
  The type must be imported at module level.
- The correct secret gets the same 403 as a wrong secret or a non-existent route.

### B3. `AsteriskFrameSerializer` is not a Pipecat `FrameSerializer`: Verified

> **Outcome:** Fixed. `AsteriskFrameSerializer` subclasses Pipecat's `FrameSerializer`, and a test builds the transport.
- `FastAPIWebsocketParams` validates the type:
  `ValidationError: serializer — Input should be an instance of FrameSerializer`.
- Every call crashes while building the transport.
- `voice/asterisk_serializer.py` defers the Pipecat import on purpose, so the
  class can't subclass it as written.

### B4. The softphone cannot register, even with correct credentials: Verified

> **Outcome:** Fixed. pjsip sections are named by extension; both e2e phones register.
- `REGISTER` from `1001` / `habibi123` → `AOR '' not found for endpoint 'softphone'`.
  Authentication succeeds, but the registrar looks up an AOR named after the
  To-URI user (`1001`), and the AOR is named `softphone`.
- Renaming the endpoint, auth and AOR sections to `1001` fixed it
  (`Registered`, contact `Avail` 2.7 ms).
- Knock-on effects:
  - The `username` identifier matches the endpoint *name*, so it never matched `1001`.
  - `identify_by=username,auth_username` excludes `ip`, so the
    `softphone-identify` match ranges are never used.
- The earlier Zoiper failures (`sip:1001%40192.168.137.1@…`, username field
  containing `1001@192.168.137.1`) are a second, phone-side problem on top of this.

### B5. Outbound dial to the softphone cannot be created: Verified

> **Outcome:** Fixed by the same rename; outbound e2e calls dial `PJSIP/1001`.
- `asterisk_ops._endpoint_for("1001")` → `PJSIP/1001` → ARI 500
  `Allocation failed`, logged as `Unable to create PJSIP channel - endpoint '1001' was not found`.
- `exten => 1001` in `extensions.conf` does not help: ARI originate names an
  endpoint, not a dialplan extension.
- Fixed by the same rename as B4.

---

## What worked once B1–B5 were patched

- **Inbound audio:** 16 kHz slin reached Azure STT and the borrower's words were
  transcribed correctly.
- **Outbound audio:** transcribing the caller's recorded "heard" leg gave the
  bot's exact sentences at the correct speed.
- **Hangup:** the bot's `HANGUP` command cleared the call (`Normal Clearing(16)`).
- **DTMF:** `DTMF_END` arrived, and `deserialize` returns `InputDTMFFrame` for
  `1`, `#` and `*` (but see F5).
- **Concurrency:** 3 simultaneous calls all completed; voice memory rose about 115 MB.
- **Bot recording and transcript:** the composite recording and the transcript
  export reached MinIO.

---

## Functional bugs

### F1. The bot never receives caller or attempt data: Verified

> **Outcome:** Fixed. Identity rides as `__HABIBI_CTX` on the caller's channel and is inherited onto the bot's leg through ARI `originator`. The outbound e2e call asserts the interaction is `outbound` and names the borrower.
- Actual `MEDIA_START` `channel_variables`:
  `{"DIALEDPEERNUMBER": "habibi_bot/c(slin16)f(json)", "MEDIA_WEBSOCKET_CONNECTION_ID": "habibi_bot", "MEDIA_WEBSOCKET_OPTIMAL_FRAME_SIZE": "640"}`.
- Three kinds of variable never reach it:
  - `Set(CALL_TYPE/FROM/TO)` in the dialplan
  - the ARI originate variables (`ATTEMPT_ID`, `customer_id`, `objective`)
  - `UNIQUEID`
- The cause: these are set on the SIP leg, and `Dial(WebSocket/...)` creates a
  new channel. Only `_`/`__`-prefixed variables are inherited.
- Results observed:
  - All 10 test calls were stored as `direction=inbound`,
    `customer_id=UNKNOWN-CALLER`, `handler_bot_id=intake-v1`.
  - The outbound `dpd_reminder` call ran `mission=inbound` with the intake
    greeting and no borrower context.

### F2. Outbound attempts never reach a terminal state: Verified

> **Outcome:** Fixed. The controller maps Q.850 causes to attempt states; e2e covers completed, busy, rejected and no-answer. It also retries a status write that beats the dialer's own commit -- that race is how a busy call stayed `dialing`.
- Nothing listens for Asterisk call events (no Stasis app, no AMI, no hangup
  handler), so `ringing`, `no_answer`, `busy`, `completed` and `failed` are never
  written.
- The one status write in `asterisk_ws.py` (`answered`) uses
  `call_data.call_id`, which is the **WebSocket** channel id (`1789661865.1`).
  The attempt stores the originated **SIP** channel id (`1789661865.0`), so the
  write matches nothing.
- Observed:
  - An answered, completed call stayed `dialing` 2+ minutes after hangup.
  - A busy callee (`SIP/2.0 486 Busy Here`) also stayed `dialing`.
- Consequences:
  - `call_closer` never scores the call.
  - Campaign targets and cadence never advance.
  - Attempts count against `OUTBOUND_MAX_IN_FLIGHT` until `sweep_stale` marks
    them `failed` (30 min).

### F3. Warm transfer cannot work: Verified

> **Outcome:** Fixed. The caller is a Stasis channel, so `continue` works; the e2e call rings agent 1002, which answers.
- `asterisk_ops.warm_transfer` calls ARI `POST /channels/{id}/continue`.
- It returns **409** for both the WebSocket leg and the SIP leg, because
  `continue` only works on channels inside a Stasis application, and calls here
  enter through the dialplan.
- `agent_core/live_qa/enact.py` and `voice/tools_closing.py` both route
  transfers here.
- Staging queue `collections-agents` has a single member, `PJSIP/softphone`,
  which is the caller's own phone.

### F4. The Asterisk-side (MixMonitor) recording is never ingested: Verified

> **Outcome:** Fixed. The controller records the bridge, downloads it over ARI and stores it as `sip_audio` keyed by the SIP leg. No shared volume, no MixMonitor.
- `ingest_mixmonitor` is called with `asterisk_uniqueid`, taken from
  `MEDIA_START`, which is the WebSocket channel's id.
  `mixmonitor ingest: no spool file for uniqueid=1789660855.5`, while
  `1789660855.4.wav` (the SIP leg) exists in the spool.
- `UNIQUEID` is never passed through either (see F1).

### F5. DTMF is dropped: Verified

> **Outcome:** Fixed, and the stated cause was wrong: `voice/ivr.py` already had the aggregator, behind `VOICE_DTMF_INPUT_ENABLED`, which defaulted off. It is on by default now, and the e2e call's keypress reaches the transcript.
- The serializer produces `InputDTMFFrame`, but nothing in `voice/` or
  `agent_core/` consumes `InputDTMFFrame`/`KeypadEntry`. Keypad input has no
  effect, on any provider.

### F6. The PBX sends no RTP while the bot is silent: Verified

> **Outcome:** Fixed. The mixing bridge keeps audio flowing; the silent-caller e2e asserts the transmit count rises while the bot says nothing.
- The PBX's transmit packet count stayed at 228 for 30 s while the bot was
  silent, and moved only when the bot spoke.
- `START_MEDIA_BUFFERING` is sent from `serialize()` only when a `StartFrame` is
  written, and the output transport never writes one, so it is never sent.
- Risk: SBC or carrier media-inactivity timers, and NAT pinhole expiry, can drop
  calls during long pauses.
- Caveat: the test phone also sends no RTP during `Wait()`, so the shortened
  recordings (24.8 s of audio for a 56 s call) are partly a test artefact.
  Re-check the recording length with Zoiper, which sends RTP continuously.

### F7. Answer-before-connect leaves dead air and empty recordings: Verified

> **Outcome:** Fixed. Nothing answers in the dialplan; the controller answers only once the bot's leg is up, and refuses the call (or sends it to an agent) when the bot cannot be reached.
- Both dialplan contexts run `Answer()` and `MixMonitor` **before**
  `Dial(WebSocket/...)`.
- When the bot is unreachable, the caller is answered, hears silence, and gets
  hung up with cause 3 / congestion. No announcement or fallback is played.
- Every failed call left a 44-byte empty WAV in the spool.

### F8. Every Asterisk call loses its `voice_sessions` row: Verified

> **Outcome:** Fixed by applying migration 0149; the e2e stack runs at head and asserts the `voice_sessions` row exists.
- `voice_sessions_transport_check` rejects `transport='asterisk'`, because
  migration `20260917_0149` is not applied.
- `persist.start_voice_call` logs the IntegrityError and continues without the
  row. The code shipped ahead of the migration with no fallback.

### F9. Background dialers run stale Twilio-only code: Verified

> **Outcome:** Fixed. `docker-compose.dev.yml` mounts the tree into `bot_worker`, and the telephony overlay sets the provider for api, voice, bot_worker and the controller from one anchor.
- `collections_bot_worker` runs a baked image with no `/app` bind mount:
  `ImportError: cannot import name 'telephony' from 'voice'`.
- It runs cadence, campaigns, bounce voice and treatment dials, so those still
  use the old Twilio-only `outbound.place`.
- Its environment has no `TELEPHONY_PROVIDER`, and
  `docker-compose.telephony.yml` only overrides `voice` and `api`, not
  `bot_worker`.

### F10. Operator and demo dialling require Twilio credentials: Code-read

> **Outcome:** Fixed. `voice/telephony.py` gained `configured()` and `preflight()`, the dial endpoints ask the seam, and the wire field is now `telephonyConfigured`.
- `POST /twilio/voice/outbound`, used by Customer 360 "Start call"
  (`Habibi/src/api/outbound.ts`), returns `503 twilio_not_configured` when
  `twilio_ops.configured()` is false, before reaching the provider seam.
- `POST /demo/outbound-call` has the same gate, and
  `GET /demo/outbound-call` reports `twilioConfigured`.
- An Asterisk-only (bank on-prem) deployment cannot dial from the UI.
- It works today only because Twilio credentials happen to be set.

### F11. Dial failures are not classified: Verified

> **Outcome:** Fixed. `AriError` carries the status and a clean message; the e2e case asserts the stored error holds no raw JSON.
- A non-existent extension becomes `state=failed`, `reason=dial_failed`, with a
  raw ARI JSON body in `provider_error`, never `invalid_number`.
- ARI errors are flattened to `RuntimeError` strings, so
  `_carrier_failure_reason` cannot tell a bad number from an unavailable PBX.

### F12. `outbound.reserve` alone leaves `account_id` empty on Asterisk test dials: Verified

> **Outcome:** Fixed. The account fallback moved from `gate` into `reserve`.
- A dial that bypasses `gate` (as `scripts/dial_test.py --dry-run`-style tooling
  does) has `accountId=None`. `gate` resolves it; `reserve` does not.
- Listed for completeness; production dials go through `gate`.

### F13. The API proxy route accepts first and fails upstream: Verified

> **Outcome:** Fixed by deletion. Asterisk reaches voice directly, so the API proxy routes and their authz entries are gone.
- `routers/telephony.py` `/ws/asterisk/{proxy_secret}` accepts the socket, then
  `proxy_voice_websocket` fails with the voice-side 403 (B2).
- Asterisk sees an open socket that closes with no media.

### F14. `scripts/dial_test.py` cannot test Asterisk: Code-read

> **Outcome:** Fixed. `_preflight()` delegates to `telephony.preflight()`.
- `_preflight()` checks only Twilio settings (`twilio_ops.configured`, status
  callback URL, media stream URL).
- It also tells the operator the states "arrive over the Twilio status
  callback", which is not true under Asterisk.

---

## Latency

Measured from the SIP answer to the bot's first audio:

| Scenario | First speech (before) | After |
|---|---|---|
| First call after the voice process starts | about 7.4–8.7 s | not re-measured; the prewarm in `voice/bot.py` already covers it |
| Warm process, single call | about 2.4 s | **1.3–2.1 s** |
| Warm process, 3 concurrent calls | 4.6–5.0 s | 4.9–5.8 s |

- Measured from the SIP answer to the bot's first audio, over the e2e calls.
- The improvement is F7, not a faster pipeline: the caller now hears **ringback**
  until the bot is on the socket, and the call is answered at that moment, so the
  silence after answer is what is left rather than the whole setup.
- The `voice.trace setup.vad elapsed_s` line still under-reports the model load.
  Left alone: it is a trace label, and the number that matters (answer to first
  speech) is now measured end to end by the harness.

---

## Security

### S1. The WebSocket secret leaks into logs: Verified

> **Outcome:** Fixed. The media socket uses HTTP Basic (`ASTERISK_WS_USER` / `ASTERISK_WS_PASSWORD`); no secret appears in a URL or a log.
- The secret is a URL path segment (`/ws/asterisk/<secret>`).
- It is printed on every call by the uvicorn access log
  (`"WebSocket /ws/asterisk/habibi-asterisk-ws" [accepted]`) and by the API
  proxy's ERROR log (`Voice WS proxy failed connecting to ws://voice:7860/ws/asterisk/<secret>`).
- The default secret in compose and the entrypoint is `habibi-asterisk-ws`.

### S2. ARI is open inside the network: Code-read + Verified

> **Outcome:** Fixed. ARI credentials are required env with no defaults, `allowed_origins` is gone, and 8088 stays unpublished.
- Credentials are `habibi`/`habibi` (plain), `allowed_origins = *`, and HTTP
  binds `0.0.0.0:8088`.
- Any container on `backend_default` can originate calls. That is toll-fraud
  exposure once a real trunk is attached.
- `/metrics` and `/media` are also served on that listener.

### S3. The identify ranges are broad: Code-read

> **Outcome:** Fixed. Phones are not identified by IP at all; only a trunk gets an identify, from `ASTERISK_TRUNK_MATCH`, and `0.0.0.0/0` is refused.
- `softphone-identify` matches `10.0.0.0/8`, `172.16.0.0/12` and `192.168.0.0/16`.
  It is inert today (see B4), but would match all of RFC1918 if `ip` were
  enabled.

### S4. `transport-tls` is bound on 5061 with no certificate: Verified

> **Outcome:** Fixed. The TLS transport is rendered only when both certificate files exist.
- It is listed in `pjsip show transports`, with `cert_file` and `priv_key_file`
  commented out.

---

## Production readiness gaps

These were found while testing and matter for the "pluggable, production-level"
goal: recordings, multiple numbers, bank trunks.

- **G1. No call control layer.** F1–F4 share one root cause: calls go
  dialplan → `Dial(WebSocket)`, so nothing Habibi owns controls the call's
  lifecycle. There is no place for:
  - status and hangup cause
  - transfer
  - carrying attempt and caller identity
  - recording control
  - a single call id mapping
- **G2. Recordings live on a shared Docker volume.**
  - `/var/spool/asterisk/monitor` only works when Asterisk and voice share a host.
  - File names are `UNIQUEID`, which is `epoch.seq` and can collide between two
    PBX nodes started in the same second.
  - There is no retention, integrity or immutability (CBUAE 5-year).
- **G3. CDRs are not written.**
  - `cdr_csv.c: Unable to open file /var/log/asterisk//cdr-csv//Master.csv`,
    because the directory is missing.
  - There is no CDR to reconcile billing or carrier minutes.
- **G4. Number pools are not proven.**
  - `place()` passes the pool number as ARI `callerId`.
  - For a trunk, CLI also needs `P-Asserted-Identity` / `send_pai` /
    `trust_id_outbound` on the trunk endpoint, and none of these are configured.
  - Not tested: the test attempt had no pool.
- **G5. The trunk is a placeholder.** `bank-sbc` has `contact=sip:127.0.0.1:5060`
  (Asterisk itself) and `context=from-internal`, the same context as the
  softphone. Setting `ASTERISK_TRUNK_ENDPOINT=bank-sbc` would dial the PBX itself.
- **G6. The media inactivity risk** from F6 applies to real trunks and SBCs.
- **G7. No Asterisk health signal for dialling.** The container healthcheck only
  runs `core show version`. It stayed "healthy" while `habibi_bot` was missing
  and no call could connect.
- **G8. The tests do not cover the integration.** All 12 Asterisk unit tests
  pass while every call path is broken:
  - `test_asterisk_serializer` never builds a transport.
  - Nothing tests the route.
  - `test_bot_flow_asterisk` asserts on source text.
  - A DTMF assertion ends in `or True`.

---

## Laptop / Zoiper staging path

- **L1. `ASTERISK_EXTERNAL_IP` is hard-coded.** It is `192.168.137.1` (the
  hotspot), baked into SDP at container start. The hotspot adapter is currently
  down (Wi-Fi is `192.168.88.9`), and any IP change needs a container restart.
  Verified.
- **L2. The relay works from the host.** SIP OPTIONS and REGISTER through
  `192.168.88.9:5060` reach the live PBX (401 challenge in 67 ms). UDP to a
  `0.0.0.0`-published port via the LAN IP reaches containers (seen as
  `172.17.0.1`). Verified from the host only.
- **L3. Firewall rules cover only the Public profile.** The inbound allow rules
  for the relay's `python.exe` and Docker Desktop are Public-profile only, and
  the Wi-Fi network is **Private**. A phone reaching the laptop over that Wi-Fi
  would be blocked. Verified (rule inspection).
- **L4. The relay supports one phone.** Its UDP side replies to whichever client
  sent last. It also drops packets from `127.0.0.1`, so a softphone on the
  laptop itself must use `127.0.0.1:15060` directly. Code-read.
- **L5. The Zoiper username field** held `1001@192.168.137.1` in earlier
  attempts (`From: sip:1001%40192.168.137.1@…`). It should be `1001`, with the
  domain `192.168.137.1`. Verified from logs.

---

## Observed on these calls but not telephony-specific

- **N1. High LLM usage.** A 54 s call with 4 caller turns used 35 LLM turns and
  82,824 prompt tokens (`voice call usage`).
- **N2. Teardown error.** `policy_rules:resolve` logs
  `ResourceClosedError: This Connection is closed` at teardown.
- **N3. Opening speech is lost.** Speech during the bot's opening turn is
  dropped: the user aggregator is muted until the greeting ends.
- **N4. Close errors after hangup.** Pipecat logs
  `exception while closing the websocket: Cannot call "send" once a close message has been sent`
  after a remote hangup.
- **N5. Zero-edge flow graph.** `authored flow has zero compiled edges ·
  nodes=30` is logged on every call.
- **N6. Transfer request not acted on.** In the "I want to speak to a human"
  call, `escalate_to_human` was not called, `capture_call_goal` returned
  `ok=0 error=failed`, and the bot then stayed silent for 30 s.

---

## Outcomes for the G, L and N items

**Production gaps**

| Item | Outcome |
|---|---|
| G1 no call control | Fixed. `voice/asterisk_controller.py` owns every call over ARI; F1-F4 followed from it. |
| G2 recordings on a shared volume | Fixed. The bridge recording is downloaded over ARI and stored as `sip_audio` under the interaction. No volume, no `UNIQUEID` filenames. Retention and object-lock remain later work. |
| G3 no CDRs | Fixed. The image creates `/var/log/asterisk/cdr-csv` (and the ARI recording spool, whose absence made `record` answer 500). |
| G4 number pools unproven | Partly. The trunk is rendered with `send_pai` / `trust_id_outbound` so a pool CLI is asserted to the carrier; with no trunk to dial, still unproven. |
| G5 placeholder trunk | Fixed. Nothing is rendered without `ASTERISK_TRUNK_HOST`; no `bank-sbc` pointing at Asterisk itself. |
| G6 media inactivity | Fixed for the bot's own silence (F6). A carrier's inactivity timer is still untested. |
| G7 no health signal | Fixed. The controller's `/health` is 503 until the ARI app is connected and Asterisk has loaded the bot's `websocket_client`, and it is the compose healthcheck. |
| G8 tests did not cover the integration | Fixed. `tests/e2e_telephony` places real SIP calls; the source-pinning test is deleted and the `or True` assertion is gone. |

**Laptop / Zoiper**

| Item | Outcome |
|---|---|
| L1 hard-coded external IP | Documented. Still env (`ASTERISK_EXTERNAL_IP`) and still needs a restart to change; the relay now prints the addresses to choose from. |
| L2 relay works | Unchanged, still true. |
| L3 firewall profile | Documented in `backend/telephony/README.md`, with the rule to add. Not changed for you: it is a system setting. |
| L4 one phone only | Fixed. The relay keeps one upstream socket per phone. |
| L5 Zoiper username | Documented: the extension only, and skip the wizard's auto-detect. |

**Seen on the calls, not telephony**

| Item | Outcome |
|---|---|
| N1 usage counted ~7x | Fixed. The metrics observer counts each frame once; a test pushes one frame through seven hops. Historical `usage_events` rows stay inflated -- no backfill. |
| N2 closed connection at teardown | Fixed at the root: `live_qa/scorecard.py` read the calling window after its `with` block closed, so QA's hours-breach check could never fire. |
| N3 opening speech dropped | Fixed. `voice/greeting_hold.py` holds what the caller says during the greeting and replays it as one turn; the e2e barge-in call asserts it reaches the transcript. |
| N4 close errors after hangup | Fixed. The serializer sends no HANGUP once Asterisk has hung up. |
| N5 zero-edge flow warning | Downgraded to INFO: that graph is tool-driven by design, and publish-time gates already check reachability. |
| N6 transfer request ignored | Fixed. `capture_call_goal` sends an escalation intent to `escalate_to_human` instead of asking the caller what they need, and "speak to a human" now classifies as escalation. |

## Found while deploying it (18 Sep)

Two more of the same shape as the findings above, caught by running the fixed
stack rather than a fresh one:

- **The image's `mkdir` was masked by a volume.** The base image declares
  `/var/spool/asterisk` and `/var/log/asterisk` as volumes, and Docker carries an
  anonymous volume over when a container is recreated. The recording directory
  created at build time therefore did not exist in the running container and ARI
  `bridges/{id}/record` answered **500** on the live stack while passing on the
  fresh e2e one. The entrypoint now creates both directories at every start.
- **`asterisk_controller` had no bind mount.** It ran the baked api image and
  crash-looped on `No module named voice.asterisk_controller` -- exactly F9 in a
  new service. `docker-compose.dev.yml` now mounts the tree into it too; a real
  deployment needs the module in the image instead.
- **A dial that failed before the carrier kept `provider = twilio`** (the column
  default), because only `_mark_dialing` set it. `outbound.fail` now stamps the
  provider, so an Asterisk deployment's failures do not read as Twilio's.

## Known flake

The scenarios that assert on what the bot heard (inbound speech, the transfer
request) depend on real-time audio and Azure STT. Run alongside the full backend
suite on this laptop, one call in five arrives with the speech missing from the
transcript while DTMF and the recording still land. Run them on a quiet machine;
if it recurs when nothing else is running, it is worth a real investigation.

## Still not proven

- **A real phone's media through the hotspot** -- the one thing that needs your
  handset. The e2e phones speak SIP and RTP, but they are containers on the
  Docker network, so Zoiper over the relay is still untested end to end.
- SIP TLS / SRTP, and a real bank SBC trunk.
- `MEDIA_XOFF` / `MEDIA_XON` flow control (Asterisk never asked for it).
- Number-pool caller ID on a trunk.
- Behaviour when voice admission (20 slots) is full.
- Supervisor listen/barge on Asterisk calls.
- Outbound IVR traversal: Pipecat emits `OutputDTMFFrame` and `chan_websocket`
  has no command for it; it needs ARI `/channels/{id}/dtmf` on the SIP leg.

## Test data left behind

- `call_attempts` (source `asterisk_e2e_test`): `CA-5E1ECD197DD7` (canceled),
  `CA-382E0A8BB661` (canceled), `CA-CFE9141943FB` (failed).
- From the 18 Sep deployment smoke test, in the dev database, tagged
  `context.source = "telephony_e2e"`: four attempts (completed, busy, and two
  failed unroutable dials) and their interactions. All terminal; nothing is
  holding a fleet slot.
- `interactions`: 10 test calls on 17 Sep 2026 between 16:00 and 16:26 UTC, all
  `UNKNOWN-CALLER` / `intake-v1`, including `CL-1DDB09E7DC`, `CL-BDB3E2CB3B`,
  `CL-DC2286B2E7`, `CL-A6436AA116` and `CL-3FA95FB6ED`.
- Their recordings and transcripts in MinIO, and test WAVs in the
  `backend_asterisk_monitor` volume.
- The scratch containers, the copied env file and the live PBX debug logging
  were removed.

The fix work (18 Sep) ran entirely against a **separate** database,
`collections_telephony_e2e` (a dump/restore of dev, migrated to head), and
throwaway `e2e_*` containers with no published ports. The dev database only
carries the rows listed above; the e2e rows are all tagged
`context.source = "telephony_e2e"` in the copy.
