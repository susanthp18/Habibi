// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// Failed reads on the Outbound tab, which are the ones most worth getting right.
//
// Replaces a source-grep in studio-trust.test.ts that checked this file
// contained "preview.isError", "campaigns.isError" and "stats.isError". All
// three strings are present whatever the branches render; what the grep could
// not see is that the alternative to each is a *number*. "0 of 0 answered" and
// an empty campaign list are claims about the business, and an operator reads
// them as "nothing is going out" rather than "we could not ask".
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AgentCard } from "@/api/agent-card";

const q = vi.hoisted(() => {
  const idle = { data: undefined, isPending: false, isLoading: false, isError: false };
  return {
    stats: { ...idle } as Record<string, unknown>,
    campaigns: { ...idle } as Record<string, unknown>,
    idle,
  };
});

vi.mock("@/api/outbound", () => ({
  useMissions: () => q.idle,
  useOutboundVocabulary: () => q.idle,
  useReachStats: () => q.stats,
  useCampaigns: () => q.campaigns,
  useCadenceCases: () => q.idle,
  useNonpaymentReasons: () => q.idle,
  useObligations: () => q.idle,
  useSetCampaignStatus: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useCreateCampaign: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePreviewCohort: () => q.idle,
  useNumberPools: () => q.idle,
  REASON_LABEL: {},
}));

vi.mock("@/api/agent-studio", () => ({
  useCompilePreview: () => q.idle,
}));

const { OutboundTab } = await import("./OutboundTab");

const CARD = {
  schema_version: "1",
  identity: { bot_id: "kaia-v2-4", slug: "collections", channels: ["voice"] },
  outbound: { direction: "outbound", dials: true, objectives: [], cadences: [] },
} as unknown as AgentCard;

function show(
  pane: "Reach" | "Cadence",
  over: { stats?: Record<string, unknown>; campaigns?: Record<string, unknown> } = {},
) {
  q.stats = { ...q.idle, ...over.stats };
  q.campaigns = { ...q.idle, ...over.campaigns };
  const view = render(<OutboundTab botId="kaia-v2-4" card={CARD} onChange={() => {}} />);
  // The tab opens on Missions; reach figures live under Reach and the campaign
  // book under Cadence.
  fireEvent.click(screen.getByRole("button", { name: new RegExp(pane, "i") }));
  return view;
}

describe("OutboundTab · failed reads", () => {
  it("does not print reach figures as zero when reach could not be read", () => {
    show("Reach", { stats: { isError: true } });

    expect(screen.getByText(/these figures are not zero/i)).toBeInTheDocument();
  });

  it("does not present an unreadable campaign book as an empty one", () => {
    show("Cadence", { campaigns: { isError: true } });

    expect(screen.getByText(/this is not an empty book/i)).toBeInTheDocument();
  });

  it("still says nothing is scheduled when that is actually true", () => {
    // The other half of the same rule: a settled, genuinely empty response
    // must keep reading as empty, or the error copy has just moved the lie.
    show("Cadence", { campaigns: { data: [] }, stats: { data: { attempts: 0, answered: 0 } } });

    expect(screen.queryByText(/this is not an empty book/i)).toBeNull();
    expect(screen.queryByText(/these figures are not zero/i)).toBeNull();
  });
});
