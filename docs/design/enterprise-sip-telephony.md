# Enterprise SIP Telephony: Self-Hosted, Multi-Country Blueprint

How Habibi takes and places real phone calls for BFSI clients in **India, the UAE/GCC and the USA** without routing borrower audio through a US-hosted CPaaS. One gateway design for every country; what changes per country is the carrier, the region the stack runs in, and the contact-policy rule pack.

> **Status:** implemented and proven by real SIP calls, 18 Sep 2026 — see [`asterisk-telephony-findings.md`](asterisk-telephony-findings.md) for what the first build got wrong and `backend/telephony/README.md` for how to run it. Revised 2026-09-17 after research. Supersedes the earlier LiveKit-SIP draft (see §11 for what was wrong in it). Implementation notes and the staging-vs-bank split live in [`enterprise-sip-telephony-research.md`](enterprise-sip-telephony-research.md).

---

## 1. Decision

**Asterisk (open source, GPLv2) as the SIP gateway, connected to the Pipecat bot through Asterisk's WebSocket channel driver (`chan_websocket`).**

```
Local licensed carrier ──► Bank's SBC ──────────────────► Asterisk ────────────────► Habibi voice bot (Pipecat)
 India: Airtel/Tata/Jio    Cisco CUBE / AudioCodes /      SIP + RTP in,             WebSocket, 8 kHz ulaw/slin
 UAE:   e& or du only      Oracle — the bank owns it      one container             same pipeline as today
 USA:   STIR/SHAKEN carrier
```

Plain terms:
- **SIP trunk** — a phone line delivered over IP by a telco.
- **SBC (Session Border Controller)** — the bank's firewall for phone traffic. It already exists in every bank contact centre; we sit behind it.
- **Asterisk** — answers/places the call, handles transfer, recording and keypad input, and streams the audio to our bot over a WebSocket.

### Why Asterisk

1. **Fits the code we already have.** `voice/bot.py` already runs phone calls as *WebSocket + frame serializer* (Twilio/Telnyx/Plivo/Exotel via `FastAPIWebsocketParams`). Asterisk is one more serializer, not a new transport model.
2. **The WebSocket driver does what a voice agent needs.** Available in Asterisk 20.16, 21.11, 22.6 and 23.0+. **Pin 22.8+** so JSON control (`f(json)`) is the preferred format (20.18 / 22.8 / 23.2). Asterisk owns the playout clock and frames the audio for us; `FLUSH_MEDIA` cuts playback instantly on barge-in; `DTMF_END` delivers keypad digits; `HANGUP` ends the call; `MEDIA_XOFF`/`MEDIA_XON` give flow control; the client connection supports TLS.
3. **Collections needs contact-centre features that are Twilio-only in our code today** — warm transfer into a human agent queue, on-prem SIP recording, outbound dialling via ARI. Answering-machine detection stays **in-band ML** (`voice/amd.py`); do not enable Asterisk `AMD()`.
4. **Bank telecom teams know it**, it is one container, and it needs no SFU or Redis.

### Options considered

| Option | Verdict | Why |
|---|---|---|
| **Asterisk + `chan_websocket`** | **Chosen** | See above. Cost: the community Pipecat integration is young, so we own the serializer (§5). |
| LiveKit SIP + LiveKit server + Redis | Runner-up | Solid (TLS/SRTP, REFER transfer, Apache-2.0), but three extra services, host networking, a SIP→WebRTC→bot transcode hop, cold transfer only, no agent queue. |
| jambonz | Rejected | Self-hosting needs a paid licence since Jan 2026 ($7/session or $2,000/month). |
| FreeSWITCH + `mod_audio_stream` | Workable, worse | Prebuilt packages need a SignalWire account token; the streaming module is third-party. |
| Flowcat (Rust SIP runtime) | Rejected | Too new; replaces Pipecat rather than plugging into it. |
| Genesys AudioHook | **Keep as a second path** | Pipecat ships `GenesysAudioHookSerializer`. Use when a bank wants the bot inside its existing Genesys contact centre instead of a new trunk. Audio Connector is Genesys Cloud only, not BYOC Premises. |
| AudioCodes VoiceAI Connect | **Later path** | Many GCC/private banks already own Mediant. Same bot, different media front. Not this package. |
| Twilio / Telnyx / Exotel WebSockets | Keep for demos and cloud-allowed tenants | Adapter behind `TELEPHONY_PROVIDER`. Not the bank on-prem path. |

---

## 2. Deployment model: one stack per region

Data residency is satisfied by **where the stack runs**, not by the SIP layer. Each region gets its own deployment; no borrower audio crosses a border.

| Region | Runs in | Carrier handoff | Model endpoints must also be in-region |
|---|---|---|---|
| India | Bank DC or Indian cloud region | Bank SBC ← Airtel / Tata / Jio SIP trunk, 1600-series number | e.g. Azure Central India |
| UAE | Bank DC or UAE cloud (CBUAE sovereign financial cloud / Core42) | Bank SBC ← **e& or du** only | e.g. Azure UAE North |
| KSA | Bank DC or in-Kingdom cloud | Bank SBC ← CST-licensed operator | in-Kingdom |
| USA | Bank DC or US region | Bank SBC ← carrier with STIR/SHAKEN attestation | US region |

> **The larger residency risk is not SIP.** Azure STT, Azure TTS and Azure OpenAI are still cloud calls. Every regional deployment must point them at an in-region endpoint (or an on-prem model), otherwise audio leaves the country anyway.

---

## 3. Docker Compose (demo / staging)

Staging overlay is `backend/docker-compose.telephony.yml` (Asterisk **22.8+**). **Windows / Docker Desktop:** publish `5060/udp`, `5060/tcp`, and a small RTP range (10000–10050 ≈ 25 calls). `network_mode: host` does not work on Docker Desktop; Linux/bank VMs can switch to host net later without bot changes.

Operator recordings go to MinIO `recordings/` via the Pipecat buffer (`voice/recording.py`). MixMonitor spool is a second `sip_audio` copy, ingested into the same bucket — not the system of record.

RTP: **each call uses 2 ports** (RTP + RTCP). 10000–20000 covers ~5,000 calls; a 50-port range caps you at ~25.

---

## 4. Asterisk configuration (the pluggable part)

The per-customer cutover is **configuration only**: the trunk endpoint in `pjsip.conf` and the allowed source addresses. The bot does not change.

### 4a. Trunk to the SBC — `pjsip.conf` (illustrative)

```ini
[transport-udp]
type=transport
protocol=udp
bind=0.0.0.0:5060
; Staging may use UDP. Bank prod: TLS transport (protocol=tls, cert_file,
; priv_key_file) and media_encryption=sdes when the SBC supports SRTP.
; UDP 5060 is the documented fallback, not the default handover.

[bank-sbc]
type=endpoint
transport=transport-udp
context=from-bank
disallow=all
allow=alaw,ulaw           ; India/UAE carriers usually hand off G.711 A-law
aors=bank-sbc
direct_media=no

[bank-sbc]
type=aor
contact=sip:10.20.30.40:5060   ; DEMO: softphone/test PBX. PROD: bank SBC inside address.

[bank-sbc]
type=identify
endpoint=bank-sbc
match=10.20.30.40/32           ; allowlist — never 0.0.0.0/0, even for demos
```

### 4b. Hand the call to the bot — `websocket_client.conf`

```ini
[habibi_bot]
type=websocket_client
connection_type=per_call_config   ; one socket per call (required for media)
uri=wss://voice.internal:8443/ws/asterisk
protocols=media
tls_enabled=yes
verify_server_cert=yes
```

### 4c. Dial plan — `extensions.conf`

```ini
[from-bank]
; Inbound: record on-prem, then stream the caller to the bot.
exten => _X.,1,NoOp(Inbound ${CALLERID(num)} -> ${EXTEN})
 same => n,MixMonitor(${UNIQUEID}.wav)
 same => n,Dial(WebSocket/habibi_bot/c(ulaw)f(json))
 same => n,Hangup()

[agents]
; Warm-transfer target when the bot escalates to a human collector.
exten => collectors,1,Queue(collections-agents)
```

Dial-string options used: `c(<codec>)` codec, `f(json)` JSON control messages (the plain-text format is deprecated). Others: `n` don't auto-answer, `p` passthrough, `v(...)` URI parameters, `d(in|out|both)` media direction.

**Outbound** (bot dials a borrower): the contact-policy engine approves the attempt, then originates through ARI — dial `PJSIP/<number>@bank-sbc` **into the `habibi` Stasis app**, and on answer bridge it to the bot's media leg. Use a separate websocket client connection for ARI and for media; never share one.

> **Correction, measured 18 Sep 2026.** ARI `externalMedia` with `transport=websocket` *does* create a `chan_websocket` channel, but that channel is not in ARI's bridgeable registry: `GET /channels` omits it and `bridges/{id}/addChannel` and `/record` answer **400 "Channel not found"**. Only the dialplan can reach such a channel. The bot's media leg is therefore a **Local channel** — the controller originates `Local/bot@to-bot`, whose far end runs `Dial(WebSocket/habibi_bot/c(slin16)f(json))` — and the controller bridges that. The dial comes before any `Answer`, so the leg answering means the bot is on the socket, which is what lets the caller be answered at the right moment. See `backend/voice/asterisk_controller.py`.

**What carries identity.** Dialplan variables and ARI originate variables do not reach the media channel. Set `__HABIBI_CTX` (inheritable) on the *caller's* channel and originate the media leg with `originator=<caller channel id>`; Asterisk copies it down the chain, and the bot reads it from `MEDIA_START.channel_variables` — under the name `__HABIBI_CTX`, prefix included.

---

## 5. Bot side: an `asterisk` serializer

What exists today:
- `voice/host.py` serves `/ws` for Twilio Media Streams; Pipecat's runner detects the provider from the first socket messages.
- `voice/bot.py` builds `FastAPIWebsocketParams` for the `twilio` transport type.
- `voice/bot_flow.py` treats `{"twilio","telnyx","plivo","exotel"}` as phone transports.

What to add:
1. **A dedicated route `/ws/asterisk`.** Pipecat's runner auto-detection does not recognise Asterisk, so build the transport explicitly instead of via `create_transport`.
2. **`AsteriskFrameSerializer`** (a few hundred lines), mapping:

   | Asterisk → bot | Bot → Asterisk |
   |---|---|
   | `MEDIA_START` (JSON: `connection_id`, `channel_id`, `format`, `optimal_frame_size`, `ptime`, `channel_variables`) → session start, carry `channel_id` for transfer/hangup | audio frames → binary ulaw/slin |
   | binary audio → `InputAudioRawFrame` | interruption → `FLUSH_MEDIA` |
   | `DTMF_END` → `InputDTMFFrame` | end of call → `HANGUP` |
   | `MEDIA_XOFF` / `MEDIA_XON` → pause/resume output | |

   Subclass Pipecat's `FastAPIWebsocketOutputTransport` for flow control, as Pipecat's maintainers advised. The community package [`pipecat-asterisk`](https://github.com/NikolayShakin/pipecat-asterisk) (BSD-2-Clause, tested on Pipecat 1.8.1) is a reference to borrow from; we are on Pipecat 1.6.0, so vendor the ideas rather than depend on it.
3. **Add `"asterisk"`** to the phone-transport set in `voice/bot_flow.py`, and read caller ANI from `channel_variables` for the customer lookup that `twilio_ops` does today.
4. **Move transfer off Twilio-only paths**: ARI redirect to the `agents` context. AMD stays the in-band detector in `voice/amd.py`.

---

## 6. Concurrency & Number Pools: Scaling Outbound in Real Operations

In real collections operations, an automated platform **never** dials "one-by-one" with a single number. During statutory calling hours (e.g. RBI 08:00–19:00), a lender must place hundreds of concurrent calls across rotating caller IDs.

### 6a. Software Concurrency vs. Human Headcount
- **AI agents are software instances, not physical seats.** When an outbound campaign dials 50 borrowers simultaneously, Asterisk handles 50 concurrent SIP/RTP sessions, and Habibi spawns 50 independent `asyncio` Pipecat workers.
- Each borrower converses with an independent agent instance concurrently—one in Hindi negotiating an EMI, another in Tamil requesting a callback, and a third in English settling a balance.
- Fleet concurrency is strictly capped by `OUTBOUND_MAX_IN_FLIGHT` (e.g. 50 in [`outbound.py`](file:///d:/Hackathon/backend/outbound.py#L191-L200)) to prevent campaign dialers from saturating the voice worker or starving inbound headroom (`VOICE_MAX_CONCURRENT_CALLS` in [`voice/admission.py`](file:///d:/Hackathon/backend/voice/admission.py#L85-L95)).

### 6b. Telecom Channels vs. Phone Numbers (DIDs)
A common misconception is needing "50 separate phone lines". In enterprise telecom:
1. **One SIP Trunk = Many Channels**: The bank contracts a single SIP trunk with 30, 100, or 500 concurrent channels (calls).
2. **One Trunk = A Block of DIDs (Caller IDs)**: The telco attaches a pool of 10 to 100 pilot numbers (e.g., in the 1600-series) to that single trunk.
3. **Dynamic Caller ID via ARI**: When Habibi originates a call, it selects a caller ID from the pool and instructs Asterisk to set the SIP `From:` / `P-Asserted-Identity:` header dynamically. No trunk reconfiguration is needed per call.

### 6c. Why Multiple Numbers are Required
Operating outbound collections with a single phone number fails in production:
1. **Truecaller & Handset Spam Decay**: If thousands of daily calls originate from one CLI, handsets and call-filtering apps flag it within 48 hours, causing answer rates to collapse from ~40% to <5%.
2. **Portfolio / Sub-Brand Separation**: Auto loans, credit cards, and retail lending cannot share a caller ID without misattributing identity to borrowers.
3. **Regulatory Classification**: India's TRAI mandates distinct headers/series for service vs. transactional outreach.

### 6d. How Habibi Handles Number Pools Today
Habibi already includes automated number-pool governance in [`backend/outbound_pools.py`](file:///d:/Hackathon/backend/outbound_pools.py):
- **Least-Recently-Used (LRU) Allocation**: [`pick_number()`](file:///d:/Hackathon/backend/outbound_pools.py#L17-L63) selects the active number with the oldest `last_used_at` via `SELECT ... FOR UPDATE SKIP LOCKED`, balancing dial volume across the pool.
- **Automated Spam Cooling**: [`refresh_pool_health()`](file:///d:/Hackathon/backend/outbound_pools.py#L78-L100) measures rolling 7-day answer rates. If an active number with ≥30 attempts drops below a 5% answer rate (`POOL_ANSWER_FLOOR`), Habibi moves it to `cooling` status for **7 days** (`POOL_COOL_HOURS = 168`), resting the number until spam reputation clears.

---

## 7. Demo Modes & Latency Benchmark (No Telco Contract Needed)

You can demonstrate the complete SIP and AI pipeline immediately without waiting for bank agreements or telco KYC. Two staging modes are available:

### 7a. Staging Option A: Real Mobile SIM Call (via Developer SIP Trunk)
- **Use case**: You want to type a real mobile number into Habibi and ring a real smartphone's native cellular dialer during an executive pitch.
- **Setup**: Connect Asterisk to an instant, self-serve developer SIP trunk (e.g. Telnyx or Twilio Elastic SIP Trunking, prepaid with $5–$10).
- **Flow**: Habibi originates call ➔ Asterisk sends SIP INVITE to Telnyx ➔ Telnyx terminates onto Indian/local cellular towers ➔ Target smartphone rings.

### 7b. Staging Option B: Pure Softphone over Local SIP (Zoiper / Linphone)
- **Use case**: 100% free, unlimited minutes, zero external telecom accounts, permanent local staging.
- **Setup**: Install **Zoiper**, **Linphone**, or **MicroSIP** on a smartphone or laptop and register it directly to Asterisk on port `5060`.
- **Why Option B is 100% Pluggable to Bank Production**:
  - To Asterisk and to Habibi, a softphone endpoint and a multi-million-dollar Bank SBC (Cisco CUBE, AudioCodes Mediant) speak the **exact same standard protocols**: **SIP (RFC 3261)** and **RTP (RFC 3550)**.
  ```
  [Option B (Staging Today)]
   Zoiper / Softphone ──SIP (RFC 3261)──► [Asterisk Gateway] ──WebSocket (/ws/asterisk)──► [Habibi AI Bot]

  [Bank Production (Tomorrow)]
   Bank's Cisco/AudioCodes SBC ──SIP (RFC 3261)──► [Asterisk Gateway] ──WebSocket (/ws/asterisk)──► [Habibi AI Bot]
  ```
  - The Python voice bot, the `AsteriskFrameSerializer`, the WebSocket endpoints, and the conversational engine are **100% identical and untouched**.
  - Moving from Option B to production requires only replacing the softphone IP in `pjsip.conf` (`contact` and `match`) with the bank's SBC IP address.

### 7c. Latency & Performance Benchmark: Asterisk vs. Twilio
These rows are **architecture properties, not a lab measurement of this stack.** End-to-end barge-in is VAD + STT + LLM cancel + flush. Measure on the Zoiper path before quoting milliseconds to a bank. Directionally: Twilio Media Streams has no India media region (US1 default; IE1 and AU1 only). Local RTP and raw binary frames avoid that hop and Base64-JSON wrapping.

1. **Network Transport Hop (Domestic/Local vs. Overseas Proxy)**:
   - **Twilio**: Even for domestic calls in India or the UAE, Twilio often proxies audio through overseas media clusters (Singapore, Europe, or US-East), adding **300ms–600ms** of transport delay.
   - **Asterisk (Option B / Prod)**: In Option B (local Wi-Fi), network latency is **2ms–5ms**. In bank production (domestic telco SIP to on-prem Asterisk), transport latency is **15ms–30ms**.
2. **Audio Serialization (Raw Binary vs. Base64 JSON)**:
   - **Twilio**: Every 20ms audio frame is wrapped in a JSON object and Base64-encoded:
     `{"event": "media", "media": {"payload": "//uQxAAAA..."}}`.
     Python must parse thousands of JSON payloads and decode Base64 strings per second, incurring continuous CPU and serialization delay.
   - **Asterisk (`chan_websocket`)**: Streams **pure raw binary audio bytes** (`ulaw` or `slin`) directly over the WebSocket. Python forwards frames directly to the STT buffer with zero parsing overhead.
3. **Instant Barge-In & Interruption (`FLUSH_MEDIA`)**:
   - **Twilio**: When a borrower interrupts ("Wait, stop!"), the bot issues a Twilio `clear` command. Twilio's cloud buffer takes **400ms–800ms** to drain, so the bot awkwardly talks over the borrower.
   - **Asterisk**: On interruption detection, Habibi sends a `FLUSH_MEDIA` control frame. Asterisk purges the local channel playout buffer in **<10ms**, cutting bot audio instantly for a natural, human-like reaction.

| Telephony Metric | Twilio Media Streams | Self-Hosted Asterisk (Option B & Prod) | Improvement with Asterisk |
|---|---|---|---|
| **Audio Transport Latency** | ~350ms – 600ms+ (Foreign cloud hops) | **2ms – 30ms** (Direct local/domestic RTP) | **~300ms faster** |
| **Audio Payload Format** | Base64-encoded text inside JSON | **Raw binary audio bytes** | **Zero serialization lag** |
| **Jitter / Buffer Control** | Remote cloud buffer | **Asterisk local jitter buffer** | **Stable playout clock** |
| **Barge-in Cutoff Delay** | 400ms – 800ms (Noticeable talk-over) | **< 10ms** (`FLUSH_MEDIA` channel flush) | **Instant interruption** |
| **Total Telephony Overhead** | **~450ms – 800ms** | **~20ms – 50ms** | **~400ms–750ms total reduction** |

### 7d. Step-by-Step Option B Demo Execution
1. Run Asterisk with the §4 configuration pointing `bank-sbc` to your softphone's IP.
2. In **Zoiper** or **Linphone**, enter your Asterisk host IP and dial extension `1001`.
3. Asterisk triggers `MixMonitor` (recording locally) and dials `WebSocket/habibi_bot`.
4. Habibi answers and greets the caller.
5. **Interactive Verification**:
   - **Barge-in**: Speak over the bot—playback cuts immediately.
   - **Keypad / DTMF**: Press `1` or `2`—captured via `DTMF_END` frames.
   - **Queue Transfer**: Trigger human escalation—Asterisk executes warm queue transfer.
   - **SIP Ladder**: Run `sngrep` on the Asterisk host to show the live RFC 3261 call flow to observers.

---

## 8. Country rules

The gateway is identical everywhere. Rules land in three places: **carrier/number**, **deployment region** (§2), and **the contact-policy engine** as a per-jurisdiction rule pack. Calling rules do not belong in telephony config.

### India
- **1600-series numbers are mandatory** for **service and transactional** calls by RBI-, SEBI-, PFRDA- and IRDAI-regulated entities. TRAI's phased deadlines ran 1 Jan 2026 (commercial banks) to 1 Mar 2026 (remaining RBI entities). Non-compliance: treated as an unregistered telemarketer, penalties from ₹2 lakh per violation, possible blacklisting of telecom resources. The number is allocated by the telco on the SIP trunk. Whether **post-default recovery** is a “service call” is **not settled** — do not assert 1600 for all collections until counsel signs it. Pre-default EMI reminders likely qualify.
- Recovery calls only within the RBI window (08:00–19:00), DND and frequency caps — contact-policy engine.
- Residency: the stronger arguments are RBI outsourcing/IT-outsourcing directions, DPDP Act 2023 obligations, and the bank's own policy. (The 2018 RBI localisation circular is about payment-system data, not call audio — don't overstate it.)

### UAE
- **Only e& (Etisalat) and du** may provide business voice/SIP trunks (TDRA); unlicensed VoIP is blocked.
- CBUAE Consumer Protection Standards (§5.2.5 debt collection): all communications with consumers recorded and **retained 5 years** after settlement/write-off; the name of the employee/agent making the call documented; no undue or coercive pressure; disclose any third-party collector, the amount, and its authority. For an AI caller, "agent name" means the bot/card identity plus the accountable human — record both.
- CBUAE outsourcing/cloud rules and its AI guidance (governance framework, model inventory, board accountability, bias testing) → in-country hosting and in-region models.

### KSA
- SAMA Debt Collection Regulations (updated by circular 106889333, 5 Mar 2025) apply to banks and finance companies; do not invoke SAMA or credit bureaus in collection calls; stop reminders while a complaint is open. Confirm call-hour and recording specifics against the full rulebook before onboarding.

### USA
- **Reg F (FDCPA):** presumed violation above 7 calls in 7 days per debt, or within 7 days after a conversation.
- **TCPA:** the FCC ruled (Feb 2024, FCC 24-17) AI-generated voices are "artificial voice" — consent rules apply; disclose the AI voice at call start and offer an automated opt-out.
- Caller ID signed via STIR/SHAKEN by the carrier; two-party-consent states need a recording disclosure.

---

## 9. Production cutover checklist

1. **Regulatory:** number allocation (India 1600-series; UAE via e&/du; US STIR/SHAKEN attestation), letter of authority from the lender.
2. **Network:** the bank's telecom team issues the SIP handover sheet — SBC inside IP, codec (usually G.711 A-law, 20 ms), TLS/SRTP support, channel count.
3. **Asterisk config:** set `contact` and `match` in `pjsip.conf`, enable the TLS transport and SRTP if offered, size the RTP range, reload (`pjsip reload`). No bot code changes.
4. **Region wiring:** STT/TTS/LLM endpoints set to the in-region deployment.
5. **Policy pack:** enable the jurisdiction's contact-policy rules; verify recording retention.
6. **Test calls:** inbound, outbound, barge-in, DTMF, transfer, recording playback — through the real SBC before go-live.

---

## 10. Pitch (for bank CTOs and telecom architects)

> "Our voice agent does not send your customers' audio through a foreign cloud. We install one open-source SIP gateway — Asterisk — behind your existing Session Border Controller, inside your data centre or in-country cloud. You keep your carrier, your numbers, your recordings and your media perimeter. The same design runs in India on a 1600-series trunk, in the UAE on e& or du, and in the US on your own carrier; only the trunk address and the local calling rules change."

---

## 11. Corrections to the previous draft

| Previous claim | Correction |
|---|---|
| "160-series" CLI | The TRAI mandate is the **1600-series**, and its deadlines passed Jan–Mar 2026. |
| Trunks and dispatch rules in `sip.yaml`; "edit and restart, zero code" | Invalid for LiveKit SIP: trunks/dispatch rules are API objects stored in Redis, not config-file entries. |
| `pipecat.transports.services.livekit` | Current path is `pipecat.transports.livekit.transport`. |
| Bridged ports, RTP 10000–10050 | LiveKit SIP needs host networking; a 50-port range caps concurrency at ~25 calls. |
| Inbound `allowed_addresses: 0.0.0.0/0` for demo | Open SIP ports are found by scanners within hours (toll fraud). Always allowlist. |
| "RBI data localization" forbids foreign voice processing | Overstated; that circular covers payment data. Use outsourcing rules, DPDP and bank policy. |
| `create_stt_service()` etc. in sample code | Functions that don't exist in this codebase. |
| `version: "3.9"`, `:latest` images | Obsolete compose key; unpinned images are unacceptable for a bank. |
| India only | UAE, KSA and US requirements were missing (§8). |
| Per-minute rates ₹0.20–0.35 vs Twilio | Unsourced; quote from the carrier's proposal instead. |

---

## Sources

- Pipecat Asterisk integration: [pipecat-asterisk](https://github.com/NikolayShakin/pipecat-asterisk) · [PR #3229](https://github.com/pipecat-ai/pipecat/pull/3229) · [issue #3260](https://github.com/pipecat-ai/pipecat/issues/3260)
- Asterisk: [WebSocket channel driver](https://docs.asterisk.org/Configuration/Channel-Drivers/WebSocket/) · [res_websocket_client](https://docs.asterisk.org/Latest_API/API_Documentation/Module_Configuration/res_websocket_client/)
- LiveKit SIP: [README](https://github.com/livekit/sip/blob/main/README.md) · [secure trunking](https://docs.livekit.io/sip/secure-trunking/) · [self-hosted trunk config (issue #256)](https://github.com/livekit/sip/issues/256)
- Others: [jambonz self-hosting](https://www.jambonz.org/self-hosting) · [FreeSWITCH install](https://signalwire.com/docs/platform/freeswitch/installing-freeswitch) · [Flowcat](https://github.com/AreevAI/flowcat)
- India: [TRAI 1600-series direction](https://trai.gov.in/notifications/press-release/trai-issues-direction-mandating-phase-wise-adoption-1600-series-bfsi) · [Vinod Kothari analysis](https://vinodkothari.com/2026/03/adopting-1600-number-series-preventive-measure-or-burden/)
- UAE: [CBUAE Consumer Protection Standards](https://rulebook.centralbank.ae/en/rulebook/consumer-protection-standards) · [CBUAE 5.2.5 Debt Collection](https://cbuae.thomsonreuters.com/en/rulebook/525-debt-collection-practice) · [TDRA FAQs](https://tdra.gov.ae/en/FAQs)
- KSA: [SAMA debt collection regulations](https://rulebook.sama.gov.sa/en/debt-collection-regulations-and-procedures-individual-customers-1)
- USA: [CFPB call frequency](https://www.consumerfinance.gov/ask-cfpb/when-and-how-often-can-a-debt-collector-call-me-on-the-phone-en-2110/) · [FCC 24-17](https://docs.fcc.gov/public/attachments/FCC-24-17A1.pdf)
