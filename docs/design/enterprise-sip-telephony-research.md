# Enterprise SIP telephony — research (17 Sep 2026)

Review of [`enterprise-sip-telephony.md`](enterprise-sip-telephony.md). This note is the source of truth for what we implement now versus what stays a later bank plug.

## Verdict

Keep **Asterisk behind an SBC**, WebSocket into the existing Pipecat bot. That is the right *class* of on-prem path.

The compose snippet in the blueprint is **staging**, not a bank DC install. Do not ship a single UDP-only container as production.

Twilio is **not deleted**. It remains a selectable adapter (`TELEPHONY_PROVIDER=twilio|asterisk`). Bank production unplugs Twilio; the module stays for demos and cloud-allowed tenants. Browser WebRTC sandbox is unrelated.

## What the blueprint got right

- Sit behind the bank’s existing SBC (Cisco CUBE / AudioCodes / Oracle). Habibi is an application, not the public SIP edge.
- `chan_websocket` is first-party Asterisk: playout clock, `FLUSH_MEDIA`, `DTMF_END`, `MEDIA_XOFF`/`MEDIA_XON`, TLS on the client socket.
- Fits the current bot: WebSocket + frame serializer. Asterisk is one more serializer.
- Reject LiveKit SIP as the primary collections path (extra SFU + Redis, SIP→WebRTC hop, cold REFER, no agent queue).
- Keep Genesys AudioHook as a second path when the contact centre is already Genesys Cloud (Audio Connector is **not** supported on BYOC Premises / LDM Edge).
- Keep Twilio/Telnyx/Exotel WebSockets for demos and tenants that allow foreign media. Not the bank on-prem path.
- Residency is where STT/TTS/LLM run, not the SIP layer.
- Allowlist SIP sources; never `0.0.0.0/0`.
- TRAI series is **1600**, not 160. The 2018 RBI localisation circular is payment-system data, not call audio.
- jambonz self-host licence ($7/session or $2,000/month) is accurate as of 2026.

## Gaps (do not treat the blueprint as a runbook)

| Gap | Implication |
|---|---|
| Pin **22.8+**, not 22.6 | JSON control is preferred from 20.18 / 22.8 / 23.2; `f(json)` needs that floor. Staging overlay uses **andrius 23.4.1** because that image's 22.x line does not compile `chan_websocket`. |
| TLS/SRTP left as a comment | Bank handover sheets ask for SIP TLS + SRTP first. UDP 5060 is the lab trunk. |
| MixMonitor to a Docker volume | Not a retention system. Operator recordings already go to MinIO `recordings/` via `voice/recording.py`. MixMonitor is a second SIP copy (`sip_audio`). |
| Single container, `network_mode: host` | Asterisk does not fail over live RTP. Host net does **not** work on Docker Desktop (Windows). Staging publishes 5060 + a small RTP range. |
| `chan_websocket` is young | Late-2025 driver. Pipecat core closed upstream (#3260) and listed Asterisk as an **unsupported community** serializer. **Do not** `pip install pipecat-asterisk` onto `pipecat-ai==1.6.0`. Vendor a small serializer. |
| GPLv2 | ARI/WebSocket apps are not derivative works per Asterisk LICENSE. Shipping a **patched** Asterisk into a bank DC is the Sangoma-licence conversation. Stock image as a service is the usual path. |
| `AMD()` | Cadence heuristics, ~70–85% on modern mobile. Keep in-band ML (`voice/amd.py`). A false HUMAN leaves a debt disclosure on voicemail. |
| Latency table | Directionally true (Twilio Media Streams has no India media region: US1 / IE1 / AU1). Millisecond rows are **unmeasured**. Quote as architecture, then measure on Zoiper. |
| Habibi as the edge | Bank tenants have a CUBE. An NBFC / Habibi-operated region needs Kamailio+RTPEngine or a commercial SBC in front of Asterisk. Not this package. |
| AudioCodes VoiceAI Connect | Missing third path. Many GCC/private banks already own Mediant. Later adapter, same bot. |
| 1600 vs recovery | 1600 is mandatory for BFSI **service/transactional** calls (banks from 1 Jan 2026). Whether **post-default recovery** is a service call is unsettled (NBFC CEOs asked RBI; Vinod Kothari 5 Sep 2026 argues it is outside TCCCPR). Pre-default EMI reminders likely are 1600. Counsel signs recovery numbering. |

## Plug map

| Plug | When |
|---|---|
| `asterisk` | Default on-prem / local softphone. Bank CUBE tomorrow is `pjsip.conf` `contact`/`match` only. |
| `twilio` | Unset default so existing tunnels keep working. Demos and cloud-allowed tenants. |
| `genesys` | Later. Bank already runs Genesys Cloud. |
| `audiocodes` | Later. Bank already runs VoiceAI Connect / Live Hub. |

## This package vs later

**Now:** provider seam, vendored serializer, `/ws/asterisk`, compose overlay + Zoiper, ARI originate/transfer/hangup, real Audit playback, MixMonitor ingest as `sip_audio` (migration written, not applied), redaction index + real export zip.

**Later:** dual-node HA, Kamailio, SIP TLS/SRTP as the only trunk, Genesys/AudioCodes adapters, Sangoma SLA, object-lock / 5-year CBUAE retention, predictive CPS beyond `OUTBOUND_MAX_IN_FLIGHT`.

## Sources

Asterisk WebSocket channel driver; `res_websocket_client`; Asterisk LICENSE / Sangoma commercial licensing; Pipecat issue #3260 (closed → community); docs.pipecat.ai Asterisk serializer (unsupported); jambonz self-hosting; LiveKit secure trunking; Genesys Audio Connector overview; AudioCodes VoiceAI Connect Enterprise; Twilio Media Streams regions; TRAI direction 19 Nov 2025; ETBFSI recovery/1600 query; Vinod Kothari 5 Sep 2026; CBUAE Consumer Protection Standards §5.2.5.
