import { useState } from "react";
import { toast } from "sonner";
import { USE_MOCK } from "@/api/config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Lozenge } from "@/components/ui/lozenge";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";
import {
  useConnectorMutations,
  useConnectors,
  useGatewayStatus,
  useGatewayCanary,
  useProposeGatewayCanary,
  usePromoteGatewayCanary,
  useMcpKeyMutations,
  useMcpKeys,
  useMcpStatus,
  useMcpTasks,
  useVaultMutations,
  useVaultRefs,
  useA2aPartners,
  useA2aTasks,
  useUpsertA2aPartner,
  type Connector,
  type McpKey,
  type McpTask,
  type VaultRef,
  type A2aPartner,
  type A2aTask,
} from "@/api/integrations";

const SCOPES = ["crm.read", "kb.search", "offers.read", "policy.read", "tasks.write"] as const;

export function ConnectorsPanel() {
  const { data: rows = [], isLoading } = useConnectors();
  const mut = useConnectorMutations();
  const [slug, setSlug] = useState("");
  const [url, setUrl] = useState("");
  const [authRef, setAuthRef] = useState("");
  const [issuer, setIssuer] = useState("");
  const vault = useVaultRefs();

  const columns: RecordsColumn<Connector>[] = [
    {
      id: "name",
      header: "Connector",
      sticky: true,
      cell: (r) => (
        <div>
          <div className="font-medium">{r.displayName}</div>
          <div className="font-mono text-caption text-text-subtle">{r.slug}</div>
        </div>
      ),
    },
    {
      id: "kind",
      header: "Kind",
      cell: (r) => <span className="text-text-subtle">{r.kind === "first_party" ? "first-party" : "remote MCP"}</span>,
    },
    {
      id: "status",
      header: "Status",
      cell: (r) => (
        <Lozenge tone={r.status === "approved" ? "success" : r.status === "disabled" ? "danger" : "warning"}>
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
      cell: (r) => <span className="font-mono text-caption">{(r.dataClass ?? []).join(", ") || "—"}</span>,
    },
    {
      id: "cache",
      header: "tools/list",
      cell: (r) => (
        <span className="text-caption text-text-subtle">
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
          <Button size="sm" variant="outline" onClick={() => void mut.test.mutateAsync(r.id).then(() => toast.success("Health test ran"))}>
            Test
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        Bind approved servers on the card. Remote URLs must be HTTPS. Auth is a vault ref — never a token in this
        form. Idle mouth excludes <span className="font-mono">ext.*</span> so G6 does not blow the 12-tool cap.
      </p>
      <div className="grid gap-100 md:grid-cols-4">
        <Input placeholder="slug" value={slug} onChange={(e) => setSlug(e.target.value)} />
        <Input placeholder="https://bank.example/mcp" value={url} onChange={(e) => setUrl(e.target.value)} />
        <select
          className="h-400 rounded-medium border border-border bg-surface px-100 text-body-small"
          value={authRef}
          onChange={(e) => setAuthRef(e.target.value)}
        >
          <option value="">Vault ref (optional)</option>
          {(vault.data ?? []).map((ref) => (
            <option key={ref.id} value={ref.id}>
              {ref.name}
            </option>
          ))}
        </select>
        <Button
          size="sm"
          onClick={() => {
            if (!slug.trim()) return;
            void mut.upsert
              .mutateAsync({
                slug: slug.trim(),
                url: url.trim() || undefined,
                kind: url.trim() ? "remote_mcp" : "first_party",
                authRef: authRef || undefined,
                dataClass: ["pii"],
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
        emptyMessage="No connectors. Seed creates pay-link and LMS."
        ariaLabel="MCP connectors"
        tableClassName="min-w-full"
      />
      <div className="flex flex-wrap items-end gap-100 rounded-medium border border-border p-150">
        <div className="min-w-[16rem] flex-1">
          <div className="text-caption text-text-subtle">CIMD issuer (HTTPS). No DCR. Client secret stays in vault.</div>
          <Input placeholder="https://idp.bank.example" value={issuer} onChange={(e) => setIssuer(e.target.value)} />
        </div>
        <Button
          size="sm"
          variant="outline"
          disabled={!rows[0] || !issuer.trim()}
          onClick={() =>
            void mut.cimd
              .mutateAsync({ id: rows[0].id, issuer: issuer.trim() })
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

export function OurMcpPanel() {
  const status = useMcpStatus();
  const keys = useMcpKeys();
  const keyMut = useMcpKeyMutations();
  const tasks = useMcpTasks();
  const [name, setName] = useState("cursor-read");
  const [scopes, setScopes] = useState<string[]>(["crm.read"]);
  const [once, setOnce] = useState<string | null>(null);
  const s = status.data;

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success("Copied");
    } catch {
      /* ignore */
    }
  };

  const keyCols: RecordsColumn<McpKey>[] = [
    { id: "name", header: "Key", cell: (r) => <span className="font-medium">{r.name}</span> },
    { id: "prefix", header: "Prefix", cell: (r) => <span className="font-mono text-caption">{r.prefix}…</span> },
    { id: "scopes", header: "Scopes", cell: (r) => <span className="font-mono text-caption">{r.scopes.join(" ")}</span> },
    {
      id: "state",
      header: "State",
      cell: (r) => <Lozenge tone={r.revoked ? "danger" : "success"}>{r.revoked ? "revoked" : "active"}</Lozenge>,
    },
    {
      id: "act",
      header: "",
      cell: (r) =>
        r.revoked ? null : (
          <div className="flex gap-050">
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                void keyMut.rotate.mutateAsync(r.id).then((row) => {
                  const shown = (row as McpKey).key;
                  if (shown) setOnce(shown);
                })
              }
            >
              Rotate
            </Button>
            <Button size="sm" variant="outline" onClick={() => keyMut.revoke.mutate(r.id)}>
              Revoke
            </Button>
          </div>
        ),
    },
  ];

  const taskCols: RecordsColumn<McpTask>[] = [
    { id: "id", header: "Task", cell: (r) => <span className="font-mono text-caption">{r.id}</span> },
    { id: "kind", header: "Kind", cell: (r) => r.kind },
    { id: "status", header: "Status", cell: (r) => r.status },
    { id: "when", header: "Created", cell: (r) => <span className="text-caption text-text-subtle">{r.createdAt ?? "—"}</span> },
  ];

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        Separate process — never mounted on FastAPI. Bootstrap <span className="font-mono">MCP_API_KEY</span> is
        read-only. Mutators return 403. MCP Apps ({s?.appsEnabled ? "on" : "flag off"}) serve handoff-prep and PTP confirm over ui://.
      </p>
      <div className="grid gap-100 md:grid-cols-2">
        <div className="rounded-medium border border-border p-150">
          <div className="text-caption text-text-subtle">stdio</div>
          <div className="mt-050 flex items-center gap-100">
            <code className="text-body-small">{s?.stdioCommand}</code>
            <Button size="sm" variant="outline" onClick={() => void copy(s?.stdioCommand ?? "")}>
              Copy
            </Button>
          </div>
        </div>
        <div className="rounded-medium border border-border p-150">
          <div className="text-caption text-text-subtle">HTTP {s?.httpEnabled ? "on" : "flag off"}</div>
          <div className="mt-050 flex items-center gap-100">
            <code className="text-body-small">{s?.httpUrl}</code>
            <Button size="sm" variant="outline" onClick={() => void copy(s?.httpUrl ?? "")}>
              Copy
            </Button>
          </div>
          <div className="mt-050 text-caption text-text-subtle">mTLS {s?.mtls ? "required" : "unset"}</div>
        </div>
      </div>
      <div>
        <div className="mb-075 text-body font-medium">Resources</div>
        <ul className="font-mono text-caption text-text-subtle">
          {(s?.resources ?? []).map((uri) => (
            <li key={uri}>{uri}</li>
          ))}
        </ul>
      </div>
      {once ? (
        <div className="rounded-medium border border-border-warning bg-background-warning-subtler px-150 py-100 text-body-small">
          Shown once — copy now. <code className="break-all">{once}</code>
          <Button size="sm" className="ml-100" variant="outline" onClick={() => void copy(once)}>
            Copy
          </Button>
        </div>
      ) : null}
      <div className="flex flex-wrap items-end gap-100">
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="key name" />
        <div className="flex flex-wrap gap-075">
          {SCOPES.map((scope) => (
            <label key={scope} className="flex items-center gap-050 text-caption">
              <input
                type="checkbox"
                checked={scopes.includes(scope)}
                onChange={() =>
                  setScopes((prev) => (prev.includes(scope) ? prev.filter((x) => x !== scope) : [...prev, scope]))
                }
              />
              {scope}
            </label>
          ))}
        </div>
        <Button
          size="sm"
          onClick={() =>
            void keyMut.mint.mutateAsync({ name, scopes }).then((row) => {
              if (row.key) setOnce(row.key);
              toast.success("Key minted — copy it now");
            })
          }
        >
          Mint key
        </Button>
      </div>
      <RecordsTable
        rows={keys.data ?? []}
        getRowId={(r) => r.id}
        columns={keyCols}
        emptyMessage="No minted keys. Use MCP_API_KEY for bootstrap (read scopes only)."
        ariaLabel="MCP keys"
        tableClassName="min-w-full"
      />
      <div className="text-body font-medium">Tasks</div>
      <RecordsTable
        rows={tasks.data ?? []}
        getRowId={(r) => r.id}
        columns={taskCols}
        emptyMessage="No MCP tasks. Statement generate returns an id without blocking the call."
        ariaLabel="MCP tasks"
        tableClassName="min-w-full"
      />
    </div>
  );
}

export function VaultPanel() {
  const refs = useVaultRefs();
  const mut = useVaultMutations();
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("connector_oauth");
  const [secret, setSecret] = useState("");
  const [rotateId, setRotateId] = useState<string | null>(null);
  const [rotateSecret, setRotateSecret] = useState("");

  const cols: RecordsColumn<VaultRef>[] = [
    { id: "name", header: "Name", sticky: true, cell: (r) => <span className="font-medium">{r.name}</span> },
    { id: "purpose", header: "Purpose", cell: (r) => r.purpose },
    { id: "backend", header: "Backend", cell: (r) => r.backend },
    {
      id: "rotated",
      header: "Last rotated",
      cell: (r) => <span className="text-caption text-text-subtle">{r.lastRotatedAt ?? "—"}</span>,
    },
    {
      id: "used",
      header: "Last used",
      cell: (r) => <span className="text-caption text-text-subtle">{r.lastUsedAt ?? "—"}</span>,
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
        Secrets never come back on JSON. No <span className="font-mono">vault://</span> placeholders. Rotation does
        not require a deploy. Ops lock still applies to provider env keys.
      </p>
      <div className="grid gap-100 md:grid-cols-4">
        <Input placeholder="name" value={name} onChange={(e) => setName(e.target.value)} />
        <select
          className="h-400 rounded-medium border border-border bg-surface px-100 text-body-small"
          value={purpose}
          onChange={(e) => setPurpose(e.target.value)}
        >
          {["connector_oauth", "mcp_key", "webhook", "llm", "twilio", "whatsapp", "other"].map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
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
        emptyMessage="No vault refs yet."
        ariaLabel="Vault refs"
        tableClassName="min-w-full"
      />
    </div>
  );
}

export function GatewayPanel() {
  const { data } = useGatewayStatus();
  const canaryQuery = useGatewayCanary();
  const propose = useProposeGatewayCanary();
  const promote = usePromoteGatewayCanary();
  const [candidate, setCandidate] = useState("");
  const profiles = data?.profiles ?? {};
  const canary = canaryQuery.data?.current ?? data?.canary ?? null;
  const copy = canary?.copyToEnv ?? [];
  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        All four profiles go through the gateway client when the flag is on.{" "}
        <span className="font-mono">azure_openai</span> is the kill-switch. Canary a new Azure
        deployment to <span className="font-mono">analysis</span> first, then text, then voice. Red-team
        is never skipped. Copy-to-env is a human step.
      </p>
      <div className="rounded-medium border border-border p-150 text-body-small">
        <div>Enabled: {data?.enabled ? "yes" : "no"}</div>
        <div>Base URL: {data?.baseUrl || "unset"}</div>
        <div>Kill-switch: {data?.killSwitch || "gateway"}</div>
        <div>Voice SLO: {data?.voiceSloMs ?? 800} ms</div>
      </div>
      <ul className="divide-y divide-border rounded-medium border border-border">
        {Object.entries(profiles).map(([name, row]) => (
          <li key={name} className="flex items-center justify-between px-150 py-100">
            <div>
              <div className="font-medium">{name}</div>
              <div className="font-mono text-caption text-text-subtle">{row.model || "default model"}</div>
              {row.canaryModel ? (
                <div className="text-caption text-text-subtle">canary {row.canaryModel}</div>
              ) : null}
            </div>
            <div className="text-caption text-text-subtle">cap ₹{row.capInr || 0}</div>
          </li>
        ))}
      </ul>
      <div className="rounded-medium border border-border p-150">
        <div className="mb-100 text-body-small font-semibold text-text">Model canary</div>
        {canary ? (
          <div className="mb-100 space-y-050 text-body-small">
            <div className="flex flex-wrap items-center gap-075">
              <span className="font-mono">{canary.candidateModel}</span>
              <Lozenge tone={canary.status === "promoted" ? "success" : canary.status === "fail" ? "danger" : "neutral"}>
                {canary.stage} · {canary.status}
              </Lozenge>
              {canary.injectionClosed ? <Lozenge tone="success">injection closed</Lozenge> : null}
            </div>
            {canary.status === "pass" && canary.stage !== "voice" ? (
              <Button
                size="sm"
                disabled={promote.isPending}
                onClick={() => void promote.mutateAsync(canary.id)}
              >
                {promote.isPending ? "Promoting…" : `Promote to ${canary.stage === "analysis" ? "text" : "voice"}`}
              </Button>
            ) : null}
            {copy.length > 0 ? (
              <ul className="font-mono text-caption text-text-subtle">
                {copy.map((c) => (
                  <li key={c.name}>
                    {c.name}={c.value}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : (
          <p className="mb-100 text-caption text-text-subtlest">No open canary.</p>
        )}
        <div className="flex flex-wrap items-end gap-100">
          <Input
            value={candidate}
            onChange={(e) => setCandidate(e.target.value)}
            placeholder="azure/gpt-deployment"
          />
          <Button
            size="sm"
            disabled={!candidate || propose.isPending || USE_MOCK}
            onClick={() => void propose.mutateAsync(candidate)}
          >
            {propose.isPending ? "Starting…" : "Start at analysis"}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function A2aPartnersPanel() {
  const partners = useA2aPartners();
  const tasks = useA2aTasks();
  const upsert = useUpsertA2aPartner();
  const [name, setName] = useState("");
  const [certDn, setCertDn] = useState("");

  const cols: RecordsColumn<A2aPartner>[] = [
    { id: "name", header: "Partner", cell: (r) => <span className="font-medium">{r.name}</span> },
    { id: "dn", header: "Client cert DN", cell: (r) => <span className="font-mono text-caption">{r.certDn || r.certFingerprint}</span> },
    { id: "skills", header: "Skills", cell: (r) => <span className="text-caption">{(r.allowedSkills ?? []).join(", ") || "all"}</span> },
    {
      id: "status",
      header: "Status",
      cell: (r) => <Lozenge tone={r.status === "active" ? "success" : "neutral"}>{r.status}</Lozenge>,
    },
  ];
  const taskCols: RecordsColumn<A2aTask>[] = [
    { id: "id", header: "Task", cell: (r) => <span className="font-mono text-caption">{r.id}</span> },
    { id: "skill", header: "Skill", cell: (r) => r.skillId ?? "—" },
    { id: "status", header: "Status", cell: (r) => r.status },
    { id: "cert", header: "Cert DN", cell: (r) => <span className="font-mono text-caption">{r.certDn ?? "—"}</span> },
  ];

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        A2A partners authenticate with mTLS. A bearer token without a client certificate is rejected. Never on the audio path.
      </p>
      <div className="flex flex-wrap items-end gap-100">
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Partner name" />
        <Input value={certDn} onChange={(e) => setCertDn(e.target.value)} placeholder="CN=partner.example" />
        <Button
          size="sm"
          disabled={!name || !certDn || upsert.isPending}
          onClick={() =>
            void upsert
              .mutateAsync({ name, certDn })
              .then(() => {
                toast.success("Partner registered");
                setName("");
                setCertDn("");
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
        emptyMessage="No A2A partners"
      />
      <div className="text-body font-medium">Recent A2A tasks</div>
      <RecordsTable
        rows={tasks.data ?? []}
        columns={taskCols}
        getRowId={(r) => r.id}
        isLoading={tasks.isLoading}
        emptyMessage="No A2A tasks"
      />
    </div>
  );
}
