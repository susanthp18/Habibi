import { useState } from "react";
import { toast } from "sonner";
import { useRolesCatalog } from "@/api/roles";
import {
  useAccessRequests,
  useApproveAccessRequest,
  useDenyAccessRequest,
  type AccessRequest,
} from "@/api/access-requests";
import { isViewerRoleName } from "@/components/roles/access";
import { Button } from "@/components/ui/button";
import { Empty } from "@/components/ui/empty";
import { Lozenge } from "@/components/ui/lozenge";
import { SelectField } from "@/components/ui/select";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";
import { useConfirm } from "@/components/ui/use-confirm";
import { fmtRelative } from "@/lib/format";

function statusTone(status: string): "success" | "warning" | "neutral" | "information" {
  if (status === "approved") return "success";
  if (status === "pending") return "information";
  if (status === "denied") return "neutral";
  return "warning";
}

export function AccessRequestsSection() {
  const catalog = useRolesCatalog();
  const list = useAccessRequests();
  const approve = useApproveAccessRequest();
  const deny = useDenyAccessRequest();
  const { confirm, confirmDialog } = useConfirm();
  const roles = catalog.data?.roles ?? [];
  const defaultRole = roles.find((role) => isViewerRoleName(role.name))?.id ?? roles[0]?.id ?? "";
  const [grantById, setGrantById] = useState<Record<string, string>>({});

  const onApprove = (row: AccessRequest) => {
    const roleId = grantById[row.id] || defaultRole;
    if (!roleId) {
      toast.error("Choose a role to grant");
      return;
    }
    void approve
      .mutateAsync({ requestId: row.id, roleId })
      .then(() => toast.success(`Granted ${roles.find((r) => r.id === roleId)?.name ?? "role"}`))
      .catch((err: Error) => toast.error(err.message));
  };

  const onDeny = async (row: AccessRequest) => {
    const ok = await confirm({
      title: "Deny this request?",
      description: `${row.userName} will stay on their current roles. They can ask again.`,
      confirmLabel: "Deny request",
      cancelLabel: "Keep pending",
    });
    if (!ok) return;
    void deny
      .mutateAsync(row.id)
      .then(() => toast.success("Request denied"))
      .catch((err: Error) => toast.error(err.message));
  };

  const columns: RecordsColumn<AccessRequest>[] = [
    {
      id: "who",
      header: "From",
      sticky: true,
      sortable: true,
      sortValue: (row) => row.userName,
      cell: (row) => (
        <div>
          <div className="font-medium">{row.userName}</div>
          <div className="text-body-small text-text-subtle">{row.userEmail ?? "—"}</div>
        </div>
      ),
    },
    {
      id: "page",
      header: "Page",
      sortable: true,
      sortValue: (row) => row.pagePath,
      cell: (row) => (
        <div>
          <div className="font-mono text-body-small">{row.pagePath}</div>
          {row.permissionLabel ? (
            <div className="text-body-small text-text-subtle">{row.permissionLabel}</div>
          ) : null}
        </div>
      ),
    },
    {
      id: "reason",
      header: "Reason",
      cell: (row) => <span className="text-body-small">{row.reason}</span>,
    },
    {
      id: "status",
      header: "Status",
      cell: (row) => (
        <Lozenge tone={statusTone(row.status)} className="capitalize">
          {row.status}
        </Lozenge>
      ),
    },
    {
      id: "when",
      header: "Requested",
      sortable: true,
      sortValue: (row) => row.requestedAt ?? "",
      cell: (row) => (
        <span className="text-body-small text-text-subtle">{fmtRelative(row.requestedAt)}</span>
      ),
    },
    {
      id: "actions",
      header: "",
      cell: (row) =>
        row.status === "pending" ? (
          <div className="flex flex-wrap items-center justify-end gap-100">
            <div className="w-40">
              <SelectField
                value={grantById[row.id] || defaultRole}
                onChange={(value) => setGrantById((prev) => ({ ...prev, [row.id]: value }))}
                options={roles.map((role) => ({ value: role.id, label: role.name }))}
                placeholder="Grant role"
                aria-label={`Role to grant ${row.userName}`}
                size="compact"
              />
            </div>
            <Button
              type="button"
              variant="primary"
              size="compact"
              loading={approve.isPending}
              onClick={() => onApprove(row)}
            >
              Approve
            </Button>
            <Button type="button" variant="danger" size="compact" onClick={() => void onDeny(row)}>
              Deny
            </Button>
          </div>
        ) : (
          <span className="text-body-small text-text-subtlest">
            {row.grantedRoleName ?? row.reviewedByName ?? "—"}
          </span>
        ),
    },
  ];

  const rows = list.data?.requests ?? [];
  const pending = rows.filter((row) => row.status === "pending").length;

  return (
    <section className="space-y-200">
      {confirmDialog}
      <div>
        <h2 className="text-body font-semibold">Access requests</h2>
        <p className="mt-025 text-body-small text-text-subtle">
          People who cannot open a page can send a reason. Approve by granting a role — PayInt
          authorizes by role, not per person.
          {pending ? ` ${pending} waiting.` : ""}
        </p>
      </div>
      {!list.isPending && !list.isError && rows.length === 0 ? (
        <Empty title="No access requests">
          When someone is refused a page, their ask lands here.
        </Empty>
      ) : (
        <RecordsTable
          rows={rows}
          getRowId={(row) => row.id}
          columns={columns}
          isLoading={list.isPending}
          isError={list.isError}
          error={list.error}
          errorLabel="access requests"
          emptyMessage="No access requests."
          ariaLabel="Access requests"
          tableClassName="min-w-full"
        />
      )}
    </section>
  );
}
