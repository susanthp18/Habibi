/** The MCP server this tenant exposes: its keys and the tasks callers left. */
import { useState } from "react";
import { toast } from "sonner";
import {
  useMcpKeyMutations,
  useMcpKeys,
  useMcpStatus,
  useMcpTasks,
  type McpKey,
  type McpTask,
} from "@/api/integrations";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Lozenge } from "@/components/ui/lozenge";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";

const SCOPES = ["crm.read", "kb.search", "offers.read", "policy.read", "tasks.write"] as const;

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
    {
      id: "prefix",
      header: "Prefix",
      cell: (r) => <span className="font-mono text-body-tiny">{r.prefix}…</span>,
    },
    {
      id: "scopes",
      header: "Scopes",
      cell: (r) => <span className="font-mono text-body-tiny">{r.scopes.join(" ")}</span>,
    },
    {
      id: "state",
      header: "State",
      cell: (r) => (
        <Lozenge tone={r.revoked ? "danger" : "success"}>
          {r.revoked ? "revoked" : "active"}
        </Lozenge>
      ),
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
                  if (row.key) setOnce(row.key);
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
    {
      id: "id",
      header: "Task",
      cell: (r) => <span className="font-mono text-body-tiny">{r.id}</span>,
    },
    { id: "kind", header: "Kind", cell: (r) => r.kind },
    { id: "status", header: "Status", cell: (r) => r.status },
    {
      id: "when",
      header: "Created",
      cell: (r) => <span className="text-body-tiny text-text-subtle">{r.createdAt ?? "—"}</span>,
    },
  ];

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        Separate process — never mounted on FastAPI. Bootstrap{" "}
        <span className="font-mono">MCP_API_KEY</span> is read-only. Mutators return 403. MCP Apps (
        {s?.appsEnabled ? "on" : "flag off"}) serve handoff-prep and PTP confirm over ui://.
      </p>
      <div className="grid gap-100 md:grid-cols-2">
        <div className="rounded-medium border border-border p-150">
          <div className="text-body-tiny text-text-subtle">stdio</div>
          <div className="mt-050 flex items-center gap-100">
            <code className="text-body-small">{s?.stdioCommand}</code>
            <Button size="sm" variant="outline" onClick={() => void copy(s?.stdioCommand ?? "")}>
              Copy
            </Button>
          </div>
        </div>
        <div className="rounded-medium border border-border p-150">
          <div className="text-body-tiny text-text-subtle">
            HTTP {s?.httpEnabled ? "on" : "flag off"}
          </div>
          <div className="mt-050 flex items-center gap-100">
            <code className="text-body-small">{s?.httpUrl}</code>
            <Button size="sm" variant="outline" onClick={() => void copy(s?.httpUrl ?? "")}>
              Copy
            </Button>
          </div>
          <div className="mt-050 text-body-tiny text-text-subtle">
            mTLS {s?.mtls ? "required" : "unset"}
          </div>
        </div>
      </div>
      <div>
        <div className="mb-075 text-body font-medium">Resources</div>
        <ul className="font-mono text-body-tiny text-text-subtle">
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
            <label key={scope} className="flex items-center gap-050 text-body-tiny">
              <input
                type="checkbox"
                checked={scopes.includes(scope)}
                onChange={() =>
                  setScopes((prev) =>
                    prev.includes(scope) ? prev.filter((x) => x !== scope) : [...prev, scope],
                  )
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
        isLoading={keys.isLoading}
        isError={keys.isError}
        error={keys.error}
        errorLabel="MCP keys"
        emptyMessage="No minted keys. Use MCP_API_KEY for bootstrap (read scopes only)."
        ariaLabel="MCP keys"
        tableClassName="min-w-full"
      />
      <div className="text-body font-medium">Tasks</div>
      <RecordsTable
        rows={tasks.data ?? []}
        getRowId={(r) => r.id}
        columns={taskCols}
        isLoading={tasks.isLoading}
        isError={tasks.isError}
        error={tasks.error}
        errorLabel="MCP tasks"
        emptyMessage="No MCP tasks. Statement generate returns an id without blocking the call."
        ariaLabel="MCP tasks"
        tableClassName="min-w-full"
      />
    </div>
  );
}
