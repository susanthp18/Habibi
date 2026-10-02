// @vitest-environment jsdom
import "@/test/jsdom";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const q = vi.hoisted(() => ({ customers: {} as Record<string, unknown> }));

vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));
vi.mock("@/api/me", () => ({ useMe: () => ({ data: undefined }), can: () => false }));
vi.mock("@/api/voice-studio", () => ({ useStudioAgents: () => ({ data: [] }) }));
vi.mock("@/api/workspace", () => ({ useWorkItems: () => ({ data: [], isError: false }) }));
vi.mock("@/api/customers", () => ({ useCustomerSearch: () => q.customers }));

const { CommandPalette } = await import("./CommandPalette");

describe("CommandPalette", () => {
  it("keeps a customer the server matched on an account the row does not show", () => {
    // The server matches every account of a customer; the row shows one.
    q.customers = {
      data: [{ id: "C-1", name: "Synthetic Borrower", accountId: "ACC-PRIMARY" }],
      isError: false,
    };
    render(<CommandPalette open onOpenChange={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/jump to page/i), {
      target: { value: "ACC-SECONDARY" },
    });
    expect(screen.getByText(/Synthetic Borrower/)).toBeInTheDocument();
    expect(screen.queryByText("No matches.")).toBeNull();
  });

  it("says a failed search failed, rather than showing no customers", () => {
    q.customers = { data: undefined, isError: true, refetch: vi.fn() };
    render(<CommandPalette open onOpenChange={vi.fn()} />);
    expect(screen.getByText(/couldn.t search customers/i)).toBeInTheDocument();
  });
});
