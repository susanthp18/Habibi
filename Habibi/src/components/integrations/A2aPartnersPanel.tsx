/** Agent-to-agent partners: certificates, bots, and the tasks exchanged. */
import { useState } from "react";
import { toast } from "sonner";
import {
  useA2aPartners,
  useA2aTasks,
  useUpsertA2aPartner,
  type A2aPartner,
  type A2aTask,
} from "@/api/integrations";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Lozenge } from "@/components/ui/lozenge";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";

export function A2aPartnersPanel() {
  const partners = useA2aPartners();
  const tasks = useA2aTasks();
  const upsert = useUpsertA2aPartner();
  const [name, setName] = useState("");
  const [botId, setBotId] = useState("");
  const [certDn, setCertDn] = useState("");
  const [certPem, setCertPem] = useState("");

  const cols: RecordsColumn<A2aPartner>[] = [
    { id: "name", header: "Partner", cell: (r) => <span className="font-medium">{r.name}</span> },
    {
      id: "bot",
      header: "Bot",
      cell: (r) => <span className="font-mono text-body-tiny">{r.botId || "unscoped"}</span>,
    },
    {
      id: "dn",
      header: "Client cert DN",
      cell: (r) => (
        <span className="font-mono text-body-tiny">{r.certDn || r.certFingerprint}</span>
      ),
    },
    {
      id: "skills",
      header: "Skills",
      cell: (r) => (
        <span className="text-body-tiny">{(r.allowedSkills ?? []).join(", ") || "all"}</span>
      ),
    },
    {
      id: "status",
      header: "Status",
      cell: (r) => (
        <Lozenge tone={r.status === "active" ? "success" : "neutral"}>{r.status}</Lozenge>
      ),
    },
  ];
  const taskCols: RecordsColumn<A2aTask>[] = [
    {
      id: "id",
      header: "Task",
      cell: (r) => <span className="font-mono text-body-tiny">{r.id}</span>,
    },
    { id: "skill", header: "Skill", cell: (r) => r.skillId ?? "—" },
    { id: "status", header: "Status", cell: (r) => r.status },
    {
      id: "cert",
      header: "Cert DN",
      cell: (r) => <span className="font-mono text-body-tiny">{r.certDn ?? "—"}</span>,
    },
  ];

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        A2A partners authenticate with a verified mTLS certificate bound to one tenant and bot. A
        bearer token or a typed DN alone is rejected. Never on the audio path.
      </p>
      <div className="flex flex-wrap items-end gap-100">
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Partner name" />
        <Input value={botId} onChange={(e) => setBotId(e.target.value)} placeholder="Bot id" />
        <Input
          value={certDn}
          onChange={(e) => setCertDn(e.target.value)}
          placeholder="CN=partner.example"
        />
        <Textarea
          value={certPem}
          onChange={(e) => setCertPem(e.target.value)}
          placeholder="-----BEGIN CERTIFICATE-----"
          className="min-h-24 min-w-80 font-mono text-body-tiny"
        />
        <Button
          size="sm"
          disabled={!name || !botId || !certDn || !certPem || upsert.isPending}
          onClick={() =>
            void upsert
              .mutateAsync({ name, botId, certDn, certPem })
              .then(() => {
                toast.success("Partner registered");
                setName("");
                setBotId("");
                setCertDn("");
                setCertPem("");
              })
              .catch((err: Error) => toast.error(err.message))
          }
        >
          Add partner
        </Button>
      </div>
      <RecordsTable
        rows={partners.data ?? []}
        columns={cols}
        getRowId={(r) => r.id}
        isLoading={partners.isLoading}
        isError={partners.isError}
        error={partners.error}
        errorLabel="A2A partners"
        emptyMessage="No A2A partners"
      />
      <div className="text-body font-medium">Recent A2A tasks</div>
      <RecordsTable
        rows={tasks.data ?? []}
        columns={taskCols}
        getRowId={(r) => r.id}
        isLoading={tasks.isLoading}
        isError={tasks.isError}
        error={tasks.error}
        errorLabel="A2A tasks"
        emptyMessage="No A2A tasks"
      />
    </div>
  );
}
