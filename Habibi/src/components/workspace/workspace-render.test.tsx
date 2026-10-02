// @vitest-environment jsdom
import "@/test/jsdom";

import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const q = vi.hoisted(() => ({
  pages: {} as Record<string, unknown>,
  summary: {} as Record<string, unknown>,
}));

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children }: { children: ReactNode }) => <span>{children}</span>,
  useNavigate: () => vi.fn(),
}));
vi.mock("@/api/me", () => ({ useMe: () => ({ data: { id: "u", tenantId: "t" } }) }));
vi.mock("@/api/workspace", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/workspace")>()),
  useWorkItemPages: () => q.pages,
  useWorkspaceSummary: () => q.summary,
}));

const { AssignedQueue } = await import("./AssignedQueue");
const { NotificationsPopover } = await import("@/components/shell/NotificationsPopover");

const row = {
  id: "D-1",
  customer: "Synthetic Borrower",
  customerId: "C-1",
  accountId: "A-1",
  type: "Dispute",
  detail: "Charge disputed",
  amount: 100,
  createdAt: "2026-09-30T05:00:00Z",
  dueAt: "2026-10-09T05:00:00Z",
  sla: "ok",
  slaLabel: "",
  entityType: "dispute",
};

const failed = { isError: true, error: new Error("502"), isPending: false, dataUpdatedAt: 0 };

function queue() {
  render(
    <AssignedQueue
      scope="me"
      onScope={vi.fn()}
      tab="all"
      onTab={vi.fn()}
      due={undefined}
      onDue={vi.fn()}
      search=""
      onSearch={vi.fn()}
    />,
  );
}

describe("AssignedQueue when a read fails", () => {
  it("says so on a first load, rather than showing an empty queue", () => {
    q.summary = { data: undefined };
    q.pages = { ...failed, data: undefined };
    queue();
    expect(screen.getByText(/could not load the queue/i)).toBeInTheDocument();
    expect(screen.queryByText(/nothing here/i)).toBeNull();
  });

  it("says so when the last good read was empty", () => {
    q.pages = { ...failed, data: { pages: [[]] } };
    queue();
    expect(screen.getByText(/could not load the queue/i)).toBeInTheDocument();
    expect(screen.queryByText(/nothing here/i)).toBeNull();
  });

  it("keeps cached rows and says they could not be refreshed", () => {
    q.pages = { ...failed, dataUpdatedAt: Date.now(), data: { pages: [[row]] } };
    queue();
    expect(screen.getByText("Synthetic Borrower")).toBeInTheDocument();
    expect(screen.getByText(/couldn.t refresh the queue/i)).toBeInTheDocument();
  });
});

describe("NotificationsPopover", () => {
  it("does not claim nothing is blocked when only the soonest callbacks were checked", () => {
    q.summary = {
      isError: false,
      isPending: false,
      dataUpdatedAt: Date.now(),
      data: {
        attention: [],
        nextCallback: null,
        callbacksBlockedCount: 0,
        callbacksBlockedPartial: true,
        queueCounts: { total: 0, overdue: 0, dueSoon: 0, byType: {} },
      },
    };
    render(<NotificationsPopover />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(screen.queryByText(/nothing overdue, due soon or blocked/i)).toBeNull();
    expect(screen.getByText(/later ones weren.t checked/i)).toBeInTheDocument();
  });
});
