import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Lozenge } from "@/components/ui/lozenge";
import { Empty } from "@/components/ui/empty";
import {
  RecordsAvatarMark,
  RecordsTable,
  type RecordsColumn,
} from "@/components/records/RecordsTable";
import type { DirectoryUser } from "@/api/users";
import { useDirectoryUsers, usePatchUserStatus, usePutUserRoles } from "@/api/users";
import type { RolesCatalog } from "@/api/agent-studio";
import { fmtRelative } from "@/lib/format";
import { PersonSheet } from "./PersonSheet";

const NO_USERS: DirectoryUser[] = [];

export function PeopleTab({ catalog }: { catalog: RolesCatalog | undefined }) {
  const { data, isPending, isError, error } = useDirectoryUsers();
  const putRoles = usePutUserRoles();
  const patchStatus = usePatchUserStatus();
  const [q, setQ] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const roles = (catalog?.roles ?? []).map((role) => ({ id: role.id, name: role.name }));
  const users = data?.users ?? NO_USERS;

  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return users;
    return users.filter((user) => {
      const hay = [user.name, user.email, user.upn, user.roleNames.join(" ")]
        .join(" ")
        .toLowerCase();
      return hay.includes(s);
    });
  }, [users, q]);

  const active = users.find((user) => user.id === activeId) ?? null;

  const toggleRole = (userId: string, roleId: string, current: string[]) => {
    const next = current.includes(roleId)
      ? current.filter((id) => id !== roleId)
      : [...current, roleId];
    void putRoles
      .mutateAsync({ userId, roleIds: next })
      .then(() => toast.success("Roles saved"))
      .catch((err: Error) => toast.error(err.message));
  };

  const setStatus = (userId: string, status: "active" | "inactive") => {
    void patchStatus
      .mutateAsync({ userId, status })
      .then(() => toast.success(status === "active" ? "User activated" : "User deactivated"))
      .catch((err: Error) => toast.error(err.message));
  };

  const columns = useMemo<RecordsColumn<DirectoryUser>[]>(
    () => [
      {
        id: "name",
        header: "Name",
        sticky: true,
        rowActivator: true,
        sortable: true,
        sortValue: (row) => row.name,
        cell: (row) => (
          <div className="flex min-w-0 items-center gap-100">
            <RecordsAvatarMark label={row.name} />
            <div className="min-w-0">
              <div className="truncate font-medium">{row.name}</div>
              <div className="truncate text-body-small text-text-subtle">
                {row.email ?? row.upn ?? row.id}
              </div>
            </div>
          </div>
        ),
      },
      {
        id: "roles",
        header: "Roles",
        cell: (row) => (
          <div className="flex flex-wrap gap-050">
            {row.bootstrapAdmin ? <Lozenge tone="discovery">Super admin</Lozenge> : null}
            {row.roleNames.length === 0 ? (
              <span className="text-text-subtlest">None</span>
            ) : (
              row.roleNames.map((name) => (
                <Lozenge key={name} tone="information">
                  {name}
                </Lozenge>
              ))
            )}
          </div>
        ),
      },
      {
        id: "status",
        header: "Status",
        sortable: true,
        sortValue: (row) => row.status,
        cell: (row) => (
          <Lozenge tone={row.status === "active" ? "success" : "neutral"}>
            {row.status === "active" ? "Active" : "Inactive"}
          </Lozenge>
        ),
      },
      {
        id: "lastLogin",
        header: "Last sign-in",
        sortable: true,
        sortValue: (row) => row.lastLoginAt ?? "",
        cell: (row) => (
          <span className="text-body-small text-text-subtle">{fmtRelative(row.lastLoginAt)}</span>
        ),
      },
    ],
    [],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-100 border-b border-border px-300 py-150">
        <div className="relative max-w-md flex-1">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
          <Input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="Search name or email"
            className="pl-400"
            size="compact"
          />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden p-300">
        {!isPending && !isError && users.length === 0 ? (
          <Empty title="No Microsoft sign-ins yet">
            People appear here after they sign in with Entra. Invite them from Settings.
          </Empty>
        ) : (
          <RecordsTable
            rows={rows}
            getRowId={(row) => row.id}
            columns={columns}
            isLoading={isPending}
            isError={isError}
            error={error}
            errorLabel="people"
            emptyMessage="No people match your search."
            ariaLabel="Operators"
            activeRowId={activeId}
            onRowClick={(row) => setActiveId(row.id)}
            className="h-full"
            tableClassName="min-w-full"
          />
        )}
      </div>
      <PersonSheet
        user={active}
        roles={roles}
        catalog={catalog}
        onClose={() => setActiveId(null)}
        onToggleRole={toggleRole}
        onSetStatus={setStatus}
      />
    </div>
  );
}
