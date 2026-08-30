// -----------------------------------------------------------------------------
// mockDisputeSla mirrors backend/db.py::_dispute_sla line for line, and the two
// have to agree or the disputes board and the Customer 360 tab describe the same
// dispute differently — which is the bug the shared module was created to end.
//
// It reads Date.now() directly rather than taking an injected clock, so the
// clock is frozen here instead. The 40-hour filing window makes the 25% warn
// threshold land on a round 10 hours, so "just inside" and "just outside" are
// one minute apart rather than a rounding argument.
// -----------------------------------------------------------------------------

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockDisputeSla } from "./dispute-sla";

const NOW = "2026-03-10T12:00:00Z";

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(NOW));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the warn threshold", () => {
  it("is at risk with just under a quarter of the window left", () => {
    // 40h window, 9h59m remaining — one minute inside the 10h threshold.
    const sla = mockDisputeSla({
      capturedAt: "2026-03-09T05:59:00Z",
      slaDueAt: "2026-03-10T21:59:00Z",
      status: "open",
    });
    expect(sla.sla).toBe("warn");
    expect(sla.slaLabel).toBe("9h 59m left");
    expect(sla.slaMinutes).toBe(599);
  });

  it("is still ok with exactly a quarter of the window left", () => {
    // Same 40h window, 10h remaining. The comparison is strict, so the
    // threshold itself is not yet at risk.
    const sla = mockDisputeSla({
      capturedAt: "2026-03-09T06:00:00Z",
      slaDueAt: "2026-03-10T22:00:00Z",
      status: "open",
    });
    expect(sla.sla).toBe("ok");
    expect(sla.slaLabel).toBe("10h 0m left");
    expect(sla.slaMinutes).toBe(600);
  });

  it("is ok when the due date is far out", () => {
    const sla = mockDisputeSla({
      capturedAt: "2026-03-10T11:00:00Z",
      slaDueAt: "2026-04-09T12:00:00Z",
      status: "open",
    });
    expect(sla.sla).toBe("ok");
  });
});

describe("past due", () => {
  it("is a breach, counted as overdue", () => {
    const sla = mockDisputeSla({
      capturedAt: "2026-03-09T09:30:00Z",
      slaDueAt: "2026-03-10T09:30:00Z",
      status: "open",
    });
    expect(sla.sla).toBe("breach");
    expect(sla.slaLabel).toBe("2h 30m over");
    expect(sla.slaMinutes).toBe(-150);
  });

  it("breaches the instant the due date passes", () => {
    const sla = mockDisputeSla({
      capturedAt: "2026-03-09T12:00:00Z",
      slaDueAt: "2026-03-10T11:59:00Z",
      status: "open",
    });
    expect(sla.sla).toBe("breach");
  });
});

describe("closed disputes", () => {
  it("is done once resolved", () => {
    const sla = mockDisputeSla({
      capturedAt: "2026-03-09T12:00:00Z",
      slaDueAt: "2026-03-10T22:00:00Z",
      status: "resolved",
    });
    expect(sla).toEqual({ sla: "done", slaLabel: "Closed", slaMinutes: 0 });
  });

  it("is done once rejected", () => {
    const sla = mockDisputeSla({
      capturedAt: "2026-03-09T12:00:00Z",
      slaDueAt: "2026-03-10T22:00:00Z",
      status: "rejected",
    });
    expect(sla.sla).toBe("done");
  });

  it("does not report a breach on a dispute that was already closed", () => {
    // The status check comes first on purpose — a dispute settled after its
    // due date is finished, not overdue.
    const sla = mockDisputeSla({
      capturedAt: "2026-03-08T12:00:00Z",
      slaDueAt: "2026-03-09T12:00:00Z",
      status: "resolved",
    });
    expect(sla.sla).toBe("done");
  });
});

describe("no due date", () => {
  it("is open, not overdue, when slaDueAt is null", () => {
    const sla = mockDisputeSla({
      capturedAt: "2026-03-09T12:00:00Z",
      slaDueAt: null,
      status: "open",
    });
    expect(sla).toEqual({ sla: "ok", slaLabel: "Open", slaMinutes: 0 });
  });

  it("is open when slaDueAt is absent", () => {
    const sla = mockDisputeSla({ capturedAt: "2026-03-09T12:00:00Z", status: "open" });
    expect(sla.sla).toBe("ok");
    expect(sla.slaLabel).toBe("Open");
  });

  it("is open when slaDueAt cannot be parsed", () => {
    const sla = mockDisputeSla({
      capturedAt: "2026-03-09T12:00:00Z",
      slaDueAt: "not a date",
      status: "open",
    });
    expect(sla.sla).toBe("ok");
    expect(sla.slaLabel).toBe("Open");
  });
});
