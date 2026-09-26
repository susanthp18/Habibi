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

export function isBigtappInviteEmail(raw: string) {
  const email = raw.trim().toLowerCase();
  if (email.split("@").length !== 2) return false;
  if (!email.endsWith("@bigtapp.ai")) return false;
  return email.slice(0, -"@bigtapp.ai".length).length > 0;
}

export function moduleLabel(module: string) {
  return module.replace(/_/g, " ");
}

export function groupPermissions(
  permissions: { id: string; module: string; action: string; description: string }[],
) {
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
