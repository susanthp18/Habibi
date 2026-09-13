// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// Keyboard paths for the three surfaces whose only trigger used to be a mouse
// gesture. Report 30 C4–C6: routing priority lived in `onDrop`, coaching status
// lived in `onDrop` (the card click only raised a toast), and a live floor row
// had no focusable cell.
//
// WP-071: these are rendered, and the gap that justifies rendering was measured
// rather than asserted. Two inversions were tried against the source pin this
// file replaced:
//
//   A. `onMoveUp` calling `onReorder(i, i + 1)`. The old pin CAUGHT this — it
//      asserted the exact ternary text `i > 0 ? () => props.onReorder(i, i - 1)`,
//      so two of its assertions broke. Rendering was not needed for A.
//   B. Swapping which DropdownMenuItem fires which handler, so the item labelled
//      "Move up" calls `onMoveDown`. Every one of the old pin's seven assertions
//      still PASSED — "Move up", "Move down", `onClick={onMoveUp}` and
//      `onClick={onMoveDown}` are all still present, merely wired to the wrong
//      labels. These tests FAIL, because they press the item named "Move up".
//
// B is the reason this file renders. A source pin reads what a file contains; it
// cannot read what the user gets when they press the thing they can see.
//
// Drag stays as a source pin: it is no longer the only door, and jsdom is the
// wrong tool for a drop target.
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
import type { Rule } from "@/api/types/routing";
import { LiveTable } from "@/components/floor/LiveTable";
import { CoachingBoard } from "@/components/qa/CoachingBoard";
import { RecordsTable } from "@/components/records/RecordsTable";
import { RuleList } from "@/components/routing/RuleList";

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

function read(rel: string): string {
  return readFileSync(join(srcRoot, rel), "utf8");
}

function rule(id: string, name: string): Rule {
  return {
    id,
    name,
    description: "",
    category: "Routing",
    enabled: true,
    when: [{ id: `${id}-when`, field: "dpd", op: ">", value: 30 }],
    then: { key: "handoff_human" },
    triggersLast24h: 0,
  };
}

function renderRuleList(rules: Rule[]) {
  const onReorder = vi.fn();
  render(
    <RuleList
      rules={rules}
      selectedId={null}
      onSelect={vi.fn()}
      onToggle={vi.fn()}
      onEdit={vi.fn()}
      onDuplicate={vi.fn()}
      onDelete={vi.fn()}
      onReorder={onReorder}
    />,
  );
  return { onReorder };
}

describe("routing rule priority", () => {
  const rules = [
    rule("r-first", "First rule"),
    rule("r-mid", "Middle rule"),
    rule("r-last", "Last rule"),
  ];

  it("Move up from the keyboard on the rule at index 1 reorders the list", async () => {
    const user = userEvent.setup();
    const { onReorder } = renderRuleList(rules);

    screen.getByRole("button", { name: "Actions for Middle rule" }).focus();
    await user.keyboard("{Enter}");
    const moveUp = await screen.findByRole("menuitem", { name: "Move up" });
    moveUp.focus();
    await user.keyboard("{Enter}");

    expect(onReorder).toHaveBeenCalledTimes(1);
    expect(onReorder).toHaveBeenCalledWith(1, 0);
  });

  it("disables Move up on the first rule and Move down on the last", async () => {
    const user = userEvent.setup();
    const { onReorder } = renderRuleList(rules);

    await user.click(screen.getByRole("button", { name: "Actions for First rule" }));
    expect(await screen.findByRole("menuitem", { name: "Move up" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await user.click(screen.getByRole("menuitem", { name: "Move down" }));
    expect(onReorder).toHaveBeenCalledTimes(1);
    expect(onReorder).toHaveBeenCalledWith(0, 1);

    onReorder.mockClear();
    await user.click(screen.getByRole("button", { name: "Actions for Last rule" }));
    expect(await screen.findByRole("menuitem", { name: "Move down" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await user.click(screen.getByRole("menuitem", { name: "Move up" }));
    expect(onReorder).toHaveBeenCalledTimes(1);
    expect(onReorder).toHaveBeenCalledWith(2, 1);
  });

  it("still reorders on drop, so drag is a convenience", () => {
    expect(read("components/routing/RuleList.tsx")).toContain("props.onReorder(dragIdx, i)");
  });
});

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
