import { useState } from "react";
import { toast } from "sonner";
import { Checkbox } from "@/components/ui/checkbox";
import { Lozenge } from "@/components/ui/lozenge";
import { LoadingState } from "@/components/ui/loading-state";
import { QueryErrorBanner } from "@/components/ui/query-state";
import { cn } from "@/lib/utils";
import type { RolesCatalog } from "@/api/roles";
import { usePatchRolePermissions } from "@/api/roles";
import { groupPermissions, isAdminRoleName, moduleLabel, studioRoleNote } from "./access";

export function RolesMatrix({
  catalog,
  canEdit,
  isLoading,
  isError,
  error,
}: {
  catalog: RolesCatalog | undefined;
  canEdit: boolean;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
}) {
  const patch = usePatchRolePermissions();
  const roles = catalog?.roles ?? [];
  const [activeId, setActiveId] = useState(roles[0]?.id ?? "");
  const active = roles.find((role) => role.id === activeId) ?? roles[0];
  const groups = groupPermissions(catalog?.permissions ?? []);
  const adminLocked = active ? isAdminRoleName(active.name) : false;

  const toggle = (permissionId: string) => {
    if (!active || adminLocked || !canEdit) return;
    const current = active.permissionIds;
    const next = current.includes(permissionId)
      ? current.filter((id) => id !== permissionId)
      : [...current, permissionId];
    void patch
      .mutateAsync({ roleId: active.id, permissionIds: next })
      .then(() => toast.success("Grants saved"))
      .catch((err: Error) => toast.error(err.message));
  };

  if (isLoading && !catalog) {
    return (
      <div className="grid place-items-center py-400">
        <LoadingState label="Loading roles" />
      </div>
    );
  }
  if (isError) {
    return <QueryErrorBanner label="roles" error={error} />;
  }
  if (!active) return null;

  return (
    <div className="flex min-h-0 flex-1 gap-300 overflow-hidden p-300">
      <nav className="w-56 shrink-0 overflow-auto rounded-medium border border-border bg-surface">
        {roles.map((role) => (
          <button
            key={role.id}
            type="button"
            onClick={() => setActiveId(role.id)}
            className={cn(
              "flex w-full flex-col items-start gap-025 border-b border-border px-150 py-150 text-left last:border-b-0",
              role.id === active.id
                ? "bg-background-selected text-text-selected"
                : "hover:bg-background-neutral-subtle-hovered",
            )}
          >
            <span className="text-body font-medium">{role.name}</span>
            {studioRoleNote(role.name) ? (
              <span className="text-body-small text-text-subtle">{studioRoleNote(role.name)}</span>
            ) : null}
            {isAdminRoleName(role.name) ? (
              <span className="text-body-small text-text-subtle">Superuser</span>
            ) : null}
          </button>
        ))}
      </nav>
      <div className="min-h-0 min-w-0 flex-1 overflow-auto rounded-medium border border-border bg-surface p-200">
        <div className="mb-200 flex flex-wrap items-center gap-100">
          <h2 className="text-body font-semibold">{active.name}</h2>
          {studioRoleNote(active.name) ? (
            <Lozenge tone="information">{studioRoleNote(active.name)}</Lozenge>
          ) : null}
          {adminLocked ? <Lozenge tone="discovery">All permissions</Lozenge> : null}
        </div>
        {adminLocked ? (
          <p className="mb-200 rounded-medium border border-border bg-background-neutral-subtle px-150 py-100 text-body-small text-text-subtle">
            Admin is a superuser — the enforcer grants every permission. These checkboxes cannot be
            narrowed.
          </p>
        ) : null}
        <div className="space-y-200">
          {groups.map((group) => (
            <section key={group.module}>
              <h3 className="mb-100 text-body-small font-semibold capitalize text-text-subtle">
                {moduleLabel(group.module)}
              </h3>
              <div className="grid gap-100 md:grid-cols-2">
                {group.items.map((perm) => {
                  const checked = adminLocked || active.permissionIds.includes(perm.id);
                  return (
                    <label key={perm.id} className="flex items-start gap-100 text-body-small">
                      <Checkbox
                        className="mt-025"
                        checked={checked}
                        disabled={!canEdit || adminLocked}
                        onCheckedChange={() => toggle(perm.id)}
                      />
                      <span>
                        <span className="text-text">{perm.description}</span>
                        <span className="ml-075 font-mono text-body-tiny text-text-subtlest">
                          {perm.id}
                        </span>
                        {perm.studioActions?.length ? (
                          <span className="mt-025 block text-body-tiny text-text-subtle">
                            In Voice Studio: {perm.studioActions.join(" · ")}
                          </span>
                        ) : null}
                      </span>
                    </label>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
