# Voice LLM latency — bottlenecks & keep-alive

## Fix applied

Pipecat's stock `AzureLLMService.create_client()` does **not** set httpx
`keepalive_expiry=None` (OpenAI path does). Our old prewarm also **closed** its
client, so the next Pipecat turn re-handshook TLS every time.

Now:

- [`voice/llm_pool.py`](llm_pool.py) — process-wide shared `AsyncAzureOpenAI` with
  persistent keep-alives
- `KeepAliveAzureLLMService` — Pipecat uses that same client
- Prewarm never closes the client; runs at bot start + on call connect

```powershell
.\.venv\Scripts\python.exe -m voice.spike --bottlenecks
.\.venv\Scripts\python.exe -m voice.spike --probe-ttfb --rounds 6
```

## Bottleneck breakdown (`gpt-4.1-mini` @ East US 2, from India)

| Stage | p50 / typical | Notes |
|-------|---------------|--------|
| DNS | ~130 ms | one-time |
| Cold HTTP (TCP+TLS+GET) | ~1920 ms | full handshake |
| Warm HTTP (keep-alive) | **~510–740 ms** | network floor India→East US 2 |
| Handshake tax (cold−warm) | **~1200 ms** | what keep-alive removes |
| LLM TTFB (shared client) | **~1.3–1.9 s** (saw 881 ms once) | |
| Approx model/queue beyond RTT | **~1000 ms** | `TTFB − warm_HTTP` |

## What we can / cannot fix in code

**Fixed here:** repeated TLS handshakes between turns; prewarm now warms the
real Pipecat client.

**Hard floor from this laptop:** ~500–700 ms network RTT to East US 2 +
~1 s Azure model TTFT → expect ~1.5 s warm LLM TTFB unless the resource moves
closer (India / SE Asia region).

## Resource

```
AZURE_OPENAI_VOICE_ENDPOINT=https://bt-rmc-01c7b.openai.azure.com/
AZURE_OPENAI_VOICE_DEPLOYMENT=gpt-4.1-mini
region: East US 2
```
