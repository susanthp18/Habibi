// -----------------------------------------------------------------------------
// Inbox delta-merge ordering.
//
// The list is polled every 1.5–4s: a full list on the first poll and every
// ~15th, deltas in between. A full poll renders the server's order verbatim; a
// delta poll re-sorts on the client. If those two orders disagree, rows swap
// places on their own once a minute.
// -----------------------------------------------------------------------------

import { describe, expect, it } from "vitest";

import { compareThreads, INBOX_LIST_LIMIT, mergeThreads, withOlder } from "./inbox";
import type { ThreadSummary } from "@/api/types/inbox";

type Thread = ThreadSummary;

function thread(id: string, lastAt: string, lastTime: string): Thread {
  return { id, lastAt, updatedAt: lastAt, lastTime, customer: id } as unknown as Thread;
}

describe("compareThreads", () => {
  it("orders by the last message, newest first", () => {
    const older = thread("CV-1", "2026-08-23T05:00:00.000000+00:00", "10:30 AM");
    const newer = thread("CV-2", "2026-08-23T06:00:00.000000+00:00", "11:30 AM");
    expect([older, newer].sort(compareThreads).map((t) => t.id)).toEqual(["CV-2", "CV-1"]);
  });

  it("does not compare 12-hour clock strings", () => {
    // "9:40 AM" > "10:29 AM" lexicographically, so the older thread sorted
    // first whenever the hour had one digit fewer. Every seeded thread shares
    // an updatedAt to the microsecond — one bulk transaction — so this
    // tiebreak decided the whole list.
    const nine = thread("CV-B", "2026-08-23T05:04:18.379714+00:00", "9:40 AM");
    const ten = thread("CV-A", "2026-08-23T05:04:18.379714+00:00", "10:29 AM");
    const byClock = [ten, nine].sort((a, b) => (b.lastTime || "").localeCompare(a.lastTime || ""));
    expect(byClock.map((t) => t.id)).toEqual(["CV-B", "CV-A"]); // the old bug

    expect([ten, nine].sort(compareThreads).map((t) => t.id)).toEqual(["CV-A", "CV-B"]);
  });

  it("breaks ties by id, ascending — the server's own tiebreak", () => {
    // Server: ORDER BY COALESCE(last message, created_at) DESC, cv.id
    const at = "2026-08-23T05:04:18.379714+00:00";
    const rows = [
      thread("CV-C", at, "1:00 PM"),
      thread("CV-A", at, "2:00 PM"),
      thread("CV-B", at, "3:00 PM"),
    ];
    expect(rows.sort(compareThreads).map((t) => t.id)).toEqual(["CV-A", "CV-B", "CV-C"]);
  });

  it('breaks ties bytewise, as the server\'s COLLATE "C" does — not by locale', () => {
    // A locale folds case: "cv-a" before "CV-B". Postgres orders the id
    // bytewise ("CV-B" first), and the next page starts from that order.
    const at = "2026-08-23T05:04:18.379714+00:00";
    const rows = [thread("cv-a", at, "1:00 PM"), thread("CV-B", at, "1:00 PM")];
    expect(rows.sort(compareThreads).map((t) => t.id)).toEqual(["CV-B", "cv-a"]);
  });

  it("is a total order — sorting twice does not reshuffle", () => {
    const at = "2026-08-23T05:04:18.379714+00:00";
    const rows = [
      thread("CV-C", at, "9:40 AM"),
      thread("CV-A", at, "10:29 AM"),
      thread("CV-B", at, "8:00 AM"),
    ];
    const once = [...rows].sort(compareThreads).map((t) => t.id);
    const twice = [...rows]
      .sort(compareThreads)
      .sort(compareThreads)
      .map((t) => t.id);
    expect(twice).toEqual(once);
  });

  it("does not move a thread for a change nobody said anything in", () => {
    // `updatedAt` is the delta watermark: a takeover or a receipt moves it.
    const talked = thread("CV-1", "2026-08-23T06:00:00.000000+00:00", "11:30 AM");
    const touched = {
      ...thread("CV-2", "2026-08-23T05:00:00.000000+00:00", "10:30 AM"),
      updatedAt: "2026-08-23T07:00:00.000000+00:00",
    } as Thread;
    expect([touched, talked].sort(compareThreads).map((t) => t.id)).toEqual(["CV-1", "CV-2"]);
  });

  it("treats a missing lastAt as oldest rather than throwing", () => {
    const dated = thread("CV-1", "2026-08-23T05:00:00.000000+00:00", "10:30 AM");
    const undated = {
      ...thread("CV-2", "", "11:30 AM"),
      lastAt: undefined,
    } as unknown as Thread;
    expect([undated, dated].sort(compareThreads).map((t) => t.id)).toEqual(["CV-1", "CV-2"]);
  });
});

describe("mergeThreads", () => {
  it("keeps the previous list when a delta poll returns nothing", () => {
    const prev = [thread("CV-1", "2026-08-23T05:00:00.000000+00:00", "10:30 AM")];
    expect(mergeThreads(prev, [])).toBe(prev);
  });

  it("upserts a delta and re-sorts into server order", () => {
    const prev = [
      thread("CV-1", "2026-08-23T05:00:00.000000+00:00", "10:30 AM"),
      thread("CV-2", "2026-08-23T04:00:00.000000+00:00", "9:30 AM"),
    ];
    const merged = mergeThreads(prev, [
      thread("CV-2", "2026-08-23T07:00:00.000000+00:00", "12:30 PM"),
    ]);
    expect(merged.map((t) => t.id)).toEqual(["CV-2", "CV-1"]);
  });

  it("replaces a row with its delta", () => {
    const prev = [
      { ...thread("CV-1", "2026-08-23T05:00:00.000000+00:00", "10:30 AM"), awaitingReply: 2 },
    ];
    const delta = {
      ...thread("CV-1", "2026-08-23T06:00:00.000000+00:00", "11:30 AM"),
      awaitingReply: 0,
    };
    expect(mergeThreads(prev as Thread[], [delta as Thread])[0]?.awaitingReply).toBe(0);
  });
});

describe("withOlder", () => {
  const page = (n: number, from = 0) =>
    Array.from({ length: n }, (_, i) =>
      thread(`CV-${String(from + i).padStart(4, "0")}`, "2026-08-23T05:00:00.000000+00:00", "x"),
    );

  it("keeps the older rows the operator paged to when the first page refreshes", () => {
    const first = page(INBOX_LIST_LIMIT);
    const loaded = page(3, INBOX_LIST_LIMIT);
    const held = { rows: [...first, ...loaded], more: false, polls: 4 };
    const next = withOlder(first, held);
    expect(next.rows).toHaveLength(INBOX_LIST_LIMIT + 3);
    expect(next.more).toBe(false);
  });

  it("is the whole list when the first page is not full", () => {
    const held = { rows: page(7), more: true, polls: 2 };
    expect(withOlder(page(5), held)).toEqual({ rows: page(5), more: false });
  });
});
