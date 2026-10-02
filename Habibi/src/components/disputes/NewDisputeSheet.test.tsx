// @vitest-environment jsdom
import "@/test/jsdom";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/api/disputes", () => ({ createDispute: vi.fn() }));

const { NewDisputeSheet } = await import("./NewDisputeSheet");

const customers = [
  { id: "C-1", name: "Synthetic One", accountId: "ACC-1" },
  { id: "C-2", name: "Synthetic Two", accountId: "ACC-9" },
];

describe("NewDisputeSheet", () => {
  it("chooses the linked customer once the list arrives on a cold load", () => {
    // Opened from a conversation before the customers loaded: the empty list
    // cleared the link, and its arrival never restored it.
    const props = {
      onClose: () => {},
      onCreated: () => {},
      initialCustomerId: "C-1",
      initialAccountId: "ACC-2",
    };
    const { rerender } = render(<NewDisputeSheet {...props} customers={[]} />);
    rerender(<NewDisputeSheet {...props} customers={customers} />);
    expect(screen.getByRole("combobox", { name: "Customer" })).toHaveTextContent("Synthetic One");
    expect(screen.getByText("ACC-2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Raise dispute" })).toBeEnabled();
  });
});
