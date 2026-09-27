import type { VersionQuality } from "@/api/voice-studio";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

const pct = (v: number | null) => (v == null ? "—" : `${v}%`);

/**
 * Each released version of an agent on its real calls: the QA cascade's score,
 * critical fails, compliance violations, calls where the agent spoke personal
 * data, containment and the customer's mood. A regression shows next to the
 * version that caused it.
 */
export function VersionQualityTable({ rows }: { rows: VersionQuality[] }) {
  if (rows.length === 0)
    return (
      <p className="text-body-small text-text-subtle">
        No filed calls for this agent in the last 90 days.
      </p>
    );
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Version</TableHead>
          <TableHead>Calls</TableHead>
          <TableHead title="Average QA total over scored calls">QA</TableHead>
          <TableHead title="Calls with a critical criterion scored 0">Critical fails</TableHead>
          <TableHead title="Compliance violations per 100 calls">Violations / 100</TableHead>
          <TableHead title="Calls where the agent itself spoke personal data">
            Agent spoke PII
          </TableHead>
          <TableHead title="Calls finished without a person">Contained</TableHead>
          <TableHead title="Average customer sentiment, -1 to +1">Mood</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.version ?? "draft"}>
            <TableCell className="font-semibold">
              {r.version != null ? `v${r.version}` : "draft"}
            </TableCell>
            <TableCell>
              {r.calls}
              {r.scored < r.calls && (
                <span className="text-text-subtlest"> ({r.scored} scored)</span>
              )}
            </TableCell>
            <TableCell>{r.qaAvg ?? "—"}</TableCell>
            <TableCell className={cn((r.criticalFailPct ?? 0) > 0 && "text-text-danger")}>
              {pct(r.criticalFailPct)}
            </TableCell>
            <TableCell className={cn((r.violationsPer100 ?? 0) > 0 && "text-text-warning")}>
              {r.violationsPer100 ?? "—"}
            </TableCell>
            <TableCell className={cn(r.agentPiiCalls > 0 && "text-text-danger")}>
              {r.agentPiiCalls}
            </TableCell>
            <TableCell>{pct(r.containmentPct)}</TableCell>
            <TableCell>{r.avgSentiment != null ? r.avgSentiment.toFixed(2) : "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
