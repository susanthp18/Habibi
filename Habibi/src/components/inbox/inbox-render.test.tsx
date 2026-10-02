// @vitest-environment jsdom
import "@/test/jsdom";

import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/config";
import type { Thread, ThreadSummary } from "@/api/types/inbox";

const q = vi.hoisted(() => ({
  search: {} as { conversationId?: string },
  navigate: vi.fn(),
  threads: [] as unknown[],
  details: {} as Record<string, unknown>,
  send: vi.fn(),
  rights: new Set(["perm-interactions-write"]),
}));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (opts: Record<string, unknown>) => ({
    ...opts,
    useSearch: () => q.search,
  }),
  Link: ({ children }: { children: ReactNode }) => <span>{children}</span>,
  useNavigate: () => q.navigate,
}));
vi.mock("@/api/me", () => ({
  useMe: () => ({ data: { id: "me" } }),
  can: (_me: unknown, perm: string) => q.rights.has(perm),
}));
vi.mock("@/api/contact-policy", () => ({
  useContactPolicy: () => ({ data: { allowed: true }, isPending: false, isError: false }),
}));
vi.mock("@/lib/use-debounced", () => ({ useDebounced: (v: string) => v }));
vi.mock("@/api/inbox", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/inbox")>()),
  useConversations: () => ({ data: q.threads, isPending: false, isError: false }),
  useConversation: (id: string | undefined) => ({
    data: id ? q.details[id] : undefined,
    isPending: false,
    isError: false,
    error: null,
  }),
  useCannedResponses: () => ({
    data: [{ id: "c1", label: "Pay link", text: "Here is your pay link." }],
    isPending: false,
    isError: false,
  }),
  sendConversationMessage: (...args: unknown[]) => q.send(...args),
  refreshConversationSuggestions: () => new Promise(() => {}),
}));

const { Composer } = await import("./Composer");
const { ChatThread } = await import("./ChatThread");
const { ConversationList } = await import("./ConversationList");
const { inboxErrorWords } = await import("./inbox-words");
const { Route } = await import("@/routes/_app.inbox");

const agent = { canWrite: true, canReassign: false, canFileDocuments: true };

function summary(over: Partial<ThreadSummary> = {}): ThreadSummary {
  return {
    id: "CV-A",
    customer: "Synthetic Borrower",
    customerId: "C-1",
    accountId: "ACC-1",
    channel: "whatsapp",
    status: "assigned",
    isMine: true,
    assignedUserId: "me",
    awaitingReply: 0,
    sla: "ok",
    lastTime: "3:41 PM",
    lastPreview: "hello",
    lastFrom: "customer",
    sentiment: "neutral",
    ...over,
  } as ThreadSummary;
}

function thread(over: Partial<Thread> = {}, context: Partial<Thread["context"]> = {}): Thread {
  return {
    ...summary(),
    messages: [
      { id: "M-1", sender: "customer", text: "hello", time: "3:41 PM", at: "2026-10-02T10:11:00Z" },
    ],
    ragSuggestions: [],
    ragDraftAnswer: null,
    context: {
      riskLevel: "Low",
      canReply: true,
      replyBlockedReason: null,
      replyWindowEndsAt: null,
      contactWindow: "09:00-19:00",
      outstanding: 1000,
      outstandingAging: "Current",
      nextEmiDate: null,
      nextEmiAmount: null,
      nextEmiOverdue: false,
      lastPromise: null,
      openDisputes: [],
      openDisputesTotal: 0,
      recentInteractions: [],
      ...context,
    },
    ...over,
  } as Thread;
}

function composer(props: Partial<Parameters<typeof Composer>[0]> = {}) {
  const onSend = props.onSend ?? vi.fn(async () => true);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Composer
        thread={thread()}
        rights={agent}
        draft=""
        onDraftChange={() => {}}
        onSend={onSend}
        onRefreshRag={() => {}}
        onSuggestReply={async () => null}
        ragSuggestions={[]}
        ragDraft={null}
        ragLoading={false}
        ragError={null}
        ragStale={false}
        ragSearched
        busy={false}
        errorMessage={null}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onSend, box: screen.getByRole("textbox", { name: /reply on whatsapp/i }) };
}

beforeEach(() => {
  q.send.mockReset();
  q.navigate.mockReset();
  q.rights = new Set(["perm-interactions-write"]);
});

describe("Composer", () => {
  it("does not send while an input method is composing", () => {
    const { onSend, box } = composer();
    fireEvent.change(box, { target: { value: "नमस्ते" } });
    fireEvent.keyDown(box, { key: "Enter", isComposing: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("नमस्ते", expect.any(String));
  });

  it("says why a reply can't go before it is written, and offers no Send", () => {
    const { box } = composer({
      thread: thread({}, { canReply: false, replyBlockedReason: "whatsapp_window_closed" }),
    });
    expect(screen.getByRole("status")).toHaveTextContent(/24-hour reply window is closed/);
    expect(box).toBeDisabled();
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
  });

  it("keeps a failed reply and retries it under the same key", async () => {
    const onSend = vi.fn(async () => false);
    const { box } = composer({ onSend });
    fireEvent.change(box, { target: { value: "on its way" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: /send/i })));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: /send/i })));
    expect(box).toHaveValue("on its way");
    const [first, second] = onSend.mock.calls as unknown as [string, string][];
    expect(first?.[1]).toBe(second?.[1]);
  });

  it("starts from the thread's unsent draft", () => {
    const { box } = composer({ draft: "half written" });
    expect(box).toHaveValue("half written");
  });

  it("adds a canned response to what is written instead of replacing it", () => {
    const { box } = composer({ draft: "Hi," });
    fireEvent.click(screen.getByRole("button", { name: "Canned responses" }));
    fireEvent.click(screen.getByRole("button", { name: "Pay link" }));
    expect(box).toHaveValue("Hi,\n\nHere is your pay link.");
  });
});

describe("ChatThread", () => {
  const view = (rights: typeof agent, over: Partial<Thread> = {}) =>
    render(
      <ChatThread
        thread={thread({ isMine: false, assignedUserId: "colleague", ...over })}
        rights={rights}
        onToggleRail={() => {}}
        onTakeOver={() => {}}
        onReturnToBot={() => {}}
      />,
    );

  it("does not offer an agent a colleague's thread", () => {
    view(agent);
    expect(screen.queryByRole("button", { name: /take over/i })).toBeNull();
  });

  it("offers a supervisor the takeover", () => {
    view({ ...agent, canReassign: true });
    expect(screen.getByRole("button", { name: /take over/i })).toBeInTheDocument();
  });

  it("names the channel the thread is on", () => {
    view(agent, { channel: "sms" });
    expect(screen.getByText("SMS")).toBeInTheDocument();
  });
});

describe("ConversationList", () => {
  it("names the dot after what its colour shows", () => {
    render(
      <ConversationList
        threads={[
          summary({ awaitingReply: 2, sla: "breach", status: "needs_human", isMine: false }),
        ]}
        activeId="CV-A"
        onSelect={() => {}}
        search=""
        onSearchChange={() => {}}
        searching={false}
        searchFailed={false}
      />,
    );
    expect(screen.getByRole("img", { name: /waiting over 24 hours/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { current: true })).toBeInTheDocument();
  });
});

describe("inboxErrorWords", () => {
  it("never shows the request line or a permission id", () => {
    const err = new ApiError(
      "POST",
      "/conversations/CV-1/takeover",
      403,
      "forbidden:perm-supervisor-write",
    );
    expect(inboxErrorWords(err, "whatsapp")).toBe("You don't have permission to do that.");
  });

  it("words a gate refusal", () => {
    const err = new ApiError("POST", "/conversations/CV-1/messages", 409, "cooling_off");
    expect(inboxErrorWords(err, "whatsapp")).toMatch(/Cooling-off period/);
  });
});

describe("Inbox page", () => {
  const Page = (Route as unknown as { component: () => ReactNode }).component;
  const page = () =>
    render(
      <QueryClientProvider client={new QueryClient()}>
        <Page />
      </QueryClientProvider>,
    );

  it("keeps one thread's send to that thread", async () => {
    const a = thread({ id: "CV-A" });
    const b = thread({ id: "CV-B", customer: "Second Borrower" });
    q.threads = [summary({ id: "CV-A" }), summary({ id: "CV-B", customer: "Second Borrower" })];
    q.details = { "CV-A": a, "CV-B": b };
    let fail: (e: unknown) => void = () => {};
    q.send.mockReturnValue(new Promise((_r, reject) => (fail = reject)));

    q.search = { conversationId: "CV-A" };
    const { rerender } = page();
    fireEvent.change(screen.getByRole("textbox", { name: /reply on/i }), {
      target: { value: "for A" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    q.search = { conversationId: "CV-B" };
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <Page />
      </QueryClientProvider>,
    );
    const boxB = screen.getByRole("textbox", { name: /reply on/i });
    expect(boxB).toHaveValue("");
    fireEvent.change(boxB, { target: { value: "for B" } });
    // A's send still in flight does not hold B's.
    expect(screen.getByRole("button", { name: /send/i })).toBeEnabled();

    await act(async () => fail(new ApiError("POST", "/x", 409, "cooling_off")));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
