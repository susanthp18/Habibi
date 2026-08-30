import { useState } from "react";
import { ChevronRight } from "lucide-react";
import type { Delivery, Endpoint } from "@/data/webhooks-seed";
import { fmtRel, signaturePreview } from "@/data/webhooks-seed";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Lozenge } from "@/components/ui/lozenge";
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
    <div className="rounded-medium border border-border bg-surface">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-150 px-150 py-100 text-left text-body-small hover:bg-surface-sunken"
      >
        <ChevronRight
          className={cn("h-3.5 w-3.5 shrink-0 transition-transform", open && "rotate-90")}
        />
        <span className="w-800 shrink-0 text-text-subtlest">{fmtRel(delivery.at)}</span>
        {showEndpoint && endpoint && (
          <Badge variant="outline" className="shrink-0 text-body-small">
            {endpoint.name}
          </Badge>
        )}
        <span className="shrink-0 font-mono text-body-small text-text-brand">{delivery.event}</span>
        {delivery.mode === "simulated" && (
          // A test fire does no egress. Left unlabelled it is indistinguishable
          // from a delivery that actually reached the endpoint, which is how
          // this log spent its whole life reporting sends that never happened.
          <Lozenge tone="warning" className="shrink-0">
            Simulated
          </Lozenge>
        )}
        <span
          className={cn(
            "ml-auto shrink-0 rounded px-075 py-025 font-mono text-body-small font-semibold",
            delivery.status === "success" &&
              "bg-background-success-subtler text-text-success-bolder",
            delivery.status === "client_err" &&
              "bg-background-warning-subtler text-text-warning-bolder",
            delivery.status === "server_err" &&
              "bg-background-danger-subtler text-text-danger-bolder",
            delivery.status === "pending" &&
              "bg-background-accent-gray-subtler text-text-accent-gray-bolder",
          )}
        >
          {delivery.httpStatus || "…"}
        </span>
        <span className="w-14 shrink-0 text-right text-body-small text-text-subtlest">
          {delivery.latencyMs}ms
        </span>
        <span className="w-500 shrink-0 text-right text-body-small text-text-subtlest">
          {delivery.attempt}/{delivery.maxAttempts}
        </span>
      </button>
      {open && (
        <div className="border-t border-border p-150 text-body-small">
          <div className="mb-100 grid grid-cols-2 gap-100">
            <div>
              <div className="text-text-subtlest">Endpoint URL</div>
              <code className="block truncate rounded bg-surface-sunken px-075 py-025 font-mono">
                {endpoint?.url ?? "n/a"}
              </code>
            </div>
            <div>
              <div className="text-text-subtlest">Signature (preview)</div>
              <code className="block truncate rounded bg-surface-sunken px-075 py-025 font-mono">
                {sig}
              </code>
            </div>
          </div>
          <div className="mb-050 text-text-subtlest">Request body</div>
          <pre className="mb-150 overflow-x-auto rounded-large bg-background-neutral p-100 font-mono text-body-small leading-snug text-text-code-default">
            {bodyStr}
          </pre>
          <div className="mb-050 text-text-subtlest">Response</div>
          <pre className="overflow-x-auto rounded-large bg-background-neutral p-100 font-mono text-body-small leading-snug text-text-code-default">
            {delivery.responseBody ?? "(no body)"}
          </pre>
          {failed && onRetry && (
            <div className="mt-100 flex justify-end">
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
