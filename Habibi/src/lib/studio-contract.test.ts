import { describe, expect, it } from "vitest";
import {
  catalogToolsForCard,
  compileReportSchema,
  controlKind,
  flowToolChoices,
  parseEffectiveContract,
  sandboxToolKind,
} from "./studio-contract";


describe("studio compiled contract", () => {
  it("labels ext.* as unsupported on voice", () => {
    expect(
      controlKind({
        channel: "voice",
        tool: "ext.paylink.get_status",
        allowed: ["ext.paylink.get_status"],
      }),
    ).toBe("unsupported");
    expect(
      controlKind({
        channel: "text",
        tool: "ext.paylink.get_status",
        allowed: ["ext.paylink.get_status"],
      }),
    ).toBe("runtime");
  });

  it("hides flow-control verbs from the Tools tab", () => {
    const rows = [
      { key: "create_promise_to_pay", kind: "catalog" },
      { key: "begin_negotiate", kind: "flow_control" },
    ];
    expect(catalogToolsForCard(rows).map((r) => r.key)).toEqual(["create_promise_to_pay"]);
  });

  it("intersects Flow choices with the compiled grant", () => {
    const rows = [
      { key: "create_promise_to_pay", kind: "catalog" },
      { key: "flag_dispute", kind: "catalog" },
      { key: "begin_negotiate", kind: "flow_control" },
    ];
    expect(flowToolChoices(rows, ["create_promise_to_pay"]).map((r) => r.key)).toEqual([
      "create_promise_to_pay",
      "begin_negotiate",
    ]);
    expect(flowToolChoices(rows, []).map((r) => r.key)).toEqual(["begin_negotiate"]);
  });

  // /flow/tools used to be filtered to voice on the server, which is why the
  // two text-only specs could be granted from nowhere: absent from the palette,
  // so on no card, so refused by the runtime — while the WhatsApp system prompt
  // named one of them on every turn. It now serves every channel and each
  // picker filters.
  it("keeps a flow node voice-only even though the catalog is not", () => {
    const rows = [
      { key: "create_promise_to_pay", kind: "catalog", channels: ["voice", "text"] },
      { key: "identify_customer", kind: "catalog", channels: ["text"] },
      { key: "begin_negotiate", kind: "flow_control", channels: ["voice"] },
    ];
    expect(flowToolChoices(rows, undefined).map((r) => r.key)).toEqual([
      "create_promise_to_pay",
      "begin_negotiate",
    ]);
  });

  it("shows the Tools tab what the card's own channels can render", () => {
    const rows = [
      { key: "create_promise_to_pay", kind: "catalog", channels: ["voice", "text"] },
      { key: "identify_customer", kind: "catalog", channels: ["text"] },
      { key: "capture_call_goal", kind: "catalog", channels: ["voice"] },
      { key: "begin_negotiate", kind: "flow_control", channels: ["voice"] },
    ];
    // The card vocabulary spells the text channel "whatsapp"; the catalog
    // spells it "text".
    expect(catalogToolsForCard(rows, ["voice", "whatsapp"]).map((r) => r.key)).toEqual([
      "create_promise_to_pay",
      "identify_customer",
      "capture_call_goal",
    ]);
    expect(catalogToolsForCard(rows, ["voice"]).map((r) => r.key)).toEqual([
      "create_promise_to_pay",
      "capture_call_goal",
    ]);
    // No channels given means "do not filter", so every existing caller keeps
    // behaving as it did.
    expect(catalogToolsForCard(rows).map((r) => r.key)).toHaveLength(3);
  });

  it("parses an effective-contract payload", () => {
    const parsed = parseEffectiveContract({
      source: "preview",
      botId: "kaia-v2-4",
      compiled: {
        schema_version: "1",
        bot_id: "kaia-v2-4",
        bundle_hash: "abc",
      },
    });
    expect(parsed.success).toBe(true);
  });

  it("accepts a dry compile report whose bundle is still empty", () => {
    const parsed = compileReportSchema.safeParse({
      bot_id: "kaia-v2-4",
      gates: [{ gate: "G0", name: "schema", status: "pass", detail: "", issues: [] }],
      effective_tools: [],
      idle_tools: [],
      idle_voice_tools: 0,
      voice_tool_cap: 8,
      skill_description_tokens: 0,
      card: {},
      bundle: {},
    });
    expect(parsed.success).toBe(true);
  });

  it("labels sandbox results as simulated", () => {
    expect(sandboxToolKind({ simulated: true })).toBe("simulated");
    expect(sandboxToolKind({ simulated: true, error: "sandbox_connector_blocked" })).toBe(
      "unsupported",
    );
  });

  // Six assertions stood here, each reading a component's source and checking
  // for a substring. Every one of them passed on a string in a comment, on dead
  // markup, or on a branch no reader reaches — and one of them (`toContain
  // ("simulated")`) was passing on the inspector's *empty-state* sentence while
  // saying nothing at all about what a tool call rendered.
  //
  // They are now rendered assertions, next to the components they describe:
  //   ShipTab.tsx                      -> ShipTab.test.tsx
  //   AgentCardPanels.tsx (Tools)      -> ToolsTab.test.tsx
  //   sandbox/inspector/ToolsTab.tsx   -> sandbox/inspector/ToolsTab.test.tsx
  //   sandbox/SandboxHeader.tsx        -> sandbox/SandboxHeader.test.tsx
  //   api/agent-studio.ts (zip revoke) -> api/agent-studio.export.test.ts
  //
  // `check-no-source-grep-tests.mjs` keeps this file out of the ALLOWED set.
});
