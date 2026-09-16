import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useRolesCatalog } from "@/api/agent-studio";
import { can, useMe } from "@/api/me";
import { useDirectoryUsers } from "@/api/users";
import { Lozenge } from "@/components/ui/lozenge";
import { cn } from "@/lib/utils";
import { PeopleTab } from "@/components/roles/PeopleTab";
import { RolesMatrix } from "@/components/roles/RolesMatrix";

export const Route = createFileRoute("/_app/roles")({
  head: () => ({
    meta: [
      { title: "Roles & access — PayInt" },
      {
        name: "description",
        content: "Who signed in through Microsoft, and what each role may do.",
      },
    ],
  }),
  component: RolesPage,
});

function RolesPage() {
  const catalog = useRolesCatalog();
  const people = useDirectoryUsers();
  const me = useMe();
  const canEdit = can(me.data, "perm-admin-write");
  const [tab, setTab] = useState<"people" | "roles">("people");
  const peopleCount = people.data?.users.length ?? 0;
  const roleCount = catalog.data?.roles?.length ?? 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-border bg-surface px-400 py-200">
        <h1 className="heading-medium font-semibold">Roles & access</h1>
        <p className="text-body-small text-text-subtle">
          Microsoft sign-ins and the roles they hold. New people start as Viewer until you grant
          more.
        </p>
      </header>
      <div className="flex items-center gap-050 border-b border-border bg-surface px-300">
        {(
          [
            ["people", "People", peopleCount],
            ["roles", "Roles", roleCount],
          ] as const
        ).map(([key, label, count]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={cn(
              "border-b-2 px-150 py-150 text-sm font-medium",
              tab === key
                ? "border-border-brand text-text-brand"
                : "border-transparent text-text-subtle hover:text-text",
            )}
          >
            {label}
            <Lozenge tone="neutral" className="ml-075">
              {count}
            </Lozenge>
          </button>
        ))}
      </div>
      {tab === "people" ? (
        <PeopleTab catalog={catalog.data} />
      ) : (
        <RolesMatrix
          catalog={catalog.data}
          canEdit={canEdit}
          isLoading={catalog.isLoading}
          isError={catalog.isError}
          error={catalog.error}
        />
      )}
    </div>
  );
}
