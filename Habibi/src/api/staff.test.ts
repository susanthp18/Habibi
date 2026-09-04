import { describe, expect, it } from "vitest";

import { MOCK_STAFF } from "./staff";

describe("staff roster mock", () => {
  it("does not call a bot active unless something can route to it", () => {
    // kaia-v2-4 is the only mouth in this fixture with a production
    // deployment. The other two are archived scaffolds kept so historical
    // seed rows still resolve; they cannot take a call.
    const activeBots = MOCK_STAFF.filter((s) => s.kind === "bot" && s.status === "active");
    expect(activeBots.map((s) => s.id)).toEqual(["kaia-v2-4"]);
  });

  it("keeps the archived scaffolds for name resolution", () => {
    const byId = Object.fromEntries(MOCK_STAFF.map((s) => [s.id, s]));
    expect(byId["webchatbot"]?.status).toBe("archived");
    expect(byId["collectionsbot-v2-4"]?.status).toBe("archived");
  });
});
