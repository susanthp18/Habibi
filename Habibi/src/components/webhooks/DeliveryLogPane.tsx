import { useMemo, useState } from "react";
import type { Delivery, DeliveryStatus, Endpoint, EventKey } from "@/data/webhooks-seed";
import { EVENT_CATALOG } from "@/data/webhooks-seed";
import { DeliveryRow } from "./DeliveryRow";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export function DeliveryLogPane({
  endpoints,
  deliveries,
  onRetry,
}: {
  endpoints: Endpoint[];
  deliveries: Delivery[];
  onRetry: (d: Delivery) => void;
}) {
  const [epId, setEpId] = useState<string>("all");
  const [event, setEvent] = useState<string>("all");
  const [status, setStatus] = useState<string>("all");
  const [window, setWindow] = useState<string>("24");

  const epIndex = useMemo(() => new Map(endpoints.map((e) => [e.id, e])), [endpoints]);

  const filtered = useMemo(() => {
    const cutoff = Date.now() - +window * 3_600_000;
    return deliveries
      .filter((d) => d.at >= cutoff)
      .filter((d) => (epId === "all" ? true : d.endpointId === epId))
      .filter((d) => (event === "all" ? true : d.event === event))
      .filter((d) => (status === "all" ? true : d.status === (status as DeliveryStatus)));
  }, [deliveries, epId, event, status, window]);

  return (
    <div className="flex min-h-0 flex-col border-t border-border bg-surface">
      <div className="flex shrink-0 items-center gap-100 border-b border-border px-200 py-100">
        <span className="text-body-small font-semibold text-text">Global delivery log</span>
        <span className="text-body-small text-text-subtlest">{filtered.length} events</span>
        <div className="ml-auto flex items-center gap-100">
          <Select value={epId} onValueChange={setEpId}>
            <SelectTrigger className="h-400 w-[11.25rem] text-body-small">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All endpoints</SelectItem>
              {endpoints.map((e) => (
                <SelectItem key={e.id} value={e.id}>
                  {e.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={event} onValueChange={setEvent}>
            <SelectTrigger className="h-400 w-[11.25rem] text-body-small">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All events</SelectItem>
              {EVENT_CATALOG.map((e) => (
                <SelectItem key={e.key} value={e.key as EventKey}>
                  {e.key}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="h-400 w-[8.75rem] text-body-small">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="success">Success</SelectItem>
              <SelectItem value="client_err">Client error</SelectItem>
              <SelectItem value="server_err">Server error</SelectItem>
              <SelectItem value="pending">Pending</SelectItem>
            </SelectContent>
          </Select>
          <Select value={window} onValueChange={setWindow}>
            <SelectTrigger className="h-400 w-[7.5rem] text-body-small">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1">Last hour</SelectItem>
              <SelectItem value="24">Last 24h</SelectItem>
              <SelectItem value="168">Last 7d</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-075 overflow-y-auto p-150">
        {filtered.length === 0 && (
          <div className="grid h-full place-items-center text-body-small text-text-subtlest">
            No deliveries match these filters.
          </div>
        )}
        {filtered.map((d) => (
          <DeliveryRow
            key={d.id}
            delivery={d}
            endpoint={epIndex.get(d.endpointId)}
            showEndpoint
            onRetry={onRetry}
          />
        ))}
      </div>
    </div>
  );
}
