# Vault inventory

Phase 3: connector OAuth and MCP keys live in `vault_refs`. LLM / Twilio /
WhatsApp keys can move here next; until then they stay in the platform secret
store. The UI never returns ciphertext or a token field.

Local backend: HMAC-SHA256 CTR + HMAC tag sealed with `VAULT_MASTER_KEY`
(falls back to `SKILL_PLATFORM_KEY`). Azure Key Vault when
`AZURE_KEY_VAULT_URL` + `AZURE_KEY_VAULT_TOKEN` are set — the row stores the
secret **name**, not `vault://…` placeholder strings.

Rotation is `POST /vault/refs/{ref_id}/rotate`. No deploy.

| Secret | Typical env | Used by | Destination |
|---|---|---|---|
| Connector OAuth / MCP client secret | — (never `.env`) | Remote MCP `auth_ref` | `vault_refs` (`connector_oauth`) |
| Minted MCP HTTP keys | hash in `mcp_keys` | HTTP MCP auth | hash only; raw shown once at mint |
| Bootstrap MCP key | `MCP_API_KEY` | HTTP MCP until a DB key exists | Key Vault + mTLS; read scopes only |
| Azure OpenAI key | `AZURE_OPENAI_API_KEY` | Chat, embeddings, analysis | Key Vault ref (next) |
| Azure OpenAI voice key | `AZURE_OPENAI_VOICE_API_KEY` | Pipecat mouth | same, `voice` profile |
| Azure Speech key | `AZURE_SPEECH_KEY` | STT / TTS | Key Vault |
| Twilio auth token | `TWILIO_AUTH_TOKEN` | PSTN, SMS | Key Vault |
| WhatsApp token | `WHATSAPP_TOKEN` | Cloud API | Key Vault |
| WhatsApp app secret | `WHATSAPP_APP_SECRET` | webhook verify | Key Vault |
| Postgres password | `POSTGRES_PASSWORD` / `DATABASE_URL` | API, workers | stay in platform secret store |
| MinIO keys | `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | KB originals | platform secret store |
| API keys | `API_KEY`, `API_KEY_MAP` | Habibi → API | platform secret store |
| Voice WS proxy secret | `VOICE_WS_PROXY_SECRET` | Twilio Media Streams | platform secret store |
| Payment webhook HMAC | `PAYMENT_WEBHOOK_SECRET` | pay-link callbacks | `vault_refs` (`webhook`) |
| Payment events HMAC | `PAYMENT_EVENTS_WEBHOOK_SECRET` | bounce ingest | `vault_refs` (`webhook`) |
| Redis URL | `REDIS_URL` | mesh bus, optional queues | platform secret store |
| Vault master (local) | `VAULT_MASTER_KEY` | seal/open `vault_refs.ciphertext` | platform secret store |
| Azure Key Vault token | `AZURE_KEY_VAULT_TOKEN` | Azure backend | platform secret store |

See `agent_transformation_implementation.md` Phase 3.
