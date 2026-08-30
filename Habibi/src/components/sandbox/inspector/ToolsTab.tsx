import { CheckCircle2, ExternalLink, Loader2, TriangleAlert } from "lucide-react";
import type { LiveToolCall } from "@/components/sandbox/voice/liveEvents";
import { cn } from "@/lib/utils";

function isSafeDeepLink(href: string): boolean {
  return href.startsWith("/") && !href.startsWith("//");
}

/**
 * What the agent actually *did* this call — tool by tool, with a deep-link to
 * every CRM row it created. Native RTVI reports the function calls; the CRM
 * chips come from our `crm.entity` server messages.
 */
export function ToolsTab({ calls }: { calls: LiveToolCall[] }) {
  if (calls.length === 0) {
    return (
      <div className="rounded-medium border border-dashed border-border p-300 text-center text-body-small text-text-subtlest">
        No tool calls yet. Start a live call — CRM writes appear here with links.
      </div>
    );
  }

  // Newest first: during a live call the interesting one is what just happened.
  const ordered = [...calls].reverse();

  return (
    <div className="space-y-100">
      <div className="text-body-small text-text-subtlest">
        {calls.length} tool {calls.length === 1 ? "call" : "calls"} this session
      </div>
      {ordered.map((c) => (
        <div key={c.id} className="rounded-medium border border-border bg-surface-sunken p-150">
          <div className="flex items-center gap-100">
            <StatusIcon status={c.status} />
            <span className="font-mono text-body-small font-medium text-text">{c.name}</span>
            {typeof c.endedAt === "number" && (
              <span className="ml-auto font-mono text-body-small text-text-subtlest">
                {Math.max(0, c.endedAt - c.startedAt)}ms
              </span>
            )}
          </div>

          {c.entity && (
            <div className="mt-075 flex items-center gap-075">
              <span className="rounded bg-surface px-075 py-025 text-body-small font-medium text-text-subtle">
                {c.entity}
              </span>
              {c.entityId && (
                <span className="font-mono text-body-small text-text-subtlest">{c.entityId}</span>
              )}
              {c.deepLink && isSafeDeepLink(c.deepLink) && (
                // Plain anchor, not <Link>: the target path is built server-side
                // from the tool catalog, so it is not a statically-known route.
                <a
                  href={c.deepLink}
                  className="ml-auto inline-flex items-center gap-050 text-body-small text-text-brand hover:underline"
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
    return <Loader2 className="h-3.5 w-3.5 animate-spin text-text-subtlest" />;
  }
  if (status === "error") {
    return <TriangleAlert className="h-3.5 w-3.5 text-text-danger" />;
  }
  return <CheckCircle2 className="h-3.5 w-3.5 text-text-success" />;
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
    <div className="mt-075">
      <div className="text-body-small text-text-subtlest">{label}</div>
      <pre
        className={cn(
          "mt-025 max-h-28 overflow-auto whitespace-pre-wrap break-all rounded",
          "bg-surface p-075 font-mono text-body-small text-text-subtle",
        )}
      >
        {text}
      </pre>
    </div>
  );
}
