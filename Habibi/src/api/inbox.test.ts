// -----------------------------------------------------------------------------
// Inbox delta-merge ordering.
//
// The list is polled every 1.5–4s: a full list on the first poll and every
// ~15th, deltas in between. A full poll renders the server's order verbatim; a
// delta poll re-sorts on the client. If those two orders disagree, rows swap
// places on their own once a minute.
// -----------------------------------------------------------------------------

import { describe, expect, it } from "vitest";

import {
  compareThreads,
  type Cursor,
  INBOX_LIST_LIMIT,
  mergeDeltas,
  mergeThreads,
  readPages,
} from "./inbox";
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

  it("orders threads microseconds apart as the server does", () => {
    // Date.parse keeps milliseconds: these tied, and the id put CV-1 first.
    const later = thread("CV-9", "2026-08-23T05:00:00.000400+00:00", "x");
    const earlier = thread("CV-1", "2026-08-23T05:00:00.000100+00:00", "x");
    expect([earlier, later].sort(compareThreads).map((t) => t.id)).toEqual(["CV-9", "CV-1"]);
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

/**
 * The server's list, a page at a time: ORDER BY last message DESC, id
 * COLLATE "C", keyset on (lastAt, id) -- at its full precision.
 */
function server(rows: Thread[]) {
  const reads: Array<Cursor | undefined> = [];
  const fetchPage = async (before?: Cursor) => {
    reads.push(before);
    const ordered = rows
      .slice()
      .sort((a, b) =>
        a.lastAt !== b.lastAt ? (a.lastAt! < b.lastAt! ? 1 : -1) : a.id < b.id ? -1 : 1,
      );
    const from = before ? ordered.findIndex((t) => t.id === before.id) + 1 : 0;
    return ordered.slice(from, from + INBOX_LIST_LIMIT);
  };
  return { rows, reads, fetchPage };
}

/** n threads a second apart, newest first; ids run against time. */
const book = (n: number) =>
  Array.from({ length: n }, (_, i) =>
    thread(
      `CV-${String(n - i).padStart(4, "0")}`,
      new Date(Date.UTC(2026, 7, 23, 5) - i * 1_000).toISOString().replace("Z", "000+00:00"),
      "x",
    ),
  );

describe("paging", () => {
  it("pages on past a page boundary microseconds apart, to the last row and no further", async () => {
    const rows = book(INBOX_LIST_LIMIT + 1);
    // The last row of page one and the first of page two: 300µs apart.
    rows[INBOX_LIST_LIMIT - 1]!.lastAt = "2026-08-23T04:00:00.000400+00:00";
    rows[INBOX_LIST_LIMIT]!.lastAt = "2026-08-23T04:00:00.000100+00:00";
    const s = server(rows);
    const held = await readPages(s.fetchPage, 1);
    expect(held.more).toBe(true);
    // The next page starts from the server's last row.
    expect(held.cursor).toBe(rows[INBOX_LIST_LIMIT - 1]);
    const next = await s.fetchPage(held.cursor!);
    expect(next.map((t) => t.id)).toEqual([rows[INBOX_LIST_LIMIT]!.id]);
    const all = mergeThreads(held.rows, next);
    expect(all.map((t) => t.id)).toEqual(rows.map((t) => t.id));
    expect(await s.fetchPage(next.at(-1))).toEqual([]);
  });

  it("reads every page the operator loaded again, so an older row can leave", async () => {
    const rows = book(INBOX_LIST_LIMIT + 3);
    const s = server(rows);
    const held = await readPages(s.fetchPage, 2);
    expect(held.rows).toHaveLength(INBOX_LIST_LIMIT + 3);
    // Reassigned out of the view: past the first page, so only a read of the
    // second page can see it go.
    const gone = rows.splice(INBOX_LIST_LIMIT + 1, 1)[0]!;
    rows[INBOX_LIST_LIMIT] = { ...rows[INBOX_LIST_LIMIT]!, assignedUserId: "someone-else" };
    const again = await readPages(s.fetchPage, held.pages);
    expect(again.rows.map((t) => t.id)).not.toContain(gone.id);
    expect(again.rows).toHaveLength(INBOX_LIST_LIMIT + 2);
    expect(again.rows[INBOX_LIST_LIMIT]!.assignedUserId).toBe("someone-else");
    expect(again.pages).toBe(2);
    expect(again.more).toBe(false);
  });

  it("reads one page when the first is the whole list", async () => {
    const s = server(book(7));
    const held = await readPages(s.fetchPage, 3);
    expect(held).toMatchObject({ more: false, pages: 1 });
    expect(s.reads).toEqual([undefined]);
  });

  it("keeps a delta for a thread past the pages held for its own page", () => {
    const rows = book(3);
    const held = { rows: rows.slice(0, 2), more: true, cursor: rows[1]!, pages: 1, polls: 3 };
    // A receipt moved the watermark of a thread whose last message is older.
    expect(mergeDeltas(held, [rows[2]!]).map((t) => t.id)).toEqual(
      rows.slice(0, 2).map((t) => t.id),
    );
    expect(mergeDeltas({ ...held, more: false }, [rows[2]!])).toHaveLength(3);
  });
});
