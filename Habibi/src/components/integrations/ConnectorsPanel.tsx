/** The MCP connectors this tenant attaches: register, health-check, revoke. */
import { useState } from "react";
import { toast } from "sonner";
import {
  useConnectorMutations,
  useConnectors,
  useVaultRefs,
  type Connector,
} from "@/api/integrations";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Lozenge } from "@/components/ui/lozenge";
import { SelectField } from "@/components/ui/select";
import { Chip } from "@/components/ui/chip";
import { FilterGroup } from "@/components/records/FiltersBar";
import { toggleIn } from "@/lib/utils";
import STUDIO_VOCABULARY from "@/lib/studio-vocabulary.json";
import { connectorHealthToast } from "@/lib/studio-trust";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";

export function ConnectorsPanel() {
  const { data: rows = [], isLoading, isError, error } = useConnectors();
  const mut = useConnectorMutations();
  const [slug, setSlug] = useState("");
  const [url, setUrl] = useState("");
  const [authRef, setAuthRef] = useState("");
  const [issuer, setIssuer] = useState("");
  const [cimdConnectorId, setCimdConnectorId] = useState("");
  const [dataClass, setDataClass] = useState<string[]>(["pii"]);
  const vault = useVaultRefs();

  const columns: RecordsColumn<Connector>[] = [
    {
      id: "name",
      header: "Connector",
      sticky: true,
      cell: (r) => (
        <div>
          <div className="font-medium">{r.displayName}</div>
          <div className="font-mono text-body-tiny text-text-subtle">{r.slug}</div>
        </div>
      ),
    },
    {
      id: "kind",
      header: "Kind",
      cell: (r) => (
        <span className="text-text-subtle">
          {r.kind === "first_party" ? "first-party" : "remote MCP"}
        </span>
      ),
    },
    {
      id: "status",
      header: "Status",
      cell: (r) => (
        <Lozenge
          tone={
            r.status === "approved" ? "success" : r.status === "disabled" ? "danger" : "warning"
          }
        >
          {r.status}
        </Lozenge>
      ),
    },
    {
      id: "health",
      header: "Health",
      cell: (r) => <span className="text-text-subtle">{r.health}</span>,
    },
    {
      id: "data",
      header: "Data class",
      cell: (r) => (
        <span className="font-mono text-body-tiny">{(r.dataClass ?? []).join(", ") || "—"}</span>
      ),
    },
    {
      id: "cache",
      header: "tools/list",
      cell: (r) => (
        <span className="text-body-tiny text-text-subtle">
          {r.lastToolsListAt ? new Date(r.lastToolsListAt).toLocaleString() : "never"}
        </span>
      ),
    },
    {
      id: "actions",
      header: "",
      cell: (r) => (
        <div className="flex flex-wrap gap-050">
          {r.status !== "approved" ? (
            <Button size="sm" variant="outline" onClick={() => mut.approve.mutate(r.id)}>
              Approve
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              void mut.test
                .mutateAsync(r.id)
                .then((result) => {
                  const kind = connectorHealthToast(result as { ok?: boolean });
                  if (kind === "ok") toast.success("Health test passed");
                  else if (kind === "fail") toast.error("Health test failed");
                  else toast.error("Health test returned no result");
                })
                .catch((e: Error) => toast.error(e.message || "Health test failed"))
            }
          >
            Test
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        Bind approved servers on the card. Remote URLs must be HTTPS. Auth is a vault ref — never a
        token in this form. Idle mouth excludes <span className="font-mono">ext.*</span> so G6 does
        not blow the 12-tool cap.
      </p>
      <div className="grid gap-100 md:grid-cols-5">
        <Input placeholder="slug" value={slug} onChange={(e) => setSlug(e.target.value)} />
        <Input
          placeholder="https://bank.example/mcp"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <SelectField
          aria-label="Vault ref"
          placeholder="Vault ref (optional)"
          size="compact"
          value={authRef}
          onChange={setAuthRef}
          options={(vault.data ?? []).map((ref) => ({ value: ref.id, label: ref.name }))}
        />
        <FilterGroup label="Data">
          {STUDIO_VOCABULARY.connectorDataClasses.map((dc) => (
            <Chip
              key={dc}
              active={dataClass.includes(dc)}
              onClick={() => setDataClass(toggleIn(dataClass, dc))}
            >
              {dc}
            </Chip>
          ))}
        </FilterGroup>
        <Button
          size="sm"
          disabled={dataClass.length === 0}
          onClick={() => {
            if (!slug.trim()) return;
            void mut.upsert
              .mutateAsync({
                slug: slug.trim(),
                url: url.trim() || undefined,
                kind: url.trim() ? "remote_mcp" : "first_party",
                authRef: authRef || undefined,
                dataClass,
              })
              .then(() => toast.success("Connector saved"));
          }}
        >
          Add connector
        </Button>
      </div>
      <RecordsTable
        rows={rows}
        getRowId={(r) => r.id}
        columns={columns}
        isLoading={isLoading}
        isError={isError}
        error={error}
        errorLabel="connectors"
        emptyMessage="No connectors. Seed creates pay-link and LMS."
        ariaLabel="MCP connectors"
        tableClassName="min-w-full"
      />
      <div className="flex flex-wrap items-end gap-100 rounded-medium border border-border p-150">
        <div className="min-w-[16rem] flex-1">
          <div className="text-body-tiny text-text-subtle">
            CIMD issuer (HTTPS). No DCR. Client secret stays in vault.
          </div>
          <Input
            placeholder="https://idp.bank.example"
            value={issuer}
            onChange={(e) => setIssuer(e.target.value)}
          />
        </div>
        <SelectField
          aria-label="Connector"
          placeholder="Select connector…"
          size="compact"
          value={cimdConnectorId}
          onChange={setCimdConnectorId}
          options={rows.map((r) => ({ value: r.id, label: r.displayName || r.slug }))}
        />
        <Button
          size="sm"
          variant="outline"
          disabled={!cimdConnectorId || !issuer.trim()}
          onClick={() =>
            void mut.cimd
              .mutateAsync({ id: cimdConnectorId, issuer: issuer.trim() })
              .then((r: unknown) => {
                const clientId =
                  r && typeof r === "object" && "clientId" in r
                    ? String((r as { clientId: unknown }).clientId)
                    : "recorded";
                toast.success(`CIMD client ${clientId}`);
              })
              .catch((err: unknown) =>
                toast.error(err instanceof Error ? err.message : "Connect failed"),
              )
          }
        >
          Connect IdP
        </Button>
      </div>
    </div>
  );
}
