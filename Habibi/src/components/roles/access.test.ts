import { describe, expect, it } from "vitest";

import type { RolesCatalog } from "@/api/roles";
import {
  effectivePermissionIds,
  isAdminRoleName,
  isInviteEmail,
  studioRoleNote,
  operatorMayBeEdited,
} from "./access";

const catalog: RolesCatalog = {
  permissions: [
    { id: "perm-admin-write", module: "admin", action: "write", description: "Admin" },
    { id: "perm-customers-read", module: "customers", action: "read", description: "Read" },
  ],
  agentPublishRoles: [],
  grants: [],
  roles: [
    { id: "role-admin", name: "Admin", permissionIds: ["perm-admin-write"] },
    { id: "role-viewer", name: "Viewer", permissionIds: ["perm-customers-read"] },
  ],
};

describe("roles access helpers", () => {
  it("treats Admin as a superuser regardless of listed grants", () => {
    expect(isAdminRoleName("Admin")).toBe(true);
    const granted = effectivePermissionIds(["role-admin"], catalog);
    expect(granted.has("perm-admin-write")).toBe(true);
    expect(granted.has("perm-customers-read")).toBe(true);
  });

  it("locks the bootstrap operator", () => {
    expect(operatorMayBeEdited({ bootstrapAdmin: true })).toBe(false);
    expect(operatorMayBeEdited({ bootstrapAdmin: false })).toBe(true);
  });

  it("checks invite address shape; the server owns the domain list", () => {
    expect(isInviteEmail("alex@bigtapp.ai")).toBe(true);
    expect(isInviteEmail("  Alex@Bank.co.in ")).toBe(true);
    expect(isInviteEmail("bigtapp.ai")).toBe(false);
    expect(isInviteEmail("@bigtapp.ai")).toBe(false);
  });

  it("names the Voice Studio maker and checker", () => {
    expect(studioRoleNote("Voice designer")).toMatch(/cannot publish/);
    expect(studioRoleNote("Release approver")).toMatch(/cannot edit/);
    expect(studioRoleNote("Agent")).toBeNull();
  });
});
