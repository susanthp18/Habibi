// @vitest-environment jsdom
import "@/test/jsdom";

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/config";
import type { Thread, ThreadSummary } from "@/api/types/inbox";

const q = vi.hoisted(() => ({
  search: {} as { conversationId?: string },
  navigate: vi.fn(),
  threads: [] as unknown[],
  details: {} as Record<string, unknown>,
  send: vi.fn(),
  refresh: vi.fn(),
  fetchThread: vi.fn(),
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
  useConversations: () => ({
    data: { rows: q.threads, more: false, polls: 1 },
    isPending: false,
    isError: false,
  }),
  useOlderConversations: () => ({ load: vi.fn(), loading: false, failed: false }),
  useConversationCounts: () => ({ data: undefined }),
  fetchConversation: (...args: unknown[]) => q.fetchThread(...args),
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
  refreshConversationSuggestions: (...args: unknown[]) => q.refresh(...args),
}));

const { Composer } = await import("./Composer");
const { ChatThread } = await import("./ChatThread");
const { ConversationList } = await import("./ConversationList");
const { ContextRail } = await import("./ContextRail");
const { closesAtWords, inboxErrorWords } = await import("./inbox-words");
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

type ComposerProps = Parameters<typeof Composer>[0];

/** The page's part: it owns the draft. */
function Harness({
  initial,
  ...props
}: Omit<ComposerProps, "draft" | "onDraftChange"> & { initial: string }) {
  const [draft, setDraft] = useState(initial);
  return <Composer {...props} draft={draft} onDraftChange={setDraft} />;
}

function composer(props: Partial<ComposerProps> = {}) {
  const onSend = props.onSend ?? vi.fn(async () => true);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Harness
        thread={thread()}
        rights={agent}
        initial={props.draft ?? ""}
        onSend={onSend}
        onRefreshRag={() => {}}
        onSuggestReply={props.onSuggestReply ?? (async () => ({ kind: "none" }))}
        ragSuggestions={[]}
        ragLoading={false}
        ragError={null}
        ragStale={null}
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
  q.refresh.mockReset();
  q.refresh.mockReturnValue(new Promise(() => {}));
  q.fetchThread.mockReset();
  q.fetchThread.mockImplementation(async (id: string) => q.details[id]);
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
    expect(onSend).toHaveBeenCalledWith("नमस्ते");
  });

  it("says why a reply can't go before it is written, and offers no Send", () => {
    const { box } = composer({
      thread: thread({}, { canReply: false, replyBlockedReason: "whatsapp_window_closed" }),
    });
    expect(screen.getByRole("status")).toHaveTextContent(/24-hour reply window is closed/);
    expect(box).toBeDisabled();
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
  });

  it("does not insert a draft written for a message the customer has since followed", async () => {
    const { box } = composer({ onSuggestReply: async () => ({ kind: "superseded" }) });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: /suggest reply/i })));
    expect(box).toHaveValue("");
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

describe("ContextRail", () => {
  it("offers a promise or a dispute only to someone who can file one", () => {
    const t = thread();
    const { rerender } = render(<ContextRail thread={t} context={t.context} />);
    expect(screen.queryByRole("button", { name: /create ptp/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /raise dispute/i })).toBeNull();
    rerender(<ContextRail thread={t} context={t.context} canFileRecords />);
    expect(screen.getByRole("button", { name: /create ptp/i })).toBeInTheDocument();
  });

  it("names the number a reply goes to by its last four digits", () => {
    const t = thread({}, { replyToLast4: "3210", replyToSlot: "alt" });
    render(<ContextRail thread={t} context={t.context} />);
    expect(screen.getByText(/alternate number ending 3210/)).toBeInTheDocument();
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
        filter="all"
        onFilterChange={() => {}}
      />,
    );
    expect(screen.getByRole("img", { name: /waiting over 24 hours/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { current: true })).toBeInTheDocument();
  });

  it("pages on past the last row, and counts a search by what it loaded", () => {
    const onLoadOlder = vi.fn();
    render(
      <ConversationList
        threads={[summary()]}
        activeId={null}
        onSelect={() => {}}
        search="borrower"
        onSearchChange={() => {}}
        searching={false}
        searchFailed={false}
        filter="all"
        onFilterChange={() => {}}
        more
        onLoadOlder={onLoadOlder}
      />,
    );
    // More may match past the page: "1 matching" claimed a total it never read.
    expect(screen.getByRole("status")).toHaveTextContent("1+ matching conversations");
    fireEvent.click(screen.getByRole("button", { name: /load older conversations/i }));
    expect(onLoadOlder).toHaveBeenCalledTimes(1);
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

  it("dates a window that closes on another day", () => {
    const now = new Date("2026-10-02T12:00:00Z"); // 5:30 pm IST
    expect(closesAtWords("2026-10-02T13:00:00Z", now)).toBe("6:30 pm IST");
    expect(closesAtWords("2026-10-03T10:00:00Z", now)).toBe("tomorrow, 3:30 pm IST");
    expect(closesAtWords("2026-10-05T10:00:00Z", now)).toBe("5 Oct, 3:30 pm IST");
  });

  it("words a gate refusal", () => {
    const err = new ApiError("POST", "/conversations/CV-1/messages", 409, "cooling_off");
    expect(inboxErrorWords(err, "whatsapp")).toMatch(/Cooling-off period/);
  });
});

describe("Inbox page", () => {
  const Page = (Route as unknown as { component: () => ReactNode }).component;
  let client: QueryClient;
  const ui = () => (
    <QueryClientProvider client={client}>
      <Page />
    </QueryClientProvider>
  );
  const open = (id: string) => {
    q.search = { conversationId: id };
    return render(ui());
  };
  const reopen = (rerender: (el: ReactNode) => void, id: string) => {
    q.search = { conversationId: id };
    rerender(ui());
  };
  const box = () => screen.getByRole("textbox", { name: /reply on/i });
  const send = () => fireEvent.click(screen.getByRole("button", { name: /send/i }));

  beforeEach(() => {
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    q.threads = [summary({ id: "CV-A" }), summary({ id: "CV-B", customer: "Second Borrower" })];
    q.details = {
      "CV-A": thread({ id: "CV-A" }),
      "CV-B": thread({ id: "CV-B", customer: "Second Borrower" }),
    };
  });

  it("keeps one thread's send to that thread", async () => {
    let fail: (e: unknown) => void = () => {};
    q.send.mockReturnValue(new Promise((_r, reject) => (fail = reject)));

    const { rerender } = open("CV-A");
    fireEvent.change(box(), { target: { value: "for A" } });
    send();

    reopen(rerender, "CV-B");
    expect(box()).toHaveValue("");
    fireEvent.change(box(), { target: { value: "for B" } });
    // A's send still in flight does not hold B's.
    expect(screen.getByRole("button", { name: /send/i })).toBeEnabled();

    await act(async () => fail(new ApiError("POST", "/x", 409, "cooling_off")));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("resends a reply whose answer was lost under the same key, after switching away", async () => {
    q.send.mockRejectedValue(new TypeError("Failed to fetch"));
    const { rerender } = open("CV-A");
    fireEvent.change(box(), { target: { value: "on its way" } });
    await act(async () => send());

    reopen(rerender, "CV-B");
    reopen(rerender, "CV-A");
    expect(box()).toHaveValue("on its way");
    await act(async () => send());

    const keys = q.send.mock.calls.map((c) => c[2]);
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it("keeps what was typed while a reply was sending", async () => {
    let done: (t: unknown) => void = () => {};
    q.send.mockReturnValue(new Promise((resolve) => (done = resolve)));
    open("CV-A");
    fireEvent.change(box(), { target: { value: "first" } });
    send();
    fireEvent.change(box(), { target: { value: "first, and a second thought" } });
    await act(async () => done(q.details["CV-A"]));
    expect(box()).toHaveValue("first, and a second thought");
  });

  it("clears the reply it sent", async () => {
    q.send.mockResolvedValue(q.details["CV-A"]);
    open("CV-A");
    fireEvent.change(box(), { target: { value: "sent" } });
    await act(async () => send());
    expect(box()).toHaveValue("");
  });

  it("offers a drafted reply only while it answers the latest message", async () => {
    q.refresh.mockResolvedValue({
      conversationId: "CV-A",
      answersMessageId: "M-1",
      ragSuggestions: [],
      draftAnswer: "It is due on the 5th.",
    });
    open("CV-A");
    fireEvent.click(screen.getByRole("button", { name: /suggest reply/i }));
    await waitFor(() => expect(box()).toHaveValue("It is due on the 5th."));

    // The customer wrote again while it was drafted.
    const later = thread({ id: "CV-A" });
    later.messages = [
      ...(later.messages ?? []),
      { id: "M-2", sender: "customer", text: "and the fee?", time: "3:42 PM", at: null },
    ];
    q.fetchThread.mockResolvedValueOnce(later);
    fireEvent.change(box(), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /suggest reply/i }));
    await waitFor(() => expect(q.refresh).toHaveBeenCalledTimes(3));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /suggest reply/i })).toBeEnabled(),
    );
    expect(box()).toHaveValue("");
  });

  it("offers no draft when the thread could not be read again", async () => {
    // The check fell back on the cached thread -- the old one it exists to
    // doubt -- and a failed read approved a draft for a superseded message.
    q.refresh.mockResolvedValue({
      conversationId: "CV-A",
      answersMessageId: "M-1",
      ragSuggestions: [],
      draftAnswer: "It is due on the 5th.",
    });
    q.fetchThread.mockRejectedValue(new TypeError("Failed to fetch"));
    open("CV-A");
    fireEvent.click(screen.getByRole("button", { name: /suggest reply/i }));
    await waitFor(() => expect(q.fetchThread).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /suggest reply/i })).toBeEnabled(),
    );
    expect(box()).toHaveValue("");
  });

  it("keeps the newer message's passages when an older search finishes last", async () => {
    q.refresh
      .mockResolvedValueOnce({
        conversationId: "CV-A",
        answersMessageId: "M-1",
        ragSuggestions: ["Fees are waived on the first late payment."],
      })
      .mockResolvedValueOnce({
        conversationId: "CV-A",
        answersMessageId: "M-0",
        ragSuggestions: [],
        superseded: true,
      });
    open("CV-A");
    await screen.findByRole("button", { name: "Sources (1)" });
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => expect(q.refresh).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("button", { name: /refresh/i })).toBeEnabled());
    // The older search's empty answer used to replace them.
    fireEvent.click(screen.getByRole("button", { name: "Sources (1)" }));
    expect(screen.getByText(/Fees are waived/)).toBeInTheDocument();
  });

  const wroteAgain = () => {
    const later = thread({ id: "CV-A" });
    later.messages = [
      ...(later.messages ?? []),
      { id: "M-2", sender: "customer", text: "and the fee?", time: "3:42 PM", at: null },
    ];
    return later;
  };

  it("says the passages answer an earlier message once the customer writes again", async () => {
    q.refresh.mockResolvedValueOnce({
      conversationId: "CV-A",
      answersMessageId: "M-1",
      ragSuggestions: ["Fees are waived on the first late payment."],
    });
    const { rerender } = open("CV-A");
    fireEvent.click(await screen.findByRole("button", { name: "Sources (1)" }));
    expect(screen.queryByText(/written since/)).toBeNull();
    q.details["CV-A"] = wroteAgain();
    reopen(rerender, "CV-A");
    // At once -- not when the next search returns, which may be never.
    expect(screen.getByText(/written since/)).toBeInTheDocument();
  });

  it("does not offer a slow search's passages as an answer to the newer message", async () => {
    // The page already holds M-2; the search answering M-1 lands after it.
    q.details["CV-A"] = wroteAgain();
    q.refresh.mockResolvedValueOnce({
      conversationId: "CV-A",
      answersMessageId: "M-1",
      ragSuggestions: ["Fees are waived on the first late payment."],
    });
    open("CV-A");
    fireEvent.click(await screen.findByRole("button", { name: "Sources (1)" }));
    expect(screen.getByText(/written since/)).toBeInTheDocument();
  });

  it("keeps a reply's key through a refused retry, until one succeeds", async () => {
    // Lost answer, then a 429 on the retry: the 429 says nothing of whether the
    // first one queued. A new key there let a third try queue it twice.
    q.send
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new ApiError("POST", "/x", 429, "rate_limited"))
      .mockResolvedValueOnce(q.details["CV-A"]);
    open("CV-A");
    fireEvent.change(box(), { target: { value: "on its way" } });
    await act(async () => send());
    await act(async () => send());
    await act(async () => send());
    const keys = q.send.mock.calls.map((c) => c[2]);
    expect(keys).toHaveLength(3);
    expect(new Set(keys).size).toBe(1);
  });

  it("gives focus back to the button that opened the customer context", async () => {
    open("CV-A");
    const toggle = screen.getByRole("button", { name: /toggle customer context/i });
    toggle.focus();
    fireEvent.click(toggle);
    const dialog = await screen.findByRole("dialog");
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(toggle).toHaveFocus();
  });

  it("does not search the knowledge base for someone who cannot reply", async () => {
    vi.useFakeTimers();
    try {
      q.rights = new Set();
      open("CV-A");
      await act(async () => {
        vi.advanceTimersByTime(1_000);
      });
      expect(q.refresh).not.toHaveBeenCalled();
      expect(screen.queryByRole("button", { name: /refresh/i })).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
