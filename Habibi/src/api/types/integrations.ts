/**
 * Domain / wire types for the integrations surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 */

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
  | "azure_openai"
  | "openai"
  | "azure_speech_stt"
  | "azure_speech_tts"
  | "twilio"
  | "whatsapp"
  | "cbs"
  | "pipecat";
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
  perEnv: Record<
    Env,
    {
      values: Record<string, string>;
      region: string | null;
      health: HealthStatus;
      latencyMs: number;
      enabled: boolean;
      usageStats: UsageStat[];
      costMonth: string;
      unitLabel: string; // "tokens", "minutes", "chars", "messages"…
      /** Live mode: secrets are env/ops-managed — UI must not write them. */
      credentialsLocked?: boolean;
    }
  >;
};
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
