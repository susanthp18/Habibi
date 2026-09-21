import { describe, expect, it } from "vitest";

import { can, needsAccessRequest, type Me } from "./me";

const viewer: Me = {
  id: "u-viewer",
  name: "A Viewer",
  kind: "human",
  team: null,
  status: "active",
  tenantId: "t1",
  permissions: ["perm-analytics-read", "perm-kb-read", "perm-bot-read"],
};

describe("needsAccessRequest", () => {
  it("asks first-login operators with no grants to request access", () => {
    expect(needsAccessRequest({ ...viewer, permissions: [] })).toBe(true);
  });

  it("asks inactive operators to request access even if a role is on the row", () => {
    expect(needsAccessRequest({ ...viewer, status: "inactive" })).toBe(true);
  });

  it("lets an active operator with grants through", () => {
    expect(needsAccessRequest(viewer)).toBe(false);
    expect(needsAccessRequest(undefined)).toBe(false);
  });
});

describe("can", () => {
  it("hides Roles & access without perm-admin-write", () => {
    expect(can(viewer, "perm-admin-write")).toBe(false);
    expect(can(undefined, "perm-admin-write")).toBe(false);
  });

  it("shows Roles & access when the actor holds perm-admin-write", () => {
    expect(can({ ...viewer, permissions: ["perm-admin-write"] }, "perm-admin-write")).toBe(true);
  });
});
