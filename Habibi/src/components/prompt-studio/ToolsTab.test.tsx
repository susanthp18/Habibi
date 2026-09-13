// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// The Tools tab, rendered.
//
// It had no test of any kind. The one that would have mattered is here first:
// `catalogToolsForCard` mapped two of the six channels a card can declare, so a
// card on `sms`, `internal` or `a2a` had its tool list filtered to nothing and
// the tab then printed "The tool catalog is empty" — a claim about the catalog
// produced entirely by the filter, on the one screen where the author's next
// move is to grant a tool.
//
// A source pin could not have caught it. The string "The tool catalog is empty"
// is in the file either way; what differs is whether the user is shown it.
//
// The two data hooks are stubbed rather than served: this repository has no
// request-mocking library and does not need one to answer "given these rows,
// what does the tab render".
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AgentCard } from "@/api/agent-card";

// The shape `GET /flow/tools` returns. The tab renders `key` and `description`;
// there is no `label`.
const CATALOG = [
  {
    key: "get_account_position",
    description: "Read the balance",
    kind: "read",
    channels: ["voice", "text"],
  },
  { key: "capture_lead", description: "Record interest", kind: "write", channels: ["text"] },
  {
    key: "begin_negotiate",
    description: "Move to negotiation",
    kind: "flow_control",
    channels: ["voice"],
  },
];

vi.mock("@/api/flow", () => ({
  useFlowTools: () => ({ data: CATALOG, isPending: false, isError: false }),
}));

vi.mock("@/api/skills", () => ({
  useAgentStudioSkills: () => ({ data: [], isPending: false, isError: false }),
}));

vi.mock("@/api/agent-studio", () => ({
  // The tab asks the compiler for G4/G6 rather than counting for itself; an
  // empty gate list is enough for the rows to render.
  useCompilePreview: () => ({
    data: {
      gates: [],
      idle_voice_tools: 0,
      voice_tool_cap: 12,
      effective_tools: ["get_account_position"],
    },
    isPending: false,
    isError: false,
  }),
}));

const { ToolsTab } = await import("@/components/prompt-studio/AgentCardPanels");

function card(channels: string[]): AgentCard {
  return {
    schema_version: "1",
    identity: {
      bot_id: "kaia-v2-4",
      slug: "collections",
      display_name: "Collections",
      channels,
    },
    tools: { include: ["get_account_position"], locked: [] },
  } as AgentCard;
}

const renderTab = (channels: string[]) =>
  render(<ToolsTab botId="kaia-v2-4" card={card(channels)} />);

describe("Tools tab", () => {
  it("shows the card's tools on voice + whatsapp", () => {
    renderTab(["voice", "whatsapp"]);
    expect(screen.getByText("get_account_position")).toBeInTheDocument();
  });

  it("does not call the catalog empty for a channel the map forgot", () => {
    // `sms` used to fall through the map as itself, match no catalog row, and
    // empty the list. It is not an exotic card — `sms` is in the card's own
    // Channel literal, next to `voice` and `whatsapp`.
    renderTab(["sms"]);
    expect(screen.getByText("get_account_position")).toBeInTheDocument();
    expect(screen.queryByText(/tool catalog is empty/i)).not.toBeInTheDocument();
  });

  it("never offers a flow-control verb as a grantable tool", () => {
    // Adding one makes G4 fail at publish while the tab's own lozenge stays
    // green, because a flow-control verb is not a catalog tool at all.
    renderTab(["voice"]);
    expect(screen.getByText("get_account_position")).toBeInTheDocument();
    expect(screen.queryByText("begin_negotiate")).not.toBeInTheDocument();
  });
});
