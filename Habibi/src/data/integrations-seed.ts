// Integrations & API Connections — synthetic connector registry

export type Env = "sandbox" | "production";
export type HealthStatus = "healthy" | "degraded" | "down" | "unconfigured";
export type Category = "Voice AI" | "Messaging" | "Telephony" | "Core Banking" | "Orchestrator";

export type ProviderField = {
  key: string;
  label: string;
  secret?: boolean;
  placeholder?: string;
};

export type ProviderId =
  | "azure_openai" | "openai" | "azure_speech_stt" | "azure_speech_tts"
  | "twilio" | "whatsapp" | "cbs" | "pipecat";

export type UsageStat = { label: string; value: string };

export type Provider = {
  id: ProviderId;
  name: string;
  vendor: string;
  category: Category;
  capability: string;
  description: string;
  docsUrl: string;
  brandInitial: string;
  brandColor: string; // tw class
  capabilities: string[];
  fields: ProviderField[];
  perEnv: Record<Env, {
    values: Record<string, string>;
    region: string;
    health: HealthStatus;
    latencyMs: number;
    enabled: boolean;
    usageStats: UsageStat[];
    costMonth: string;
    unitLabel: string; // "tokens", "minutes", "chars", "messages"…
    /** Live mode: secrets are env/ops-managed — UI must not write them. */
    credentialsLocked?: boolean;
  }>;
};

/** Providers backed by real process env in live mode (CBS / Pipecat stay mock-only). */
export const LIVE_PROVIDER_IDS: ProviderId[] = [
  "azure_openai",
  "azure_speech_stt",
  "azure_speech_tts",
  "twilio",
  "whatsapp",
];

const seedUsage = (id: ProviderId, days = 14) => {
  const pts: number[] = [];
  let v = 40;
  for (let i = 0; i < days; i++) {
    const drift = Math.sin(i * 0.7 + id.length) * 12 + (Math.random() - 0.5) * 18;
    v = Math.max(6, Math.min(120, v + drift));
    pts.push(Math.round(v));
  }
  return pts;
};

export const PROVIDERS: Provider[] = [
  {
    id: "azure_openai",
    name: "Azure OpenAI",
    vendor: "Microsoft Azure",
    category: "Voice AI",
    capability: "LLM — reasoning core",
    description: "GPT-4o Realtime deployment powering the collections bot's reasoning, RAG synthesis, and tool-calling loop through Pipecat.",
    docsUrl: "https://learn.microsoft.com/azure/ai-services/openai/",
    brandInitial: "Az",
    brandColor: "bg-blue-100 text-blue-700",
    capabilities: ["streaming", "tool-calling", "JSON mode", "PII masking"],
    fields: [
      { key: "endpoint", label: "Endpoint", placeholder: "https://hdfc-coll.openai.azure.com" },
      { key: "apiKey", label: "API key", secret: true, placeholder: "sk-********" },
      { key: "deployment", label: "Deployment name", placeholder: "gpt-4o-realtime" },
      { key: "apiVersion", label: "API version", placeholder: "2024-10-01-preview" },
    ],
    perEnv: {
      sandbox: {
        values: { endpoint: "https://hdfc-coll-sbx.openai.azure.com", apiKey: "", deployment: "gpt-4o-realtime", apiVersion: "2024-10-01-preview" },
        region: "eastus", health: "healthy", latencyMs: 189, enabled: true,
        usageStats: [{ label: "Prompt tokens", value: "1.42 M" }, { label: "Completion tokens", value: "612 K" }, { label: "Avg latency", value: "189 ms" }],
        costMonth: "$243.10", unitLabel: "tokens",
      },
      production: {
        values: { endpoint: "https://hdfc-coll.openai.azure.com", apiKey: "", deployment: "gpt-4o-realtime", apiVersion: "2024-10-01-preview" },
        region: "centralindia", health: "healthy", latencyMs: 142, enabled: true,
        usageStats: [{ label: "Prompt tokens", value: "38.9 M" }, { label: "Completion tokens", value: "14.2 M" }, { label: "Avg latency", value: "142 ms" }],
        costMonth: "$6,412.55", unitLabel: "tokens",
      },
    },
  },
  {
    id: "openai",
    name: "OpenAI",
    vendor: "OpenAI",
    category: "Voice AI",
    capability: "LLM · fallback",
    description: "Secondary GPT-4o endpoint used when the Azure deployment is throttled or fails a health check.",
    docsUrl: "https://platform.openai.com/docs",
    brandInitial: "Oa",
    brandColor: "bg-emerald-100 text-emerald-700",
    capabilities: ["streaming", "tool-calling", "fallback"],
    fields: [
      { key: "apiKey", label: "API key", secret: true, placeholder: "sk-********" },
      { key: "org", label: "Organization ID", placeholder: "org_..." },
      { key: "model", label: "Model", placeholder: "gpt-4o" },
    ],
    perEnv: {
      sandbox: {
        values: { apiKey: "", org: "org_hdfc_sbx", model: "gpt-4o-mini" },
        region: "global", health: "healthy", latencyMs: 220, enabled: true,
        usageStats: [{ label: "Requests", value: "8,412" }, { label: "Avg tokens/req", value: "1,240" }, { label: "Errors", value: "0.2%" }],
        costMonth: "$88.30", unitLabel: "tokens",
      },
      production: {
        values: { apiKey: "", org: "org_hdfc_prd", model: "gpt-4o" },
        region: "global", health: "degraded", latencyMs: 480, enabled: true,
        usageStats: [{ label: "Requests", value: "42,120" }, { label: "Avg tokens/req", value: "2,190" }, { label: "Errors", value: "1.4%" }],
        costMonth: "$1,204.00", unitLabel: "tokens",
      },
    },
  },
  {
    id: "azure_speech_stt",
    name: "Azure Speech STT",
    vendor: "Microsoft Azure",
    category: "Voice AI",
    capability: "STT — streaming ASR",
    description: "Azure Speech real-time transcription feeding audio frames from Pipecat's Twilio transport into the LLM.",
    docsUrl: "https://learn.microsoft.com/azure/ai-services/speech-service/",
    brandInitial: "Az",
    brandColor: "bg-sky-100 text-sky-700",
    capabilities: ["streaming", "hi-IN + en-IN", "punctuation", "interim results"],
    fields: [
      { key: "speechKey", label: "Speech key", secret: true, placeholder: "********" },
      { key: "region", label: "Region", placeholder: "centralindia" },
      { key: "language", label: "Language", placeholder: "en-IN" },
    ],
    perEnv: {
      sandbox: {
        values: { speechKey: "", region: "centralindia", language: "en-IN" },
        region: "centralindia", health: "healthy", latencyMs: 92, enabled: true,
        usageStats: [{ label: "Minutes streamed", value: "3,420" }, { label: "WER (est.)", value: "6.1%" }, { label: "Concurrent streams", value: "12" }],
        costMonth: "$38.40", unitLabel: "minutes",
      },
      production: {
        values: { speechKey: "", region: "centralindia", language: "en-IN" },
        region: "centralindia", health: "healthy", latencyMs: 74, enabled: true,
        usageStats: [{ label: "Minutes streamed", value: "72,180" }, { label: "WER (est.)", value: "5.4%" }, { label: "Concurrent streams", value: "184" }],
        costMonth: "$812.00", unitLabel: "minutes",
      },
    },
  },
  {
    id: "azure_speech_tts",
    name: "Azure Speech TTS",
    vendor: "Microsoft Azure",
    category: "Voice AI",
    capability: "TTS — outbound voice",
    description: "Azure neural voices synthesizing bot responses with the persona-selected voice profile from Prompt Studio.",
    docsUrl: "https://learn.microsoft.com/azure/ai-services/speech-service/text-to-speech",
    brandInitial: "Az",
    brandColor: "bg-teal-100 text-teal-700",
    capabilities: ["neural voices", "en-IN / hi-IN", "SSML", "streaming"],
    fields: [
      { key: "speechKey", label: "Speech key", secret: true, placeholder: "********" },
      { key: "region", label: "Region", placeholder: "centralindia" },
      { key: "defaultVoice", label: "Default voice", placeholder: "en-IN-NeerjaNeural" },
    ],
    perEnv: {
      sandbox: {
        values: { speechKey: "", region: "centralindia", defaultVoice: "en-IN-NeerjaNeural" },
        region: "centralindia", health: "healthy", latencyMs: 280, enabled: true,
        usageStats: [{ label: "Characters", value: "412 K" }, { label: "Voices used", value: "4" }, { label: "Avg latency", value: "280 ms" }],
        costMonth: "$62.00", unitLabel: "chars",
      },
      production: {
        values: { speechKey: "", region: "centralindia", defaultVoice: "en-IN-NeerjaNeural" },
        region: "centralindia", health: "healthy", latencyMs: 240, enabled: true,
        usageStats: [{ label: "Characters", value: "9.8 M" }, { label: "Voices used", value: "6" }, { label: "Avg latency", value: "240 ms" }],
        costMonth: "$1,480.00", unitLabel: "chars",
      },
    },
  },
  {
    id: "twilio",
    name: "Twilio",
    vendor: "Twilio",
    category: "Telephony",
    capability: "PSTN + SIP transport",
    description: "Programmable Voice as the media transport for Pipecat — receives inbound PSTN calls and streams audio to the pipeline.",
    docsUrl: "https://www.twilio.com/docs/voice",
    brandInitial: "Tw",
    brandColor: "bg-red-100 text-red-700",
    capabilities: ["SIP", "Media Streams", "PSTN", "recording"],
    fields: [
      { key: "accountSid", label: "Account SID", placeholder: "AC********" },
      { key: "authToken", label: "Auth token", secret: true, placeholder: "********" },
      { key: "phoneNumber", label: "Phone number", placeholder: "+91 22 61 000 000" },
    ],
    perEnv: {
      sandbox: {
        values: { accountSid: "AC_sbx_1a2b3c4d5e6f7a8b9c0d1e2f", authToken: "", phoneNumber: "+91 22 68 888 000" },
        region: "in1", health: "healthy", latencyMs: 42, enabled: true,
        usageStats: [{ label: "Inbound minutes", value: "2,110" }, { label: "Active numbers", value: "1" }, { label: "MOS score", value: "4.3" }],
        costMonth: "$63.30", unitLabel: "minutes",
      },
      production: {
        values: { accountSid: "AC_prd_9f8e7d6c5b4a3f2e1d0c9b8a", authToken: "", phoneNumber: "+91 22 61 999 111" },
        region: "in1", health: "healthy", latencyMs: 38, enabled: true,
        usageStats: [{ label: "Inbound minutes", value: "58,410" }, { label: "Active numbers", value: "4" }, { label: "MOS score", value: "4.4" }],
        costMonth: "$1,752.30", unitLabel: "minutes",
      },
    },
  },
  {
    id: "whatsapp",
    name: "WhatsApp Business",
    vendor: "Meta",
    category: "Messaging",
    capability: "Outbound + inbound chat",
    description: "Secondary channel — template messages for callbacks/PTP reminders and inbound webhook into the same conversation store.",
    docsUrl: "https://developers.facebook.com/docs/whatsapp",
    brandInitial: "Wa",
    brandColor: "bg-green-100 text-green-700",
    capabilities: ["templates", "media", "webhooks", "opt-in"],
    fields: [
      { key: "phoneNumberId", label: "Phone number ID", placeholder: "1091234567890" },
      { key: "wabaId", label: "WABA ID", placeholder: "1029384756" },
      { key: "accessToken", label: "System-user token", secret: true, placeholder: "EAAG********" },
    ],
    perEnv: {
      sandbox: {
        values: { phoneNumberId: "1099887766554433", wabaId: "1029384756", accessToken: "" },
        region: "global", health: "unconfigured", latencyMs: 0, enabled: false,
        usageStats: [{ label: "Templates sent", value: "0" }, { label: "Sessions", value: "0" }],
        costMonth: "$0.00", unitLabel: "messages",
      },
      production: {
        values: { phoneNumberId: "1088776655443322", wabaId: "9182736450", accessToken: "" },
        region: "global", health: "healthy", latencyMs: 305, enabled: true,
        usageStats: [{ label: "Templates sent", value: "12,410" }, { label: "Sessions", value: "3,890" }, { label: "Delivered", value: "97.2%" }],
        costMonth: "$412.68", unitLabel: "messages",
      },
    },
  },
  {
    id: "cbs",
    name: "HDFC Core Banking",
    vendor: "In-house (Finacle)",
    category: "Core Banking",
    capability: "Ledger + EMI lookup",
    description: "Read-only mTLS bridge into the core banking system for balance, EMI schedule and payment history lookups requested by the bot.",
    docsUrl: "https://internal.hdfc/api/cbs/v2",
    brandInitial: "Cb",
    brandColor: "bg-amber-100 text-amber-700",
    capabilities: ["mTLS", "read-only", "sub-100 ms", "field-level PII redaction"],
    fields: [
      { key: "baseUrl", label: "Base URL", placeholder: "https://cbs-gw.hdfc.internal/v2" },
      { key: "clientId", label: "Client ID", placeholder: "coll-ai-svc" },
      { key: "clientSecret", label: "Client secret", secret: true, placeholder: "********" },
      { key: "certRef", label: "mTLS cert ref", placeholder: "vault://cbs/client-cert" },
    ],
    perEnv: {
      sandbox: {
        values: { baseUrl: "https://cbs-uat.hdfc.internal/v2", clientId: "coll-ai-uat", clientSecret: "", certRef: "vault://cbs/uat-client-cert" },
        region: "internal", health: "healthy", latencyMs: 58, enabled: true,
        usageStats: [{ label: "Lookups", value: "18,240" }, { label: "Cache hit", value: "62%" }, { label: "5xx", value: "0.05%" }],
        costMonth: "—", unitLabel: "calls",
      },
      production: {
        values: { baseUrl: "https://cbs-gw.hdfc.internal/v2", clientId: "coll-ai-svc", clientSecret: "", certRef: "vault://cbs/prod-client-cert" },
        region: "internal", health: "healthy", latencyMs: 47, enabled: true,
        usageStats: [{ label: "Lookups", value: "412,180" }, { label: "Cache hit", value: "71%" }, { label: "5xx", value: "0.02%" }],
        costMonth: "—", unitLabel: "calls",
      },
    },
  },
  {
    id: "pipecat",
    name: "Pipecat Orchestrator",
    vendor: "Pipecat (self-hosted)",
    category: "Orchestrator",
    capability: "Voice AI pipeline runtime",
    description: "The Pipecat worker glues Twilio ↔ Azure Speech STT ↔ Azure OpenAI ↔ Azure Speech TTS together. This connector holds its base URL and the HMAC secret used to sign webhooks into this CRM.",
    docsUrl: "https://docs.pipecat.ai/",
    brandInitial: "Pc",
    brandColor: "bg-brand-tint text-brand-primary-dark",
    capabilities: ["FastAPI", "WebRTC/SIP", "HMAC webhooks", "auto-restart on key rotate"],
    fields: [
      { key: "baseUrl", label: "Base URL", placeholder: "https://pipecat.hdfc.internal" },
      { key: "webhookSecret", label: "Webhook HMAC secret", secret: true, placeholder: "whsec_********" },
      { key: "workerPool", label: "Worker pool", placeholder: "coll-ai-workers-01" },
    ],
    perEnv: {
      sandbox: {
        values: { baseUrl: "https://pipecat-sbx.hdfc.internal", webhookSecret: "", workerPool: "coll-ai-workers-sbx" },
        region: "in-mum-1", health: "healthy", latencyMs: 12, enabled: true,
        usageStats: [{ label: "Sessions today", value: "184" }, { label: "Active workers", value: "3" }, { label: "P95 turn latency", value: "1.42 s" }],
        costMonth: "—", unitLabel: "sessions",
      },
      production: {
        values: { baseUrl: "https://pipecat.hdfc.internal", webhookSecret: "", workerPool: "coll-ai-workers-01" },
        region: "in-mum-1", health: "healthy", latencyMs: 9, enabled: true,
        usageStats: [{ label: "Sessions today", value: "4,120" }, { label: "Active workers", value: "24" }, { label: "P95 turn latency", value: "1.28 s" }],
        costMonth: "—", unitLabel: "sessions",
      },
    },
  },
];

// Pre-generated usage series per (id, env), stable within a session.
const USAGE_CACHE: Record<string, number[]> = {};
export function usageSeries(id: ProviderId, env: Env) {
  const k = `${id}:${env}`;
  if (!USAGE_CACHE[k]) USAGE_CACHE[k] = seedUsage(id).map(v => Math.round(v * (env === "production" ? 3.2 : 1)));
  return USAGE_CACHE[k];
}

export type TestLogEntry = {
  id: string;
  at: string;
  providerId: ProviderId;
  env: Env;
  ok: boolean;
  latencyMs: number;
  message: string;
  payload?: string;
};

const rid = () => Math.random().toString(36).slice(2, 9);

export function runMockHealthCheck(provider: Provider, env: Env): Promise<TestLogEntry> {
  return new Promise(resolve => {
    const cfg = provider.perEnv[env];
    const delay = 400 + Math.random() * 700;
    setTimeout(() => {
      const ok = cfg.health !== "down" && cfg.health !== "unconfigured" && Math.random() > 0.05;
      const latency = Math.round((cfg.latencyMs || 200) * (0.85 + Math.random() * 0.3));
      const fixture = TEST_FIXTURES[provider.id];
      resolve({
        id: rid(),
        at: new Date().toISOString(),
        providerId: provider.id,
        env,
        ok,
        latencyMs: latency,
        message: ok ? fixture.okMessage : fixture.failMessage,
        payload: ok ? fixture.okPayload : fixture.failPayload,
      });
    }, delay);
  });
}

const TEST_FIXTURES: Record<ProviderId, { okMessage: string; failMessage: string; okPayload: string; failPayload: string }> = {
  azure_openai: {
    okMessage: "Chat completion returned in 189 ms",
    failMessage: "Deployment throttled (429)",
    okPayload: '{"choices":[{"message":{"role":"assistant","content":"pong"}}],"usage":{"total_tokens":8}}',
    failPayload: '{"error":{"code":"429","message":"Requests to the ChatCompletions_Create Operation have exceeded rate limit"}}',
  },
  openai: {
    okMessage: "Fallback GPT-4o responded",
    failMessage: "Organization key invalid",
    okPayload: '{"model":"gpt-4o","choices":[{"message":{"content":"pong"}}]}',
    failPayload: '{"error":{"type":"invalid_request_error","message":"Incorrect API key"}}',
  },
  azure_speech_stt: {
    okMessage: "Sample audio transcribed (Azure Speech)",
    failMessage: "Speech websocket handshake refused",
    okPayload: '{"RecognitionStatus":"Success","DisplayText":"hello I need help with my loan","Offset":0}',
    failPayload: '{"error":{"code":"Unauthorized","message":"Invalid subscription key"}}',
  },
  azure_speech_tts: {
    okMessage: "TTS synthesized 42-char sample in 280 ms",
    failMessage: "Quota exceeded",
    okPayload: '{"audio":"<base64 · 32 kB>","voice":"en-IN-NeerjaNeural","chars":42}',
    failPayload: '{"error":{"code":"429","message":"Rate limit exceeded"}}',
  },
  twilio: {
    okMessage: "Lookup on +91 98 100 12345 succeeded",
    failMessage: "Auth failed",
    okPayload: '{"phone_number":"+919810012345","carrier":{"name":"Airtel","type":"mobile"}}',
    failPayload: '{"code":20003,"message":"Authenticate"}',
  },
  whatsapp: {
    okMessage: "Template ptp_reminder_v3 delivered to test number",
    failMessage: "Access token expired",
    okPayload: '{"messages":[{"id":"wamid.HBgLMTEy..","status":"accepted"}]}',
    failPayload: '{"error":{"code":190,"message":"Access token has expired"}}',
  },
  cbs: {
    okMessage: "GET /accounts/••••4823 returned in 58 ms",
    failMessage: "mTLS handshake failed",
    okPayload: '{"account":"XXXX4823","balance":42350.00,"emi_due":8500,"next_due":"2026-08-05"}',
    failPayload: '{"error":"tls: bad certificate"}',
  },
  pipecat: {
    okMessage: "Pipeline echo round-trip in 12 ms",
    failMessage: "Worker pool unreachable",
    okPayload: '{"worker":"coll-ai-workers-01","state":"idle","turn_latency_p95_ms":1280}',
    failPayload: '{"error":"connection refused","host":"pipecat.hdfc.internal:8443"}',
  },
};

export function pipecatSnippet(p: Provider, env: Env): string {
  const v = p.perEnv[env].values;
  const secret = (k: string) => `os.environ["${p.id.toUpperCase()}_${k.toUpperCase()}"]  # ${v[k]?.slice(0, 8)}…`;
  switch (p.id) {
    case "azure_speech_stt":
      return `from pipecat.services.azure.stt import AzureSTTService

stt = AzureSTTService(
    api_key=${secret("speechKey")},
    region="${v.region}",
    settings=AzureSTTService.Settings(language="${v.language}"),
)`;
    case "azure_openai":
      return `from pipecat.services.azure import AzureLLMService

llm = AzureLLMService(
    api_key=${secret("apiKey")},
    endpoint="${v.endpoint}",
    api_version="${v.apiVersion}",
    model="${v.deployment}",
)`;
    case "openai":
      return `from pipecat.services.openai import OpenAILLMService

fallback_llm = OpenAILLMService(
    api_key=${secret("apiKey")},
    model="${v.model}",
    organization="${v.org}",
)`;
    case "azure_speech_tts":
      return `from pipecat.services.azure.tts import AzureTTSService

tts = AzureTTSService(
    api_key=${secret("speechKey")},
    region="${v.region}",
    settings=AzureTTSService.Settings(voice="${v.defaultVoice}"),
)`;
    case "twilio":
      return `from pipecat.transports.services.daily import TwilioFrameSerializer
from pipecat.transports.network.fastapi_websocket import FastAPIWebsocketTransport

# Twilio Media Streams webhook mounts this transport
transport = FastAPIWebsocketTransport(
    serializer=TwilioFrameSerializer(
        account_sid="${v.accountSid}",
        auth_token=${secret("authToken")},
        stream_sid=stream_sid,
    ),
)`;
    case "whatsapp":
      return `# Secondary channel — WhatsApp events fan into the same conversation store
WHATSAPP = dict(
    phone_number_id="${v.phoneNumberId}",
    waba_id="${v.wabaId}",
    access_token=${secret("accessToken")},
)`;
    case "cbs":
      return `# Read-only mTLS bridge to HDFC Finacle core
import httpx

cbs = httpx.AsyncClient(
    base_url="${v.baseUrl}",
    cert=("${v.certRef}/cert.pem", "${v.certRef}/key.pem"),
    headers={"x-client-id": "${v.clientId}"},
    timeout=2.0,
)`;
    case "pipecat":
      return `# This CRM's inbound webhook receiver, called by Pipecat after each turn
POST ${v.baseUrl}/webhooks/turn
x-signature: hmac-sha256(${secret("webhookSecret")}, body)

Pipeline([
    transport.input(),   # Twilio
    stt,                 # Azure Speech STT
    llm,                 # Azure OpenAI (fallback → OpenAI)
    tts,                 # Azure Speech TTS
    transport.output(),
]).run(worker_pool="${v.workerPool}")`;
  }
}

export const CATEGORY_LIST: (Category | "All")[] = ["All", "Voice AI", "Messaging", "Telephony", "Core Banking", "Orchestrator"];

export function healthTone(h: HealthStatus) {
  switch (h) {
    case "healthy": return { dot: "bg-emerald-500", text: "text-emerald-700", label: "Healthy" };
    case "degraded": return { dot: "bg-amber-500", text: "text-amber-700", label: "Degraded" };
    case "down": return { dot: "bg-red-500", text: "text-red-700", label: "Down" };
    case "unconfigured": return { dot: "bg-slate-400", text: "text-text-muted", label: "Not configured" };
  }
}
