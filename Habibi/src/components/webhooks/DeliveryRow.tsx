import { useState } from "react";
import { ChevronRight } from "lucide-react";
import type { Delivery, Endpoint } from "@/data/webhooks-seed";
import { fmtRel, signaturePreview } from "@/data/webhooks-seed";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function DeliveryRow({
  delivery,
  endpoint,
  showEndpoint = false,
  onRetry,
}: {
  delivery: Delivery;
  endpoint?: Endpoint;
  showEndpoint?: boolean;
  onRetry?: (d: Delivery) => void;
}) {
  const [open, setOpen] = useState(false);
  const bodyStr = JSON.stringify(delivery.payload, null, 2);
  const sig = endpoint ? signaturePreview(endpoint.secret, bodyStr) : "n/a";
  const failed = delivery.status === "server_err" || delivery.status === "client_err";

  return (
    <div className="rounded-md border border-[var(--border-token)] bg-surface-card">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-3 py-2 text-left text-[12px] hover:bg-surface-sunken"
      >
        <ChevronRight
          className={cn("h-3.5 w-3.5 shrink-0 transition-transform", open && "rotate-90")}
        />
        <span className="w-16 shrink-0 text-text-muted">{fmtRel(delivery.at)}</span>
        {showEndpoint && endpoint && (
          <Badge variant="outline" className="shrink-0 text-[10px]">
            {endpoint.name}
          </Badge>
        )}
        <span className="shrink-0 font-mono text-[11px] text-brand-primary-dark">
          {delivery.event}
        </span>
        <span
          className={cn(
            "ml-auto shrink-0 rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold",
            delivery.status === "success" && "bg-emerald-100 text-emerald-700",
            delivery.status === "client_err" && "bg-amber-100 text-amber-700",
            delivery.status === "server_err" && "bg-rose-100 text-rose-700",
            delivery.status === "pending" && "bg-slate-100 text-slate-700",
          )}
        >
          {delivery.httpStatus || "…"}
        </span>
        <span className="w-14 shrink-0 text-right text-[11px] text-text-muted">
          {delivery.latencyMs}ms
        </span>
        <span className="w-10 shrink-0 text-right text-[11px] text-text-muted">
          {delivery.attempt}/{delivery.maxAttempts}
        </span>
      </button>
      {open && (
        <div className="border-t border-[var(--border-token)] p-3 text-[11px]">
          <div className="mb-2 grid grid-cols-2 gap-2">
            <div>
              <div className="text-text-muted">Endpoint URL</div>
              <code className="block truncate rounded bg-surface-sunken px-1.5 py-0.5 font-mono">
                {endpoint?.url ?? "n/a"}
              </code>
            </div>
            <div>
              <div className="text-text-muted">Signature (preview)</div>
              <code className="block truncate rounded bg-surface-sunken px-1.5 py-0.5 font-mono">
                {sig}
              </code>
            </div>
          </div>
          <div className="mb-1 text-text-muted">Request body</div>
          <pre className="mb-3 overflow-x-auto rounded bg-slate-950 p-2 font-mono text-[11px] leading-snug text-emerald-300">
{bodyStr}
          </pre>
          <div className="mb-1 text-text-muted">Response</div>
          <pre className="overflow-x-auto rounded bg-slate-950 p-2 font-mono text-[11px] leading-snug text-slate-200">
{delivery.responseBody ?? "(no body)"}
          </pre>
          {failed && onRetry && (
            <div className="mt-2 flex justify-end">
              <Button size="sm" variant="outline" onClick={() => onRetry(delivery)}>
                Retry
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
