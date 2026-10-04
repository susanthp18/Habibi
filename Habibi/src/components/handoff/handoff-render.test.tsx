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
  sessionError: null as unknown,
  queue: undefined as unknown,
  wide: true,
  copilotEvidence: [] as string[],
  rights: new Set(["perm-interactions-write"]),
  me: { id: "me", tenantId: "t-1" },
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
  useRouter: () => ({ buildLocation: () => ({ href: "/upsell" }) }),
}));
vi.mock("sonner", () => ({ toast: { error: q.toastError, success: q.toastSuccess } }));
vi.mock("@/hooks/use-min-width", () => ({ useMinWidth: () => q.wide }));
vi.mock("@/api/me", () => ({
  useMe: () => ({ data: q.me }),
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
  useHandoffQueue: () => ({
    data: q.queue,
    isError: false,
    isRefetchError: false,
    isPlaceholderData: false,
  }),
  useHandoffSession: (id: string) => ({
    data: q.sessions[id],
    isError: q.sessionError != null,
    error: q.sessionError,
    isRefetchError: q.sessionError != null,
    dataUpdatedAt: 0,
  }),
  useClaimHandoff: () => ({ mutate: q.claim, isPending: false, variables: undefined }),
  useRecordDisclosure: () => ({ mutate: q.disclose, isPending: false }),
  useAcceptSuggestion: () => ({ mutate: q.accept }),
  useWrapUpHandoff: () => ({ mutate: q.wrap, isPending: false }),
  useCopilotStream: (_id: string, evidence: string) => (
    q.copilotEvidence.push(evidence),
    {
      whisper: "",
      vetoes: [],
      unavailable: [],
      approvals: [],
      streaming: false,
      done: true,
      error: null,
      refresh: vi.fn(),
    }
  ),
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
      transferOutcome: "no_line",
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
        source: null,
      },
    ],
    alerts: [],
    outcomes: [
      { label: "PTP captured", needs: "promise" },
      { label: "Info provided", needs: "notes" },
    ],
    speakers: { customer: "Synthetic Borrower" },
    wrapUp: null,
    filed: [],
    copilotEvidence: "ev-1",
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
  q.rights = new Set(["perm-interactions-write", "perm-collections-write"]);
  q.me = { id: "me", tenantId: "t-1" };
  q.sessionError = null;
  q.wide = true;
  q.copilotEvidence = [];
  sessionStorage.clear();
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
    expect(screen.getByText(/No callback line — call back/)).toBeTruthy();
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
          transferOutcome: "connected",
        },
      ],
      total: 51,
      mine: [],
    };
    q.queue = queue;
    q.claim.mockImplementation((_vars, opts: { onError: (e: unknown) => void }) =>
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

function queueItem(id: string, name: string) {
  return {
    interactionId: id,
    handoffId: `HO-${id}`,
    customerId: `C-${id}`,
    customerName: name,
    accountId: "",
    reason: "dispute",
    queue: null,
    risk: "low",
    waitSec: 30,
    requestedAt: null,
    transferOutcome: null,
  };
}

describe("Handoff Hub — who may act", () => {
  it("offers no Claim to a viewer who can't change cases", () => {
    q.search = {};
    q.rights = new Set();
    q.queue = { items: [queueItem("IX-9", "Synthetic Caller")], total: 1, mine: [] };
    mount();
    expect(screen.getByText("Synthetic Caller")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Claim/ })).toBeNull();
  });

  it("lists every open case the agent holds, not only the newest", () => {
    q.search = {};
    q.queue = {
      items: [],
      total: 0,
      mine: [queueItem("IX-1", "First Borrower"), queueItem("IX-2", "Second Borrower")],
    };
    mount();
    expect(screen.getByText("Your open cases (2)")).toBeTruthy();
    expect(screen.getByText("First Borrower")).toBeTruthy();
    expect(screen.getByText("Second Borrower")).toBeTruthy();
    expect(screen.getAllByText("Resume")).toHaveLength(2);
  });

  it("makes the holder's case read-only once their role loses write", () => {
    q.rights = new Set();
    mount();
    expect(screen.getByText(/can no longer change cases/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Wrap up" })).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: /Recording disclosure read/ }));
    expect(q.disclose).not.toHaveBeenCalled();
  });

  it("says access is lost instead of showing the stale case as yours", () => {
    q.sessionError = new ApiError("GET", "/handoff/IX-1", 403, "handoff_not_assigned");
    mount();
    expect(screen.getByText(/no longer have access to this case/)).toBeTruthy();
    expect(screen.queryByText("Claimed by you")).toBeNull();
  });

  it("keeps the last snapshot through a server blip", () => {
    q.sessionError = new ApiError("GET", "/handoff/IX-1", 503, "unavailable");
    mount();
    expect(screen.getByText(/Couldn't refresh this case/)).toBeTruthy();
    expect(screen.getByText("Claimed by you")).toBeTruthy();
  });

  it("takes over a colleague's case naming whom it saw holding it", () => {
    q.rights = new Set([
      "perm-interactions-write",
      "perm-supervisor-read",
      "perm-supervisor-write",
    ]);
    q.sessions = {
      "IX-1": session({
        monitor: true,
        activeCall: { ...session().activeCall, agentName: "Asha", handlerUserId: "asha" },
      }),
    };
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Take over case" }));
    expect(q.claim).toHaveBeenCalledWith(
      { interactionId: "IX-1", expectedAssigneeId: "asha" },
      expect.anything(),
    );
  });
});

describe("Handoff Hub — closing and after", () => {
  it("refuses a promise dated before today and a callback already past", () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Wrap up" }));
    const save = screen.getByRole("button", { name: "Save wrap-up" }) as HTMLButtonElement;
    fireEvent.click(screen.getByRole("combobox", { name: "Outcome" }));
    fireEvent.click(screen.getByRole("option", { name: "PTP captured" }));
    fireEvent.change(screen.getByLabelText("Amount (₹)"), { target: { value: "1500" } });
    fireEvent.change(screen.getByLabelText("Promised for"), { target: { value: "2020-01-01" } });
    expect(save.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Promised for"), { target: { value: "2999-01-01" } });
    expect(save.disabled).toBe(false);
  });

  it("keeps unsaved notes when the agent leaves the case and comes back", () => {
    const first = mount();
    fireEvent.click(screen.getByRole("button", { name: "Wrap up" }));
    fireEvent.change(screen.getByLabelText(/Notes/), { target: { value: "customer will call" } });
    first.unmount();
    mount();
    expect(screen.getByDisplayValue("customer will call")).toBeTruthy();
  });

  it("shows how a closed case was wrapped up and what it filed", () => {
    q.sessions = {
      "IX-1": session({
        status: "completed",
        wrapUp: { outcome: "PTP captured", notes: "pays Friday", at: null, byUserId: "me" },
        filed: [{ kind: "promise", id: "PTP-7" }],
      }),
    };
    mount();
    expect(screen.getByText("Wrapped up: PTP captured")).toBeTruthy();
    expect(screen.getByText("pays Friday")).toBeTruthy();
    expect(screen.getByText("Promise PTP-7")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Wrap up" })).toBeNull();
  });

  it("redrafts the copilot from the case's evidence version", () => {
    mount();
    expect(q.copilotEvidence).toContain("ev-1");
  });

  it("moves between the narrow-screen tabs with the arrow keys", () => {
    q.wide = false;
    mount();
    const context = screen.getByRole("tab", { name: "Context" });
    fireEvent.keyDown(context, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Suggest" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(context, { key: "End" });
    expect(screen.getByRole("tab", { name: "Compliance" }).getAttribute("aria-selected")).toBe(
      "true",
    );
  });
});

describe("Handoff Hub — round three", () => {
  it("shows the bot's disclosure as the bot's evidence, which can't be unticked", () => {
    q.sessions = {
      "IX-1": session({
        complianceItems: [
          {
            id: "rule-recording",
            label: "Recording disclosure read",
            required: true,
            checked: true,
            locked: true,
            ruleId: "rule-recording",
            source: "bot",
          },
        ],
      }),
    };
    mount();
    expect(screen.getByText("said by the bot")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: /Recording disclosure read/ }));
    expect(q.disclose).not.toHaveBeenCalled();
  });

  it("offers no outcome that files a record to a role that can't file one", () => {
    q.rights = new Set(["perm-interactions-write"]);
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Wrap up" }));
    fireEvent.click(screen.getByRole("combobox", { name: "Outcome" }));
    const ptp = screen.getByRole("option", { name: /PTP captured/ });
    expect(ptp.getAttribute("aria-disabled") ?? ptp.getAttribute("data-disabled")).not.toBeNull();
    expect(
      screen.getByRole("option", { name: "Info provided" }).getAttribute("aria-disabled"),
    ).not.toBe("true");
  });

  it("accepts a promise in rupees and paise, and nothing finer", () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Wrap up" }));
    fireEvent.click(screen.getByRole("combobox", { name: "Outcome" }));
    fireEvent.click(screen.getByRole("option", { name: "PTP captured" }));
    const amount = screen.getByLabelText("Amount (₹)") as HTMLInputElement;
    const save = screen.getByRole("button", { name: "Save wrap-up" }) as HTMLButtonElement;
    fireEvent.change(screen.getByLabelText("Promised for"), { target: { value: "2999-01-01" } });
    fireEvent.change(amount, { target: { value: "1500.50" } });
    expect(save.disabled).toBe(false);
    expect(amount.validity.stepMismatch).toBe(false);
    fireEvent.change(amount, { target: { value: "1500.555" } });
    expect(save.disabled).toBe(true);
  });

  it("never shows one operator's unsaved notes to another in the same tab", () => {
    const first = mount();
    fireEvent.click(screen.getByRole("button", { name: "Wrap up" }));
    fireEvent.change(screen.getByLabelText(/Notes/), { target: { value: "private note" } });
    first.unmount();
    q.me = { id: "someone-else", tenantId: "t-1" };
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Wrap up" }));
    expect(screen.queryByDisplayValue("private note")).toBeNull();
  });

  it("drops the unsaved notes once the case is no longer the operator's", () => {
    const first = mount();
    fireEvent.click(screen.getByRole("button", { name: "Wrap up" }));
    fireEvent.change(screen.getByLabelText(/Notes/), { target: { value: "half a note" } });
    first.unmount();
    q.sessionError = new ApiError("GET", "/handoff/IX-1", 403, "handoff_not_assigned");
    mount().unmount();
    q.sessionError = null;
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Wrap up" }));
    expect(screen.queryByDisplayValue("half a note")).toBeNull();
  });

  it("lets anyone on the queue look at a waiting case before claiming", () => {
    q.search = {};
    q.rights = new Set();
    q.queue = { items: [queueItem("IX-9", "Synthetic Caller")], total: 1, mine: [] };
    mount();
    expect(
      within(screen.getByText("Synthetic Caller").closest("li")!).getByText("View"),
    ).toBeTruthy();
  });

  it("gives a held case its age, not a wait", () => {
    q.search = {};
    q.queue = { items: [], total: 0, mine: [queueItem("IX-1", "First Borrower")] };
    mount();
    expect(screen.getByText("case open 30s")).toBeTruthy();
    expect(screen.queryByText(/waiting 30s/)).toBeNull();
  });

  it("says the list is the previous one while a new search loads", () => {
    q.search = {};
    q.queue = { items: [queueItem("IX-9", "Synthetic Caller")], total: 1, mine: [] };
    mount();
    fireEvent.change(screen.getByPlaceholderText(/Customer name/), { target: { value: "asha" } });
    expect(screen.getByText("Searching…")).toBeTruthy();
    expect(screen.queryByText(/No waiting case matches/)).toBeNull();
  });
});

describe("SentimentMeter", () => {
  it("shows movement as a change in score, not a percentage", async () => {
    const { SentimentMeter } = await import("./SentimentMeter");
    render(<SentimentMeter series={[-0.5, -0.2]} />);
    expect(screen.getByText("+0.30")).toBeTruthy();
    expect(screen.queryByText(/%/)).toBeNull();
  });
});
