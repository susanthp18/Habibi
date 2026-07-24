import { CheckCircle2, ExternalLink, Loader2, TriangleAlert, Wrench } from "lucide-react";
import type { LiveToolCall } from "@/components/sandbox/voice/liveEvents";
import { cn } from "@/lib/utils";

/**
 * What the agent actually *did* this call — tool by tool, with a deep-link to
 * every CRM row it created. Native RTVI reports the function calls; the CRM
 * chips come from our `crm.entity` server messages.
 */
export function ToolsTab({ calls }: { calls: LiveToolCall[] }) {
  if (calls.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-[var(--border-token)] p-6 text-center text-[12px] text-text-muted">
        No tool calls yet. Start a live call — CRM writes appear here with links.
      </div>
    );
  }

  // Newest first: during a live call the interesting one is what just happened.
  const ordered = [...calls].reverse();

  return (
    <div className="space-y-2">
      <div className="text-[11px] text-text-muted">
        {calls.length} tool {calls.length === 1 ? "call" : "calls"} this session
      </div>
      {ordered.map((c) => (
        <div
          key={c.id}
          className="rounded-md border border-[var(--border-token)] bg-surface-sunken p-2.5"
        >
          <div className="flex items-center gap-2">
            <StatusIcon status={c.status} />
            <span className="font-mono text-[12px] font-medium text-text-primary">{c.name}</span>
            {typeof c.endedAt === "number" && (
              <span className="ml-auto font-mono text-[10.5px] text-text-muted">
                {Math.max(0, c.endedAt - c.startedAt)}ms
              </span>
            )}
          </div>

          {c.entity && (
            <div className="mt-1.5 flex items-center gap-1.5">
              <span className="rounded bg-surface-card px-1.5 py-0.5 text-[10.5px] font-medium text-text-secondary">
                {c.entity}
              </span>
              {c.entityId && (
                <span className="font-mono text-[10.5px] text-text-muted">{c.entityId}</span>
              )}
              {c.deepLink && (
                // Plain anchor, not <Link>: the target path is built server-side
                // from the tool catalog, so it is not a statically-known route.
                <a
                  href={c.deepLink}
                  className="ml-auto inline-flex items-center gap-1 text-[11px] text-brand-primary-dark hover:underline"
                >
                  Open <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>
          )}

          {c.args !== undefined && <Payload label="args" value={c.args} />}
          {c.result !== undefined && <Payload label="result" value={c.result} />}
        </div>
      ))}
    </div>
  );
}

function StatusIcon({ status }: { status: LiveToolCall["status"] }) {
  if (status === "running") {
    return <Loader2 className="h-3.5 w-3.5 animate-spin text-text-muted" />;
  }
  if (status === "error") {
    return <TriangleAlert className="h-3.5 w-3.5 text-status-danger" />;
  }
  return <CheckCircle2 className="h-3.5 w-3.5 text-status-success" />;
}

function Payload({ label, value }: { label: string; value: unknown }) {
  let text: string;
  try {
    text = typeof value === "string" ? value : JSON.stringify(value, null, 1);
  } catch {
    text = String(value);
  }
  if (!text || text === "{}" || text === "null") return null;
  return (
    <div className="mt-1.5">
      <div className="text-[10px] uppercase tracking-wide text-text-muted">{label}</div>
      <pre
        className={cn(
          "mt-0.5 max-h-28 overflow-auto whitespace-pre-wrap break-all rounded",
          "bg-surface-card p-1.5 font-mono text-[10.5px] text-text-secondary",
        )}
      >
        {text}
      </pre>
    </div>
  );
}

export { Wrench as ToolsTabIcon };
