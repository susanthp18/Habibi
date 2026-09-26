import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { useReleases, useStudioAgents } from "@/api/voice-studio";
import { QueryState } from "@/components/ui/query-state";
import { SelectField } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const ALL = "all";

/**
 * Every publish and rollback of every Voice Studio agent: what went live, what
 * it replaced, who released it and why. Rolling back happens in the agent's
 * version history, next to the diff of what would change.
 */
export default function ReleasesPage() {
  const [agent, setAgent] = useState<string>(ALL);
  const agents = useStudioAgents();
  const releases = useReleases(agent === ALL ? null : Number(agent), 200);
  const names = new Map((agents.data ?? []).map((a) => [a.id, a.name]));
  const rows = releases.data ?? [];

  return (
    <div className="mx-auto max-w-[72rem] space-y-300 p-300">
      <header className="space-y-050">
        <h1 className="heading-medium font-semibold">Releases</h1>
        <p className="text-body-small text-text-subtle">
          Every agent version that went live, and why. To roll back, open the agent and choose an
          earlier version in its version history.
        </p>
      </header>
      <SelectField
        aria-label="Agent"
        value={agent}
        onChange={setAgent}
        className="w-[20rem]"
        options={[
          { value: ALL, label: "All agents" },
          ...(agents.data ?? []).map((a) => ({ value: String(a.id), label: a.name })),
        ]}
      />
      <QueryState
        query={releases}
        label="releases"
        empty={
          rows.length === 0 ? (
            <p className="text-body-small text-text-subtle">No releases yet.</p>
          ) : null
        }
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>When</TableHead>
              <TableHead>Agent</TableHead>
              <TableHead>Version</TableHead>
              <TableHead>What changed</TableHead>
              <TableHead>By</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="whitespace-nowrap">
                  {new Date(r.createdAt).toLocaleString()}
                </TableCell>
                <TableCell>
                  <Link
                    to="/studio/workflow/$workflowId"
                    params={{ workflowId: String(r.workflowId) }}
                    className="underline"
                  >
                    {names.get(r.workflowId) ?? `Agent ${r.workflowId}`}
                  </Link>
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  {r.fromVersion ? `v${r.fromVersion} → ` : ""}v{r.version ?? "?"}
                  {r.action === "rollback" && (
                    <span className="ml-100 text-text-warning">rollback</span>
                  )}
                </TableCell>
                <TableCell>{r.note}</TableCell>
                <TableCell>{r.actor ?? "unknown"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </QueryState>
    </div>
  );
}
