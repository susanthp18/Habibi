import { describe, expect, it } from "vitest";

import { can, type Me } from "@/api/me";

function me(permissions: string[]): Me {
  return {
    id: "u-1",
    name: "Operator",
    kind: "human",
    team: null,
    status: "active",
    tenantId: "t-1",
    permissions,
  };
}

describe("settings sections", () => {
  it("shows invites and outbound only with admin.write", () => {
    expect(can(me(["perm-customers-read"]), "perm-admin-write")).toBe(false);
    expect(can(me(["perm-admin-write"]), "perm-admin-write")).toBe(true);
  });
});
