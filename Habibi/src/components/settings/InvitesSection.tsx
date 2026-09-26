import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { Lozenge } from "@/components/ui/lozenge";
import { Empty } from "@/components/ui/empty";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";
import { useConfirm } from "@/components/ui/use-confirm";
import { useRolesCatalog } from "@/api/roles";
import { ApiError } from "@/api/config";
import {
  useCreateInvite,
  useInvites,
  useResendInvite,
  useRevokeInvite,
  type OperatorInvite,
} from "@/api/invites";
import { isBigtappInviteEmail, isViewerRoleName } from "@/components/roles/access";
import { fmtRelative } from "@/lib/format";

function statusTone(status: string): "success" | "warning" | "neutral" | "information" {
  if (status === "accepted") return "success";
  if (status === "pending") return "information";
  if (status === "revoked") return "neutral";
  return "warning";
}

export function InvitesSection() {
  const catalog = useRolesCatalog();
  const invites = useInvites();
  const create = useCreateInvite();
  const resend = useResendInvite();
  const revoke = useRevokeInvite();
  const { confirm, confirmDialog } = useConfirm();
  const roles = catalog.data?.roles ?? [];
  const defaultRole = roles.find((role) => isViewerRoleName(role.name))?.id ?? roles[0]?.id ?? "";
  const [email, setEmail] = useState("");
  const [roleId, setRoleId] = useState(defaultRole);

  const selectedRole = roleId || defaultRole;

  const send = () => {
    const trimmed = email.trim();
    if (!isBigtappInviteEmail(trimmed)) {
      toast.error("Use a @bigtapp.ai address");
      return;
    }
    if (!selectedRole) {
      toast.error("Choose a starting role");
      return;
    }
    void create
      .mutateAsync({ email: trimmed, roleId: selectedRole })
      .then((body) => {
        setEmail("");
        if (body.invite.lastError === "smtp_disabled") {
          toast.success("Invite saved. Mail is not configured on this host.");
        } else if (body.invite.lastError) {
          toast.error(`Invite saved, but mail failed (${body.invite.lastError}). Use resend.`);
        } else {
          toast.success("Invite sent");
        }
      })
      .catch((err: Error) => {
        if (err instanceof ApiError && err.detail === "already_signed_in") {
          toast.error(
            "This person already has access. Change their role under Roles & access, or deactivate them and send a new invite.",
          );
          return;
        }
        toast.error(err.message);
      });
  };

  const onRevoke = async (row: OperatorInvite) => {
    const ok = await confirm({
      title: "Revoke this invite?",
      description: `${row.email} can still sign in with Microsoft and will land on the request-access form. They will not receive the starting role from this invite.`,
      confirmLabel: "Revoke invite",
      cancelLabel: "Keep invite",
    });
    if (!ok) return;
    void revoke
      .mutateAsync(row.id)
      .then(() => toast.success("Invite revoked"))
      .catch((err: Error) => toast.error(err.message));
  };

  const columns: RecordsColumn<OperatorInvite>[] = [
    {
      id: "email",
      header: "Email",
      sticky: true,
      sortable: true,
      sortValue: (row) => row.email,
      cell: (row) => <span className="font-medium">{row.email}</span>,
    },
    {
      id: "role",
      header: "Starting role",
      cell: (row) => <Lozenge tone="information">{row.roleName}</Lozenge>,
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
      id: "sent",
      header: "Sent",
      sortable: true,
      sortValue: (row) => row.sentAt ?? "",
      cell: (row) => (
        <span className="text-body-small text-text-subtle">{fmtRelative(row.sentAt)}</span>
      ),
    },
    {
      id: "actions",
      header: "",
      cell: (row) =>
        row.status === "pending" ? (
          <div className="flex justify-end gap-100">
            <Button
              type="button"
              variant="subtle"
              size="compact"
              loading={resend.isPending}
              onClick={() =>
                void resend
                  .mutateAsync(row.id)
                  .then((body) => {
                    if (body.invite.lastError) toast.error("Mail did not send. Try again.");
                    else toast.success("Invite resent");
                  })
                  .catch((err: Error) => toast.error(err.message))
              }
            >
              Resend
            </Button>
            <Button
              type="button"
              variant="danger"
              size="compact"
              onClick={() => void onRevoke(row)}
            >
              Revoke
            </Button>
          </div>
        ) : (
          <span className="text-body-small text-text-subtlest">{row.lastError ?? "—"}</span>
        ),
    },
  ];

  const rows = invites.data?.invites ?? [];

  return (
    <section className="space-y-200">
      <div>
        <h2 className="text-body font-semibold">Invites</h2>
        <p className="mt-025 text-body-small text-text-subtle">
          Send a branded email to a @bigtapp.ai address. They still sign in with Microsoft. A new
          person, or someone you deactivated, gets the starting role from this invite. Operators
          stay on the directory after deactivation — send a new invite instead of deleting them.
        </p>
      </div>
      <form
        className="flex flex-wrap items-end gap-100"
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        <label className="min-w-[16rem] flex-1">
          <span className="mb-050 block text-body-small text-text-subtle">Email</span>
          <Input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="name@bigtapp.ai"
            autoComplete="off"
          />
        </label>
        <label className="w-56">
          <span className="mb-050 block text-body-small text-text-subtle">Starting role</span>
          <SelectField
            value={selectedRole}
            onChange={setRoleId}
            options={roles.map((role) => ({ value: role.id, label: role.name }))}
            placeholder="Choose a role"
            aria-label="Starting role"
          />
        </label>
        <Button type="submit" variant="primary" loading={create.isPending}>
          Send invite
        </Button>
      </form>
      {invites.isError ? (
        <p className="text-body-small text-text-danger">
          {invites.error instanceof Error ? invites.error.message : "Could not load invites"}
        </p>
      ) : !invites.isPending && rows.length === 0 ? (
        <Empty title="No invites yet">
          Send one above. They appear here as pending, accepted, or revoked.
        </Empty>
      ) : (
        <RecordsTable
          rows={rows}
          getRowId={(row) => row.id}
          columns={columns}
          isLoading={invites.isPending}
          isError={invites.isError}
          error={invites.error}
          errorLabel="invites"
          emptyMessage="No invites yet."
          ariaLabel="Invites"
          tableClassName="min-w-full"
        />
      )}
      {confirmDialog}
    </section>
  );
}
