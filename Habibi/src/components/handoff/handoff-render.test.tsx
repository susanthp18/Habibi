// @vitest-environment jsdom
import "@/test/jsdom";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/config";
import type { HandoffQueue, HandoffSession } from "@/api/handoff";

const q = vi.hoisted(() => ({
  search: {} as { interactionId?: string; mode?: "monitor" },
  navigate: vi.fn(),
  sessions: {} as Record<string, unknown>,
  queue: undefined as unknown,
  rights: new Set(["perm-interactions-write"]),
  claim: vi.fn(),
  disclose: vi.fn(),
  accept: vi.fn(),
  wrap: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@tanstack/react-router", () => ({
  createLazyFileRoute: () => (opts: Record<string, unknown>) => ({
    ...opts,
    useSearch: () => q.search,
  }),
  Link: ({ children }: { children: ReactNode }) => <span>{children}</span>,
  useNavigate: () => q.navigate,
}));
vi.mock("sonner", () => ({ toast: { error: q.toastError, success: q.toastSuccess } }));
vi.mock("@/hooks/use-min-width", () => ({ useMinWidth: () => true }));
vi.mock("@/api/me", () => ({
  useMe: () => ({ data: { id: "me" } }),
  can: (_me: unknown, perm: string) => q.rights.has(perm),
}));
vi.mock("@/api/contact-policy", () => ({
  useContactPolicy: () => ({ data: { allowed: true }, isPending: false, isError: false }),
}));
vi.mock("@/api/inbox", () => ({
  useCannedResponses: () => ({ data: [], isError: false }),
}));
vi.mock("@/api/floor", () => ({
  postSupervisorAction: vi.fn(),
  signalFloorApproval: vi.fn(),
  useAckFloorAlert: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/api/upsell", () => ({ useCaptureLeadFromPolicy: () => ({ mutate: vi.fn() }) }));
vi.mock("@/api/authority", () => ({ useApplyAuthority: () => ({ mutate: vi.fn() }) }));
vi.mock("@/api/handoff", () => ({
  useHandoffQueue: () => ({ data: q.queue, isError: false, isRefetchError: false }),
  useHandoffSession: (id: string) => ({
    data: q.sessions[id],
    isError: false,
    isRefetchError: false,
  }),
  useClaimHandoff: () => ({ mutate: q.claim, isPending: false, variables: undefined }),
  useRecordDisclosure: () => ({ mutate: q.disclose, isPending: false }),
  useAcceptSuggestion: () => ({ mutate: q.accept }),
  useWrapUpHandoff: () => ({ mutate: q.wrap, isPending: false }),
  useCopilotStream: () => ({
    whisper: "",
    vetoes: [],
    unavailable: [],
    approvals: [],
    streaming: false,
    done: true,
    error: null,
    refresh: vi.fn(),
  }),
}));

const { Route } = await import("@/routes/_app.handoff.lazy");
const Page = (Route as unknown as { component: () => ReactNode }).component;

function session(over: Partial<HandoffSession> = {}, id = "IX-1"): HandoffSession {
  return {
    interactionId: id,
    handoffId: `HO-${id}`,
    customerId: "C-1",
    conversationId: null,
    status: "active",
    claimed: true,
    monitor: false,
    activeCall: {
      interactionId: id,
      handoffId: `HO-${id}`,
      customerId: "C-1",
      conversationId: null,
      customerName: "Synthetic  Borrower",
      accountId: "ACC-1",
      phone: "",
      channel: "Voice",
      agentName: "You",
      transferredFrom: "Bot · Kaia",
      escalationReason: "dispute",
      startedAt: 0,
      status: "active",
      claimed: true,
      risk: "medium",
      handlerUserId: "me",
      requestedAt: "2026-10-03T10:00:00Z",
      callState: "ended",
      callEndedAt: "2026-10-03T10:05:00Z",
      transferOutcome: "no_one_available",
    },
    customerContext: {
      risk: "Medium",
      outstanding: null,
      currency: "₹",
      lastPromise: null,
      nextEmi: null,
      openDisputes: 0,
      tenureMonths: 0,
      product: "",
      offerPolicy: null,
      authorityPolicy: null,
    },
    transcriptScript: [
      { id: "T-1", speaker: "customer", text: "I want a person", at: 4, sentimentDelta: null },
    ],
    sentimentSeries: [],
    suggestions: [
      {
        id: "S-1",
        title: "Suggested response",
        body: "Offer a call back",
        source: "kb",
        accepted: false,
        stale: true,
      },
    ],
    complianceItems: [
      {
        id: "rule-recording",
        label: "Recording disclosure read",
        required: true,
        checked: false,
        locked: false,
        ruleId: "rule-recording",
      },
    ],
    alerts: [],
    outcomes: [
      { label: "PTP captured", needs: "promise" },
      { label: "Info provided", needs: "notes" },
    ],
    speakers: { customer: "Synthetic Borrower" },
    ...over,
  };
}

function mount() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <Page />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  q.search = { interactionId: "IX-1" };
  q.sessions = { "IX-1": session(), "IX-2": session({}, "IX-2") };
  q.rights = new Set(["perm-interactions-write"]);
  for (const fn of [q.claim, q.disclose, q.accept, q.wrap, q.toastError, q.navigate])
    fn.mockReset();
});

describe("Handoff Hub — the case, not a call", () => {
  it("offers no call controls and claims nothing is live", () => {
    mount();
    for (const name of [/mute/i, /hold/i, /transfer/i, /end call/i]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.queryByText(/^Live$/)).toBeNull();
    expect(screen.queryByText(/streaming/i)).toBeNull();
    expect(screen.getByText(/No one was available — call back/)).toBeTruthy();
  });

  it("says sentiment is not available instead of drawing one", () => {
    mount();
    expect(screen.getByText("Not available for this call.")).toBeTruthy();
  });

  it("shows a missing balance as unknown and an unreadable policy as unavailable", () => {
    mount();
    expect(screen.queryByText("₹0")).toBeNull();
    expect(screen.getByText(/Couldn't load the authority decision/)).toBeTruthy();
  });

  it("copies a suggestion without writing a transcript line", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: write } });
    mount();
    expect(screen.getByText("Earlier message")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await vi.waitFor(() => expect(q.accept).toHaveBeenCalledWith("S-1", expect.anything()));
    expect(write).toHaveBeenCalledWith("Offer a call back");
    expect(screen.getAllByText("Offer a call back")).toHaveLength(1);
    expect(screen.queryByText(/speak this/i)).toBeNull();
  });

  it("keeps a refused disclosure unticked and says why", () => {
    q.disclose.mockImplementation((_vars, opts: { onError: (e: unknown) => void }) =>
      opts.onError(new ApiError("POST", "/handoff/IX-1/disclosures", 403, "handoff_not_assigned")),
    );
    mount();
    const box = screen.getByRole("checkbox", { name: /Recording disclosure read/ });
    fireEvent.click(box);
    expect(box.getAttribute("aria-checked")).toBe("false");
    expect(q.toastError).toHaveBeenCalledWith(expect.stringMatching(/isn't yours/));
  });
});

describe("Handoff Hub — wrap-up", () => {
  it("has no default outcome, so nothing saves until one is chosen", () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Wrap up" }));
    expect(screen.getByRole("combobox", { name: "Outcome" }).textContent).toBe(
      "Choose what happened",
    );
    const save = screen.getByRole("button", { name: "Save wrap-up" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
  });

  it("can be reopened after it is closed", () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Wrap up" }));
    fireEvent.click(screen.getByRole("button", { name: "Close wrap-up" }));
    expect(screen.getByRole("button", { name: "Wrap up" })).toBeTruthy();
  });

  it("starts clean on the next case", () => {
    const view = mount();
    fireEvent.click(screen.getByRole("button", { name: "Wrap up" }));
    fireEvent.change(screen.getByLabelText(/Notes/), { target: { value: "typed for case one" } });
    q.search = { interactionId: "IX-2" };
    view.rerender(
      <QueryClientProvider client={new QueryClient()}>
        <Page />
      </QueryClientProvider>,
    );
    expect(screen.queryByDisplayValue("typed for case one")).toBeNull();
    expect(screen.getByRole("button", { name: "Wrap up" })).toBeTruthy();
  });
});

describe("Handoff Hub — watching and claiming", () => {
  it("is read-only for a supervisor watching someone's case", () => {
    q.rights = new Set(["perm-interactions-write", "perm-supervisor-read"]);
    q.sessions = {
      "IX-1": session({
        monitor: true,
        activeCall: { ...session().activeCall, agentName: "Asha" },
      }),
    };
    mount();
    expect(screen.getByText(/Watching Asha's case — read-only/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Wrap up" })).toBeNull();
    expect(screen.queryByRole("button", { name: /take over/i })).toBeNull();
    const box = screen.getByRole("checkbox", { name: /Recording disclosure read/ });
    fireEvent.click(box);
    expect(q.disclose).not.toHaveBeenCalled();
  });

  it("shows a failed claim on its queue row", () => {
    q.search = {};
    const queue: HandoffQueue = {
      items: [
        {
          interactionId: "IX-9",
          handoffId: "HO-9",
          customerId: "C-9",
          customerName: "Synthetic Caller",
          accountId: "ACC-9",
          reason: "dispute",
          queue: null,
          risk: "low",
          waitSec: 700,
          requestedAt: null,
          transferOutcome: "callback_line",
        },
      ],
      total: 51,
      activeInteractionId: null,
    };
    q.queue = queue;
    q.claim.mockImplementation((_id, opts: { onError: (e: unknown) => void }) =>
      opts.onError(new ApiError("POST", "/handoff/IX-9/claim", 409, "handoff_already_claimed")),
    );
    mount();
    expect(screen.getByText("Oldest 1 of 51")).toBeTruthy();
    const row = screen.getByText("Synthetic Caller").closest("li")!;
    fireEvent.click(within(row).getByRole("button", { name: /Claim/ }));
    expect(within(row).getByRole("alert").textContent).toMatch(/Someone else claimed/);
  });
});

describe("waitWords", () => {
  it("says how long, in the largest unit that reads", async () => {
    const { waitWords } = await import("./handoff-words");
    expect(waitWords(45)).toBe("45s");
    expect(waitWords(125)).toBe("2m 5s");
    expect(waitWords(3 * 3600 + 600)).toBe("3h 10m");
    expect(waitWords(74 * 86400 + 5 * 3600)).toBe("74d 5h");
  });
});
