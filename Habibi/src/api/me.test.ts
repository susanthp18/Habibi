import { describe, expect, it } from "vitest";

import { can, type Me } from "./me";

const viewer: Me = {
  id: "u-viewer",
  name: "A Viewer",
  kind: "human",
  team: null,
  status: "active",
  tenantId: "t1",
  permissions: ["perm-analytics-read", "perm-kb-read", "perm-bot-read"],
};

describe("can", () => {
  it("hides Roles & access without perm-admin-write", () => {
    expect(can(viewer, "perm-admin-write")).toBe(false);
    expect(can(undefined, "perm-admin-write")).toBe(false);
  });

  it("shows Roles & access when the actor holds perm-admin-write", () => {
    expect(can({ ...viewer, permissions: ["perm-admin-write"] }, "perm-admin-write")).toBe(true);
  });
});
