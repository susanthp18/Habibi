import type { RolesCatalog } from "@/api/roles";

export function normalizeRoleName(name: string) {
  return name.trim().toLowerCase().replace(/[-\s]/g, "_");
}

export function isAdminRoleName(name: string) {
  return normalizeRoleName(name) === "admin";
}

export function isViewerRoleName(name: string) {
  return normalizeRoleName(name) === "viewer";
}

export function operatorMayBeEdited(user: { bootstrapAdmin: boolean }) {
  return !user.bootstrapAdmin;
}

/** Shape only; which domains may be invited is the server's (INVITE_ALLOWED_DOMAINS). */
export function isInviteEmail(raw: string) {
  const [local = "", domain = "", ...rest] = raw.trim().toLowerCase().split("@");
  return rest.length === 0 && local.length > 0 && domain.includes(".");
}

/** Voice Studio's maker and checker roles: going live takes both. */
export function studioRoleNote(name: string) {
  const n = normalizeRoleName(name);
  if (n === "voice_designer") return "Builds and rehearses agents; cannot publish";
  if (n === "release_approver") return "Publishes agents and approves tools; cannot edit";
  return null;
}

export function moduleLabel(module: string) {
  return module.replace(/_/g, " ");
}

export function groupPermissions(permissions: RolesCatalog["permissions"]) {
  const byModule = new Map<string, typeof permissions>();
  for (const perm of permissions) {
    const list = byModule.get(perm.module) ?? [];
    list.push(perm);
    byModule.set(perm.module, list);
  }
  return [...byModule.entries()].map(([module, items]) => ({ module, items }));
}

export function effectivePermissionIds(roleIds: string[], catalog: RolesCatalog | undefined) {
  const granted = new Set<string>();
  if (!catalog) return granted;
  for (const roleId of roleIds) {
    const role = catalog.roles?.find((item) => item.id === roleId);
    if (!role) continue;
    if (isAdminRoleName(role.name)) {
      for (const perm of catalog.permissions) granted.add(perm.id);
      continue;
    }
    for (const permId of role.permissionIds) granted.add(permId);
  }
  return granted;
}
