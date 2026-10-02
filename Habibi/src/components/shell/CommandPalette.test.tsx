// @vitest-environment jsdom
import "@/test/jsdom";

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const q = vi.hoisted(() => ({
  search: (_needle: string): Record<string, unknown> => ({}),
  navigate: vi.fn(),
  // The debounced search the palette has asked about; null: whatever is typed.
  settled: null as string | null,
}));

vi.mock("@tanstack/react-router", () => ({ useNavigate: () => q.navigate }));
vi.mock("@/api/me", () => ({ useMe: () => ({ data: undefined }), can: () => false }));
vi.mock("@/api/voice-studio", () => ({ useStudioAgents: () => ({ data: [] }) }));
vi.mock("@/api/workspace", () => ({ useWorkItems: () => ({ data: [], isError: false }) }));
vi.mock("@/api/customers", () => ({ useCustomerSearch: (needle: string) => q.search(needle) }));
vi.mock("@/lib/use-debounced", () => ({
  useDebounced: (value: string) => q.settled ?? value,
}));

const { CommandPalette } = await import("./CommandPalette");

const borrower = { id: "C-1", name: "Synthetic Borrower", accountId: "ACC-PRIMARY" };
const toBorrower = { to: "/customers/$customerId", params: { customerId: "C-1" } };

function type(value: string) {
  const input = screen.getByPlaceholderText(/jump to page/i);
  fireEvent.change(input, { target: { value } });
  return input;
}

beforeEach(() => {
  q.navigate.mockClear();
  q.settled = null;
});

describe("CommandPalette", () => {
  it("keeps a customer the server matched on an account the row does not show", () => {
    // The server matches every account of a customer; the row shows one.
    q.search = () => ({ data: [borrower], isError: false });
    render(<CommandPalette open onOpenChange={vi.fn()} />);
    const input = type("ACC-SECONDARY");
    expect(screen.getByText(/Synthetic Borrower/)).toBeInTheDocument();
    expect(screen.queryByText("No matches.")).toBeNull();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(q.navigate).toHaveBeenCalledWith(toBorrower);
  });

  it("never opens a customer from the previous search while the new one is pending", () => {
    // keepPreviousData: a new needle answers with the last needle's rows until it lands.
    q.search = (needle) =>
      needle === "ACC-PRIMARY"
        ? { data: [borrower], isError: false }
        : { data: [borrower], isError: false, isPlaceholderData: true, isFetching: true };
    const { rerender } = render(<CommandPalette open onOpenChange={vi.fn()} />);
    type("ACC-PRIMARY");

    q.settled = "ACC-PRIMARY";
    const input = type("ACC-OTHER");
    fireEvent.keyDown(input, { key: "Enter" }); // typed, not yet asked
    q.settled = "ACC-OTHER";
    rerender(<CommandPalette open onOpenChange={vi.fn()} />);
    fireEvent.keyDown(input, { key: "Enter" }); // asked, not yet answered
    expect(q.navigate).not.toHaveBeenCalled();
    expect(screen.getByText(/Synthetic Borrower/)).toBeInTheDocument();
    expect(screen.getAllByText("Searching…").length).toBeGreaterThan(0);
  });

  it("says a failed search failed, rather than showing no customers", () => {
    q.search = () => ({ data: undefined, isError: true, refetch: vi.fn() });
    render(<CommandPalette open onOpenChange={vi.fn()} />);
    expect(screen.getByText(/couldn.t search customers/i)).toBeInTheDocument();
  });
});
