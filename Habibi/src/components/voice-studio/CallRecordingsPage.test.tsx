// @vitest-environment jsdom
import "@/test/jsdom";

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/agentstudio/client/client.gen", () => ({ client: { get: mocked.get } }));
vi.mock("@/agentstudio/components/MediaPreviewDialog", () => ({
  MediaPreviewDialog: () => ({ openPreview: vi.fn(), dialog: null }),
}));
vi.mock("@/agentstudio/hooks/useOrganizationTimezone", () => ({
  useOrganizationTimezone: () => "Asia/Kolkata",
}));
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children }: { children: React.ReactNode }) => <a href="#run">{children}</a>,
}));

const { default: CallRecordingsPage } = await import("./CallRecordingsPage");

describe("Studio call recordings", () => {
  beforeEach(() => mocked.get.mockReset());

  it("fetches once and shows a recorded inbound run", async () => {
    mocked.get.mockResolvedValue({
      data: {
        runs: [
          {
            id: 7,
            workflow_id: 1,
            workflow_name: "Inbound help",
            created_at: "2026-09-26T09:03:00Z",
            call_type: "inbound",
            call_duration_seconds: 54,
            recording_url: "recording-key",
            transcript_url: null,
          },
        ],
        total_pages: 1,
      },
    });
    render(<CallRecordingsPage />);
    expect(await screen.findByText("Inbound help")).toBeInTheDocument();
    expect(screen.getByText("inbound")).toBeInTheDocument();
    expect(screen.getByText("#7")).toBeInTheDocument();
    expect(mocked.get).toHaveBeenCalledTimes(1);
    expect(mocked.get).toHaveBeenCalledWith(
      expect.objectContaining({ query: expect.objectContaining({ has_recording: true }) }),
    );
  });

  it("shows an API error instead of an empty state", async () => {
    mocked.get.mockResolvedValue({ error: { detail: "Service unavailable" } });
    render(<CallRecordingsPage />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByText("No Studio call recordings found.")).toBeNull();
  });
});
