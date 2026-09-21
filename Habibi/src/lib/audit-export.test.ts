import { describe, expect, it } from "vitest";

import { planAuditExport } from "./audit-export";

describe("planAuditExport", () => {
  it("maps selected interaction ids onto redaction record ids", () => {
    expect(
      planAuditExport(
        ["IX-1", "IX-2"],
        [
          { id: "RD-1", callId: "IX-1" },
          { id: "RD-2", callId: "IX-2" },
        ],
      ),
    ).toEqual({ ok: true, recordIds: ["RD-1", "RD-2"] });
  });

  it("names missing calls instead of inventing a ZIP", () => {
    expect(planAuditExport(["IX-1", "IX-missing"], [{ id: "RD-1", callId: "IX-1" }])).toEqual({
      ok: false,
      missingCallIds: ["IX-missing"],
    });
  });
});
