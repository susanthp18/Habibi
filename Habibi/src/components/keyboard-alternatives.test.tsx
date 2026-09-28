// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// Keyboard alternatives for active QA and live-floor controls. The retired
// Routing / Logic builder's priority tests were replaced by keyboard coverage
// for Voice Studio's active Agent routing page.
// -----------------------------------------------------------------------------

import "@/test/jsdom";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

import type { CoachingAction } from "@/api/types/qa";
import type { ActiveCall } from "@/api/types/floor";
import { LiveTable } from "@/components/floor/LiveTable";
import { CoachingBoard } from "@/components/qa/CoachingBoard";
import { RecordsTable } from "@/components/records/RecordsTable";

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

function read(rel: string): string {
  return readFileSync(join(srcRoot, rel), "utf8");
}

describe("QA coaching status", () => {
  const action: CoachingAction = {
    id: "ca-1",
    agentId: "priya-nair",
    title: "Missed disclosure",
    category: "compliance",
    dueAt: "2099-01-15T10:00:00.000Z",
    status: "assigned",
    notes: [],
    createdAt: "2099-01-01T10:00:00.000Z",
  };

  it("advances status from the card picker, not only onDrop", async () => {
    const user = userEvent.setup();
    const onMove = vi.fn();
    render(<CoachingBoard actions={[action]} onMove={onMove} onNew={vi.fn()} onOpen={vi.fn()} />);

    // The picker is the app-wide SelectField now, not a native select, so the
    // keyboard path this file exists to prove is open/choose rather than
    // selectOptions. The card is draggable and the picker must not start a drag.
    await user.click(screen.getByRole("combobox", { name: "Status for Missed disclosure" }));
    await user.click(await screen.findByRole("option", { name: "In progress" }));
    expect(onMove).toHaveBeenCalledTimes(1);
    expect(onMove).toHaveBeenCalledWith("ca-1", "in_progress");
  });

  it("opens the card from a real button, with drag left on the wrapper", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<CoachingBoard actions={[action]} onMove={vi.fn()} onNew={vi.fn()} onOpen={onOpen} />);

    await user.click(screen.getByRole("button", { name: /Missed disclosure/i }));
    expect(onOpen).toHaveBeenCalledWith("ca-1");
    expect(read("components/qa/CoachingBoard.tsx")).toContain("draggable");
    expect(read("components/qa/CoachingBoard.tsx")).toContain("onMove(id, col.key)");
  });

  it("does not describe drag as the only path", () => {
    render(<CoachingBoard actions={[action]} onMove={vi.fn()} onNew={vi.fn()} onOpen={vi.fn()} />);
    expect(screen.getByText(/set status on the card/)).toBeInTheDocument();
    expect(
      screen.queryByText(/Assign actions to agents; drag between columns to update status\./),
    ).not.toBeInTheDocument();
  });
});

describe("live floor selection", () => {
  it("opens the inspector from the keyboard on the customer identity cell", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const row: ActiveCall = {
      id: "call-1",
      handler: { kind: "human", name: "Priya Nair", initials: "PN" },
      customer: "Anita Sharma",
      accountTail: "4821",
      channel: "voice",
      topic: "PTP capture",
      durationSec: 90,
      sentiment: 0.1,
      sentimentTrend: 0,
      risk: "high",
      lastLine: "I can pay on Friday",
      language: "en",
      flags: [],
      pendingHandoff: false,
      outstanding: 12_000,
      customerRisk: "medium",
      dnd: false,
      recentTurns: [],
      recommendedAction: "listen",
    };
    render(<LiveTable rows={[row]} activeId={null} onSelect={onSelect} />);

    const activator = screen.getByRole("button", { name: /Anita Sharma/ });
    activator.focus();
    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0]?.[0]).toMatchObject({ id: "call-1" });
  });

  it("wraps only an opted-in cell in a button that opens the row", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    render(
      <RecordsTable
        rows={[{ id: "r1", name: "Anita Sharma", topic: "PTP capture" }]}
        getRowId={(r) => r.id}
        onRowClick={onRowClick}
        columns={[
          { id: "name", header: "Customer", rowActivator: true, cell: (r) => r.name },
          { id: "topic", header: "Topic", cell: (r) => r.topic },
        ]}
      />,
    );

    expect(screen.getByRole("button", { name: "Anita Sharma" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "PTP capture" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Anita Sharma" }));
    expect(onRowClick).toHaveBeenCalledTimes(1);
    expect(onRowClick.mock.calls[0]?.[0]).toMatchObject({ id: "r1" });
  });
});
