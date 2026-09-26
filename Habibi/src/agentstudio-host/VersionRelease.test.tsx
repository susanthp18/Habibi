// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// Version history: who released each version and why, and rollback of earlier
// versions only (never the live one or the draft), with a required reason.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = { permissions: ["perm-agent-publish"] };
const mutate = vi.fn();

vi.mock("@/api/voice-studio", () => ({
  useReleases: () => ({
    data: [
      {
        id: "r1",
        workflowId: 7,
        version: 4,
        fromVersion: 3,
        action: "publish",
        note: "Ask the callback time first",
        actor: "Priya Nair",
        createdAt: "2026-09-26T09:00:00Z",
      },
    ],
  }),
  useRollbackAgent: () => ({ mutate, isPending: false }),
}));
vi.mock("@/api/me", () => ({
  useMe: () => ({ data: { permissions: state.permissions } }),
  can: (me: { permissions: string[] }, p: string) => me.permissions.includes(p),
}));

const { default: VersionRelease } = await import("./VersionRelease");

describe("Voice Studio version release notes and rollback", () => {
  beforeEach(() => {
    mutate.mockReset();
    state.permissions = ["perm-agent-publish"];
  });

  it("shows who released a version and why", () => {
    render(
      <VersionRelease
        workflowId={7}
        version={{ id: 40, version_number: 4, status: "archived" }}
        onRolledBack={() => {}}
      />,
    );
    expect(screen.getByText(/Release by Priya Nair/)).toBeInTheDocument();
    expect(screen.getByText("Ask the callback time first")).toBeInTheDocument();
  });

  it.each(["published", "draft"])("offers no rollback to the %s version", (status) => {
    render(
      <VersionRelease
        workflowId={7}
        version={{ id: 40, version_number: 4, status }}
        onRolledBack={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: /Roll back/ })).toBeNull();
  });

  it("offers no rollback without publish permission", () => {
    state.permissions = [];
    render(
      <VersionRelease
        workflowId={7}
        version={{ id: 40, version_number: 4, status: "archived" }}
        onRolledBack={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: /Roll back/ })).toBeNull();
  });

  it("rolls an earlier version back with a reason", () => {
    render(
      <VersionRelease
        workflowId={7}
        version={{ id: 40, version_number: 4, status: "archived" }}
        onRolledBack={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Roll back to v4" }));
    const confirm = screen.getByRole("button", { name: "Roll back" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Why"), {
      target: { value: "v5 double-booked callbacks" },
    });
    fireEvent.click(confirm);
    expect(mutate).toHaveBeenCalledWith(
      { versionId: 40, note: "v5 double-booked callbacks" },
      expect.anything(),
    );
  });
});
