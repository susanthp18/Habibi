/**
 * Compiled-contract helpers for Agent Studio. Kept out of React so vitest
 * (node, no jsdom) can pin the states the Effective-contract view renders.
 */
import { z } from "zod";

export type ControlKind = "runtime" | "simulated" | "compile-only" | "unsupported";

export const compiledBundleSchema = z
  .object({
    schema_version: z.string(),
    bot_id: z.string(),
    prompt_version_id: z.string().nullable().optional(),
    bundle_hash: z.string(),
    grants: z
      .array(
        z.object({
          channel: z.enum(["voice", "text"]),
          allowed: z.array(z.string()),
          offered: z.array(z.string()),
        }),
      )
      .optional(),
    skills: z
      .array(
        z.object({
          skill_id: z.string(),
          version: z.string(),
          pin: z.string().optional(),
          content_hash: z.string().optional(),
          signed: z.boolean().optional(),
          mouth: z.array(z.string()).optional(),
        }),
      )
      .optional(),
    connectors: z
      .array(
        z.object({
          connector_id: z.string(),
          allow_prefixes: z.array(z.string()).optional(),
          tool_names: z.array(z.string()).optional(),
          digest: z.string().optional(),
          voice_supported: z.boolean().optional(),
        }),
      )
      .optional(),
    human_gates: z.array(z.record(z.unknown())).optional(),
    hashes: z
      .object({
        prompt: z.string(),
        persona: z.string(),
        guardrails: z.string(),
        flow: z.string(),
        card: z.string(),
      })
      .optional(),
    prompt: z.string().optional(),
    persona: z.record(z.unknown()).optional(),
    guardrails: z.record(z.unknown()).optional(),
    flow: z.record(z.unknown()).optional(),
    agent_card: z.record(z.unknown()).optional(),
  })
  .passthrough();

export const effectiveContractSchema = z
  .object({
    source: z.enum(["published", "preview"]),
    botId: z.string(),
    promptVersionId: z.string().nullable().optional(),
    compiled: compiledBundleSchema.or(z.record(z.unknown())),
    gates: z.array(z.unknown()).optional(),
  })
  .passthrough();

export const compileReportSchema = z
  .object({
    bot_id: z.string(),
    gates: z.array(
      z
        .object({
          gate: z.string(),
          name: z.string(),
          status: z.enum(["pass", "fail", "warn", "skipped"]),
          detail: z.string(),
          issues: z.array(z.unknown()),
        })
        .passthrough(),
    ),
    effective_tools: z.array(z.string()),
    idle_tools: z.array(z.string()),
    idle_voice_tools: z.number(),
    voice_tool_cap: z.number(),
    skill_description_tokens: z.number(),
    card: z.record(z.unknown()),
    // Dry CompileReport.bundle defaults to {} before fleet wrapping.
    bundle: compiledBundleSchema.or(z.object({}).strict()).optional(),
  })
  .passthrough();

export const sandboxToolResultSchema = z
  .object({
    ok: z.boolean(),
    simulated: z.boolean().optional(),
    error: z.string().optional(),
    effect: z.string().optional(),
    notice: z.string().optional(),
  })
  .passthrough();

export const sandboxTurnResultSchema = z
  .object({
    runId: z.string(),
    promptVersionId: z.string(),
    compiledBundleHash: z.string().nullable().optional(),
    flowStatus: z
      .enum(["validated_not_executed_in_text_rehearsal", "not_authored"])
      .nullable()
      .optional(),
    customerTurn: z
      .object({
        id: z.string(),
        role: z.literal("customer"),
        text: z.string(),
        intent: z.string(),
        intentScores: z.record(z.number()),
        sentiment: z.number(),
        sentimentLabel: z.enum(["positive", "neutral", "negative"]),
      })
      .passthrough(),
    botTurn: z
      .object({
        id: z.string(),
        role: z.literal("bot"),
        text: z.string(),
        chunkIds: z.array(z.string()),
        chunks: z.array(
          z
            .object({
              chunkId: z.string(),
              docId: z.string().nullable().optional(),
              docTitle: z.string().nullable().optional(),
              heading: z.string().nullable().optional(),
              snippet: z.string().nullable().optional(),
              score: z.number().nullable().optional(),
            })
            .passthrough(),
        ),
        latencyMs: z.number(),
        tokens: z.number(),
        guardrailFlags: z.array(z.string()),
        intent: z.string(),
        sentiment: z.number(),
        sentimentLabel: z.enum(["positive", "neutral", "negative"]),
        retrievalLogId: z.string().nullable().optional(),
        retrieveLatencyMs: z.number().nullable().optional(),
        chatLatencyMs: z.number().nullable().optional(),
        halted: z.boolean().optional(),
        toolCalls: z
          .array(
            z
              .object({
                name: z.string(),
                ok: z.boolean(),
                simulated: z.boolean().optional(),
                result: z.unknown().optional(),
              })
              .passthrough(),
          )
          .optional(),
      })
      .passthrough(),
  })
  .passthrough();

export function parseEffectiveContract(raw: unknown) {
  return effectiveContractSchema.safeParse(raw);
}

export function parseCompiledBundle(raw: unknown) {
  return compiledBundleSchema.safeParse(raw);
}

export function controlKind(opts: {
  channel?: "voice" | "text";
  tool: string;
  allowed: string[];
  voiceSupported?: boolean;
}): ControlKind {
  if (opts.tool.startsWith("ext.") && opts.channel === "voice") return "unsupported";
  if (!opts.allowed.includes(opts.tool)) return "unsupported";
  return "runtime";
}

export function connectorKind(
  voiceSupported: boolean | undefined,
  channel: "voice" | "text",
): ControlKind {
  if (channel === "voice" && voiceSupported !== true) return "unsupported";
  return "runtime";
}

export function sandboxToolKind(
  result: { simulated?: boolean; error?: string } | null,
): ControlKind {
  if (!result) return "compile-only";
  if (result.error && result.simulated) return "unsupported";
  if (result.simulated) return "simulated";
  return "runtime";
}

type CatalogRow = { key: string; kind?: string; channels?: string[]; alwaysOn?: boolean };

/**
 * Tools tab rows: no zero-argument flow-control verbs, and only tools the
 * card's own channels can render.
 *
 * `/flow/tools` used to be filtered to voice on the server, which is why the
 * two text-only specs could be granted from nowhere. It now returns every
 * channel and each picker filters — so this one needs to know what the card
 * declares. `undefined` channels means "do not filter", which keeps every
 * existing caller behaving as it did.
 *
 * The card's vocabulary spells the text channel "whatsapp"; the catalog spells
 * it "text". Mapped here rather than in either vocabulary, because both are
 * right in their own file.
 */
export function catalogToolsForCard<T extends CatalogRow>(rows: T[], cardChannels?: string[]): T[] {
  const withoutFlowControl = rows.filter((t) => t.kind !== "flow_control");
  if (!cardChannels?.length) return withoutFlowControl;
  const wanted = new Set(cardChannels.map((c) => (c === "whatsapp" || c === "chat" ? "text" : c)));
  return withoutFlowControl.filter(
    (t) => !t.channels?.length || t.channels.some((c) => wanted.has(c)),
  );
}

/**
 * Flow picker = catalog ∪ flow-control, on voice, intersected with the compiled
 * grant when one is known.
 *
 * A flow node is a voice node, so a text-only spec is never a choice here even
 * though the catalog now carries it.
 */
export function flowToolChoices<T extends CatalogRow>(rows: T[], grant: string[] | undefined): T[] {
  const voice = rows.filter((t) => !t.channels?.length || t.channels.includes("voice"));
  if (!grant) return voice;
  const allowed = new Set(grant);
  return voice.filter((t) => t.kind === "flow_control" || allowed.has(t.key));
}

export function controlKindLabel(kind: ControlKind): string {
  if (kind === "runtime") return "runtime";
  if (kind === "simulated") return "simulated";
  if (kind === "compile-only") return "compile-only";
  return "unsupported";
}
