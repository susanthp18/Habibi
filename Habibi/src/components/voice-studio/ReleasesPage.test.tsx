// @vitest-environment jsdom
// Releases: every go-live and rollback across agents, with who and why.
import "@/test/jsdom";

import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { mountAt } from "@/test/mount";

vi.mock("@/api/voice-studio", () => ({
  useStudioAgents: () => ({ data: [{ id: 4, name: "Collections - overdue reminder" }] }),
  useReleases: () => ({
    status: "success",
    isPending: false,
    isError: false,
    isSuccess: true,
    data: [
      {
        id: "r2",
        workflowId: 4,
        version: 6,
        fromVersion: 5,
        action: "rollback",
        note: "Rolled back to version 4: v5 double-booked callbacks",
        actor: "Priya Nair",
        createdAt: "2026-09-26T10:00:00Z",
      },
    ],
  }),
}));

const { default: ReleasesPage } = await import("./ReleasesPage");

describe("Voice Studio releases", () => {
  it("lists a rollback with the agent, versions, reason and author", async () => {
    mountAt("/", <ReleasesPage />);
    expect(await screen.findByText("Collections - overdue reminder")).toBeInTheDocument();
    expect(screen.getByText(/v5 → v6/)).toBeInTheDocument();
    expect(screen.getByText("rollback")).toBeInTheDocument();
    expect(screen.getByText(/v5 double-booked callbacks/)).toBeInTheDocument();
    expect(screen.getByText("Priya Nair")).toBeInTheDocument();
  });
});
