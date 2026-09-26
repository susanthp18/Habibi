// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// The approval decision on a tool revision: only a named reviewer holding
// perm-tool-approve sees it, approve/reject act on a submitted revision, and
// revoking one that released agents are calling asks before it takes effect.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = { permissions: ["perm-tool-approve"] };
const review = vi.fn();

vi.mock("@/api/studio-tools", () => ({
  reviewStudioToolRevision: (...args: unknown[]) => review(...args),
}));
vi.mock("@/api/me", () => ({
  useMe: () => ({ data: { permissions: state.permissions } }),
  can: (me: { permissions: string[] }, p: string) => me.permissions.includes(p),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { default: ToolReview } = await import("./ToolReview");

const onReviewed = vi.fn();

function renderSlot(revisionState: string) {
  return render(
    <ToolReview
      toolUuid="tool-1"
      revision={3}
      state={revisionState as "submitted"}
      onReviewed={onReviewed}
    />,
  );
}

describe("Voice Studio tool revision review", () => {
  beforeEach(() => {
    review.mockReset().mockResolvedValue({ state: "approved", digest: "abc" });
    onReviewed.mockReset();
    state.permissions = ["perm-tool-approve"];
  });

  it("approves a submitted revision", async () => {
    renderSlot("submitted");
    fireEvent.click(screen.getByText("Approve"));
    await waitFor(() => expect(review).toHaveBeenCalledWith("tool-1", 3, "approved"));
    expect(onReviewed).toHaveBeenCalled();
  });

  it("offers nothing without perm-tool-approve", () => {
    state.permissions = ["perm-agent-edit"];
    renderSlot("submitted");
    expect(screen.queryByText("Approve")).not.toBeInTheDocument();
  });

  it.each(["draft", "rejected", "revoked"])("offers no decision on a %s revision", (s) => {
    renderSlot(s);
    expect(screen.queryByText("Approve")).not.toBeInTheDocument();
    expect(screen.queryByText("Revoke")).not.toBeInTheDocument();
  });

  it("does not revoke a live revision until it is confirmed", async () => {
    renderSlot("approved");
    fireEvent.click(screen.getByText("Revoke"));
    expect(await screen.findByText("Revoke revision 3?")).toBeInTheDocument();
    expect(review).not.toHaveBeenCalled();

    // The trigger and the dialog's own action share the label; confirm on the dialog.
    const confirmButton = screen.getAllByRole("button", { name: "Revoke" }).at(-1)!;
    fireEvent.click(confirmButton);
    await waitFor(() => expect(review).toHaveBeenCalledWith("tool-1", 3, "revoked"));
  });
});
