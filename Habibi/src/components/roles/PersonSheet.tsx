import { Lock } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Lozenge } from "@/components/ui/lozenge";
import { RecordsAvatarMark } from "@/components/records/RecordsTable";
import { useConfirm } from "@/components/ui/use-confirm";
import type { DirectoryUser } from "@/api/users";
import type { RolesCatalog } from "@/api/roles";
import { fmtRelative } from "@/lib/format";
import {
  effectivePermissionIds,
  groupPermissions,
  moduleLabel,
  operatorMayBeEdited,
} from "./access";

export function PersonSheet({
  user,
  roles,
  catalog,
  onClose,
  onToggleRole,
  onSetStatus,
}: {
  user: DirectoryUser | null;
  roles: { id: string; name: string }[];
  catalog: RolesCatalog | undefined;
  onClose: () => void;
  onToggleRole: (userId: string, roleId: string, current: string[]) => void;
  onSetStatus: (userId: string, status: "active" | "inactive") => void;
}) {
  const { confirm, confirmDialog } = useConfirm();
  if (!user) return null;
  const editable = operatorMayBeEdited(user);
  const granted = effectivePermissionIds(user.roleIds, catalog);
  const groups = groupPermissions(catalog?.permissions ?? []);
  const email = user.email ?? user.upn ?? user.id;

  const deactivate = async () => {
    if (!editable) return;
    const next = user.status === "active" ? "inactive" : "active";
    if (next === "inactive") {
      const ok = await confirm({
        title: "Deactivate this operator?",
        description: `${user.name} keeps a directory row with no grants. Send a new invite from Settings to restore a role and email them. The last Admin cannot be deactivated.`,
        confirmLabel: "Deactivate",
        cancelLabel: "Keep active",
      });
      if (!ok) return;
    }
    onSetStatus(user.id, next);
  };

  return (
    <>
      <Sheet open={user !== null} onOpenChange={(open) => !open && onClose()}>
        <SheetContent side="right" className="flex w-full flex-col overflow-y-auto sm:max-w-xl">
          <SheetHeader className="text-left">
            <SheetTitle className="sr-only">{user.name}</SheetTitle>
            <div className="flex items-start gap-150 pr-400">
              <RecordsAvatarMark label={user.name} className="h-10 w-10" />
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-100">
                  <span className="heading-small font-semibold text-text">{user.name}</span>
                  {user.bootstrapAdmin ? (
                    <Lozenge tone="discovery">
                      <Lock className="h-3 w-3" />
                      Super admin
                    </Lozenge>
                  ) : null}
                  <Lozenge tone={user.status === "active" ? "success" : "neutral"}>
                    {user.status === "active" ? "Active" : "Inactive"}
                  </Lozenge>
                </div>
                <p className="mt-050 text-body-small text-text-subtle">{email}</p>
                <p className="mt-025 text-body-small text-text-subtlest">
                  Microsoft · last sign-in {fmtRelative(user.lastLoginAt)}
                </p>
              </div>
            </div>
          </SheetHeader>

          {!editable ? (
            <p className="mt-200 rounded-medium border border-border bg-background-neutral-subtle px-150 py-100 text-body-small text-text-subtle">
              This identity is the bootstrap Admin. Roles and status cannot be changed.
            </p>
          ) : null}

          <section className="mt-300">
            <h3 className="text-body font-semibold text-text">Roles</h3>
            <p className="mb-150 mt-025 text-body-small text-text-subtle">
              Grants are the union of every role this person holds.
            </p>
            <div className="space-y-100">
              {roles.map((role) => (
                <label key={role.id} className="flex items-center gap-100 text-body-small">
                  <Checkbox
                    checked={user.roleIds.includes(role.id)}
                    disabled={!editable}
                    onCheckedChange={() => onToggleRole(user.id, role.id, user.roleIds)}
                  />
                  {role.name}
                </label>
              ))}
            </div>
          </section>

          <section className="mt-300">
            <h3 className="text-body font-semibold text-text">Effective access</h3>
            <p className="mb-150 mt-025 text-body-small text-text-subtle">
              What the assigned roles allow, grouped by module. There is no per-person override.
            </p>
            <div className="space-y-200">
              {groups.map((group) => (
                <div key={group.module}>
                  <div className="mb-075 text-body-small font-semibold capitalize text-text-subtle">
                    {moduleLabel(group.module)}
                  </div>
                  <ul className="space-y-050">
                    {group.items.map((perm) => (
                      <li
                        key={perm.id}
                        className={
                          granted.has(perm.id)
                            ? "text-body-small text-text"
                            : "text-body-small text-text-subtlest"
                        }
                      >
                        {granted.has(perm.id) ? "Allowed · " : "Not granted · "}
                        {perm.description}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>

          <div className="mt-auto pt-300">
            <Button
              type="button"
              variant={user.status === "active" ? "danger" : "primary"}
              disabled={!editable}
              onClick={() => void deactivate()}
            >
              {user.status === "active" ? "Deactivate" : "Activate"}
            </Button>
          </div>
        </SheetContent>
      </Sheet>
      {confirmDialog}
    </>
  );
}
