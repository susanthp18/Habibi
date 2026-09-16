import { describe, expect, it } from "vitest";

import type { RolesCatalog } from "@/api/agent-studio";
import {
  effectivePermissionIds,
  isAdminRoleName,
  isBigtappInviteEmail,
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

  it("accepts only @bigtapp.ai invite addresses", () => {
    expect(isBigtappInviteEmail("alex@bigtapp.ai")).toBe(true);
    expect(isBigtappInviteEmail("  Alex@Bigtapp.ai ")).toBe(true);
    expect(isBigtappInviteEmail("alex@gmail.com")).toBe(false);
    expect(isBigtappInviteEmail("bigtapp.ai")).toBe(false);
  });
});
