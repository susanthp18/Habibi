import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/shell/AppShell";
import { usePatchRolePermissions, useRolesCatalog } from "@/api/agent-studio";
import { LoadingState } from "@/components/ui/loading-state";
import { Lozenge } from "@/components/ui/lozenge";
import { OutboundControlPanel } from "@/components/platform/OutboundControlPanel";
import { toast } from "sonner";

export const Route = createFileRoute("/roles")({
  head: () => ({
    meta: [
      { title: "Roles & access — BigBound AI" },
      {
        name: "description",
        content: "Grant agent.publish, connector.attach, policy.export. Roles are a product.",
      },
    ],
  }),
  component: RolesPage,
});

function RolesPage() {
  const { data, isLoading, isError, error } = useRolesCatalog();
  const patch = usePatchRolePermissions();

  const toggle = (roleId: string, permissionId: string, current: string[]) => {
    const next = current.includes(permissionId)
      ? current.filter((id) => id !== permissionId)
      : [...current, permissionId];
    void patch
      .mutateAsync({ roleId, permissionIds: next })
      .then(() => toast.success("Grants saved"))
      .catch((err: Error) => toast.error(err.message));
  };

  return (
    <AppShell>
      <div className="flex h-full flex-col">
        <header className="border-b border-border px-400 py-200">
          <h1 className="heading-medium font-semibold">Roles & access</h1>
          <p className="text-body-small text-text-subtle">
            Who can publish, attach connectors, or export policy — and whether this deployment may
            telephone anyone at all. Admin keeps admin.write.
          </p>
        </header>
        {/*
          The outbound gate sits outside the roles catalog's loading and error
          branches on purpose. It is a separate query, and a roles fetch that
          failed must not take the kill switch off the screen with it — that is
          exactly when an operator most needs to reach it.
        */}
        <div className="min-h-0 flex-1 space-y-300 overflow-auto p-400">
          <OutboundControlPanel />
          {isLoading && !data ? (
            <div className="grid place-items-center py-400">
              <LoadingState label="Loading roles" />
            </div>
          ) : isError ? (
            <div className="text-text-danger">
              {error instanceof Error ? error.message : "Failed to load"}
            </div>
          ) : (
            <>
              <div>
                <h2 className="mb-100 text-body font-semibold">agent.publish</h2>
                <div className="flex flex-wrap gap-100">
                  {(data?.agentPublishRoles ?? []).length === 0 ? (
                    <span className="text-body-small text-text-subtle">
                      No role currently holds agent.publish.
                    </span>
                  ) : (
                    data?.agentPublishRoles.map((role) => (
                      <Lozenge key={role} tone="information">
                        {role}
                      </Lozenge>
                    ))
                  )}
                </div>
              </div>
              {(data?.roles ?? []).map((role) => (
                <div key={role.id} className="rounded-medium border border-border p-200">
                  <div className="mb-100 text-body font-semibold">{role.name}</div>
                  <div className="grid gap-050 md:grid-cols-2">
                    {(data?.permissions ?? []).map((p) => (
                      <label key={p.id} className="flex items-start gap-100 text-body-small">
                        <input
                          type="checkbox"
                          checked={role.permissionIds.includes(p.id)}
                          onChange={() => toggle(role.id, p.id, role.permissionIds)}
                        />
                        <span>
                          <span className="font-mono text-body-tiny">{p.id}</span>
                          <span className="ml-075 text-text-subtle">{p.description}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}
