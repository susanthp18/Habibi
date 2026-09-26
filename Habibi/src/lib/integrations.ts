import type {
  Env,
  HealthStatus,
  Category,
  ProviderField,
  ProviderId,
  UsageStat,
  Provider,
  TestLogEntry,
} from "@/api/types/integrations";

export const LIVE_PROVIDER_IDS: ProviderId[] = [
  "azure_openai",
  "azure_speech_stt",
  "azure_speech_tts",
  "twilio",
  "whatsapp",
];

export function pipecatSnippet(p: Provider, env: Env): string {
  const v = p.perEnv[env].values;
  const secret = (k: string) =>
    `os.environ["${p.id.toUpperCase()}_${k.toUpperCase()}"]  # ${v[k]?.slice(0, 8)}…`;
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
      return `# Read-only mTLS bridge to BigTapp Finacle core
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

export const CATEGORY_LIST: (Category | "All")[] = [
  "All",
  "Voice AI",
  "Messaging",
  "Telephony",
  "Core Banking",
  "Orchestrator",
];

export function healthTone(h: HealthStatus) {
  switch (h) {
    case "healthy":
      return {
        dot: "bg-background-success-bold",
        text: "text-text-success-bolder",
        label: "Healthy",
      };
    case "degraded":
      return {
        dot: "bg-background-warning-bold",
        text: "text-text-warning-bolder",
        label: "Degraded",
      };
    case "down":
      return { dot: "bg-background-danger-bold", text: "text-text-danger-bolder", label: "Down" };
    case "unconfigured":
      return {
        dot: "bg-background-accent-gray-subtle",
        text: "text-text-subtlest",
        label: "Not configured",
      };
  }
}
