// -----------------------------------------------------------------------------
// Keyboard paths for the three surfaces whose only trigger used to be a mouse
// gesture. Report 30 C4–C6: routing priority lived in `onDrop`, coaching status
// lived in `onDrop` (the card click only raised a toast), and a live floor row
// had no focusable cell.
//
// vitest is `environment: "node"` with no jsdom, so these pin the source the
// way the Field-label suite pins `htmlFor` — a missing menu item, a select
// that does not call `onMove`, or an identity cell that is plain text, fails
// here. Drag stays; it is no longer the only door.
// -----------------------------------------------------------------------------

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

function read(rel: string): string {
  return readFileSync(join(srcRoot, rel), "utf8");
}

describe("routing rule priority", () => {
  const list = read("components/routing/RuleList.tsx");
  const card = read("components/routing/RuleCard.tsx");

  it("moves a rule from the overflow menu, not only onDrop", () => {
    // onReorder had one call site: the drop handler. Priority is which rule
    // wins, and a keyboard operator could not change it.
    expect(card).toContain("Move up");
    expect(card).toContain("Move down");
    expect(card).toContain("onClick={onMoveUp}");
    expect(card).toContain("onClick={onMoveDown}");
    expect(list).toContain("props.onReorder(i, i - 1)");
    expect(list).toContain("props.onReorder(i, i + 1)");
  });

  it("disables Move up on the first rule and Move down on the last", () => {
    expect(list).toContain("i > 0 ? () => props.onReorder(i, i - 1) : undefined");
    expect(list).toContain(
      "i < props.rules.length - 1 ? () => props.onReorder(i, i + 1) : undefined",
    );
    expect(card).toContain("disabled={!onMoveUp}");
    expect(card).toContain("disabled={!onMoveDown}");
  });

  it("still reorders on drop, so drag is a convenience", () => {
    expect(list).toContain("props.onReorder(dragIdx, i)");
  });
});

describe("QA coaching status", () => {
  const board = read("components/qa/CoachingBoard.tsx");

  it("advances status from a control on the card, not only onDrop", () => {
    // onMove was invoked only from the column drop handler. The card click
    // raised a toast and left the action where it was.
    expect(board).toMatch(/<select\b/);
    expect(board).toContain("onMove(a.id, e.target.value as CoachingStatus)");
    expect(board).toContain("<option key={option.key} value={option.key}>");
  });

  it("makes the card body a real button, with drag left on the wrapper", () => {
    expect(board).toContain('type="button"');
    expect(board).toContain("onClick={() => onOpen(a.id)}");
    expect(board).toContain("draggable");
    expect(board).toContain("onMove(id, col.key)");
  });

  it("does not describe drag as the only path", () => {
    expect(board).not.toMatch(/Assign actions to agents; drag between columns to update status\./);
    expect(board).toContain("set status on the card");
  });
});

describe("live floor selection", () => {
  const live = read("components/floor/LiveTable.tsx");
  const table = read("components/records/RecordsTable.tsx");

  it("opts the customer identity cell into a focusable activator", () => {
    // LiveTable's identity cell was plain text. A supervisor watching a live
    // escalating call could not open the Inspector without a mouse.
    expect(live).toContain('id: "customer"');
    expect(live).toContain("rowActivator: true");
    expect(live).toContain("onRowClick={onSelect}");
  });

  it("wraps only an opted-in cell in a button that opens the row", () => {
    expect(table).toContain("onRowClick && col.rowActivator");
    expect(table).toContain('type="button"');
    expect(table).toContain("onRowClick(row)");
  });
});
