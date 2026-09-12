/** The secret references the connectors and channels resolve at call time. */
import { useState } from "react";
import { toast } from "sonner";
import { useVaultMutations, useVaultRefs, type VaultRef } from "@/api/integrations";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";

const VAULT_PURPOSES = [
  "connector_oauth",
  "mcp_key",
  "webhook",
  "llm",
  "twilio",
  "whatsapp",
  "other",
].map((p) => ({ value: p, label: p }));

export function VaultPanel() {
  const refs = useVaultRefs();
  const mut = useVaultMutations();
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("connector_oauth");
  const [secret, setSecret] = useState("");
  const [rotateId, setRotateId] = useState<string | null>(null);
  const [rotateSecret, setRotateSecret] = useState("");

  const cols: RecordsColumn<VaultRef>[] = [
    {
      id: "name",
      header: "Name",
      sticky: true,
      cell: (r) => <span className="font-medium">{r.name}</span>,
    },
    { id: "purpose", header: "Purpose", cell: (r) => r.purpose },
    { id: "backend", header: "Backend", cell: (r) => r.backend },
    {
      id: "rotated",
      header: "Last rotated",
      cell: (r) => (
        <span className="text-body-tiny text-text-subtle">{r.lastRotatedAt ?? "—"}</span>
      ),
    },
    {
      id: "used",
      header: "Last used",
      cell: (r) => <span className="text-body-tiny text-text-subtle">{r.lastUsedAt ?? "—"}</span>,
    },
    {
      id: "act",
      header: "",
      cell: (r) => (
        <Button size="sm" variant="outline" onClick={() => setRotateId(r.id)}>
          Rotate
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        Secrets never come back on JSON. No <span className="font-mono">vault://</span>{" "}
        placeholders. Rotation does not require a deploy. Ops lock still applies to provider env
        keys.
      </p>
      <div className="grid gap-100 md:grid-cols-4">
        <Input placeholder="name" value={name} onChange={(e) => setName(e.target.value)} />
        <SelectField
          aria-label="Purpose"
          size="compact"
          value={purpose}
          onChange={setPurpose}
          options={VAULT_PURPOSES}
        />
        <Input
          type="password"
          placeholder="secret (write-only)"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          autoComplete="off"
        />
        <Button
          size="sm"
          onClick={() => {
            void mut.put.mutateAsync({ name, purpose, secret }).then(() => {
              setSecret("");
              toast.success("Stored — secret is not shown again");
            });
          }}
        >
          Put secret
        </Button>
      </div>
      {rotateId ? (
        <div className="flex flex-wrap items-end gap-100 rounded-medium border border-border p-150">
          <Input
            type="password"
            placeholder="new secret"
            value={rotateSecret}
            onChange={(e) => setRotateSecret(e.target.value)}
            autoComplete="off"
          />
          <Button
            size="sm"
            onClick={() =>
              void mut.rotate.mutateAsync({ id: rotateId, secret: rotateSecret }).then(() => {
                setRotateId(null);
                setRotateSecret("");
                toast.success("Rotated");
              })
            }
          >
            Confirm rotate
          </Button>
        </div>
      ) : null}
      <RecordsTable
        rows={refs.data ?? []}
        getRowId={(r) => r.id}
        columns={cols}
        isLoading={refs.isLoading}
        isError={refs.isError}
        error={refs.error}
        errorLabel="vault refs"
        emptyMessage="No vault refs yet."
        ariaLabel="Vault refs"
        tableClassName="min-w-full"
      />
    </div>
  );
}
