import { toast } from "sonner";
import { useDirectoryUsers, usePatchUserStatus, usePutUserRoles } from "@/api/users";
import { LoadingState } from "@/components/ui/loading-state";

type RoleOption = { id: string; name: string };

export function PeopleSection({ roles }: { roles: RoleOption[] }) {
  const { data, isLoading, isError, error } = useDirectoryUsers();
  const putRoles = usePutUserRoles();
  const patchStatus = usePatchUserStatus();

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

  return (
    <section>
      <h2 className="mb-100 text-body font-semibold">People</h2>
      <p className="mb-200 text-body-small text-text-subtle">
        Who signed in through Microsoft, and which roles they hold. The last Admin cannot be demoted
        or deactivated.
      </p>
      {isLoading && !data ? (
        <div className="grid place-items-center py-300">
          <LoadingState label="Loading people" />
        </div>
      ) : isError ? (
        <div className="text-text-danger">
          {error instanceof Error ? error.message : "Failed to load people"}
        </div>
      ) : (
        <div className="space-y-200">
          {(data?.users ?? []).map((user) => (
            <div key={user.id} className="rounded-medium border border-border p-200">
              <div className="mb-100 flex flex-wrap items-baseline justify-between gap-100">
                <div>
                  <div className="text-body font-semibold">{user.name}</div>
                  <div className="text-body-small text-text-subtle">
                    {user.upn ?? user.id}
                    {user.bootstrapAdmin ? " · bootstrap Admin" : ""}
                    {user.status === "inactive" ? " · inactive" : ""}
                  </div>
                </div>
                <button
                  type="button"
                  className="text-body-small text-link hover:underline"
                  onClick={() =>
                    setStatus(user.id, user.status === "active" ? "inactive" : "active")
                  }
                >
                  {user.status === "active" ? "Deactivate" : "Activate"}
                </button>
              </div>
              <div className="flex flex-wrap gap-150">
                {roles.map((role) => (
                  <label key={role.id} className="flex items-center gap-100 text-body-small">
                    <input
                      type="checkbox"
                      checked={user.roleIds.includes(role.id)}
                      onChange={() => toggleRole(user.id, role.id, user.roleIds)}
                    />
                    {role.name}
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
