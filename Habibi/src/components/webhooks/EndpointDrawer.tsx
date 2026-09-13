import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Copy, KeyRound, Pause, Play, Trash2, Zap } from "lucide-react";
import type { Delivery, Endpoint, EventKey } from "@/api/types/webhooks";
import { SIGNATURE_HEADER_EXAMPLE, successRate, within } from "@/lib/webhooks";
import { DeliveryRow } from "./DeliveryRow";
import { cn } from "@/lib/utils";

export function EndpointDrawer({
  open,
  onOpenChange,
  endpoint,
  deliveries,
  onUpdate,
  onDelete,
  onRotate,
  onRetry,
  onTestFire,
  onEdit,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  endpoint: Endpoint | null;
  deliveries: Delivery[];
  onUpdate: (ep: Endpoint) => void;
  onDelete: (ep: Endpoint) => void;
  onRotate: (ep: Endpoint) => void;
  onRetry: (d: Delivery) => void;
  onTestFire: (ep: Endpoint, event: EventKey) => void | Promise<void>;
  /** Open the endpoint form -- the drawer inspects, the sheet edits. */
  onEdit: (ep: Endpoint) => void;
}) {
  const [tab, setTab] = useState("overview");
  const [testEvent, setTestEvent] = useState<EventKey>("call.completed");
  const [testBusy, setTestBusy] = useState(false);

  const epDeliveries = useMemo(
    () => (endpoint ? deliveries.filter((d) => d.endpointId === endpoint.id) : []),
    [deliveries, endpoint],
  );
  const rate24 = successRate(within(epDeliveries, 24));
  const rate7d = successRate(within(epDeliveries, 168));
  const p95 = useMemo(() => {
    if (!epDeliveries.length) return 0;
    const sorted = [...epDeliveries].map((d) => d.latencyMs).sort((a, b) => a - b);
    return sorted[Math.floor(sorted.length * 0.95)] ?? sorted[sorted.length - 1];
  }, [epDeliveries]);

  if (!endpoint) return null;

  const copy = (text: string, label: string) => {
    navigator.clipboard?.writeText(text).catch(() => {});
    toast.success(`${label} copied`);
  };

  const fireTest = () => {
    void (async () => {
      setTestBusy(true);
      try {
        await onTestFire(endpoint, testEvent);
      } finally {
        setTestBusy(false);
      }
    })();
  };

  const nodeSnippet = `import crypto from "node:crypto";

function verify(rawBody, header, secret) {
  const [, tPart, sigPart] = header.match(/t=(\\d+), v1=([a-f0-9]+)/);
  const expected = crypto
    .createHmac("sha256", secret)
    .update(\`\${tPart}.\${rawBody}\`)
    .digest("hex");
  return crypto.timingSafeEqual(Buffer.from(sigPart), Buffer.from(expected));
}`;

  const pySnippet = `import hmac, hashlib, re

def verify(raw_body: bytes, header: str, secret: str) -> bool:
    m = re.match(r"t=(\\d+), v1=([a-f0-9]+)", header)
    t, sig = m.group(1), m.group(2)
    expected = hmac.new(secret.encode(), f"{t}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)`;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full max-w-[50rem] flex-col overflow-hidden p-0 sm:max-w-[50rem]"
      >
        <SheetHeader className="shrink-0 border-b border-border px-300 py-200">
          <SheetTitle className="flex items-center gap-100 text-body font-semibold text-text">
            {endpoint.name}
            <Badge variant="outline" className="text-body-small">
              {endpoint.target}
            </Badge>
          </SheetTitle>
          <p className="truncate font-mono text-body-small text-text-subtle">{endpoint.url}</p>
        </SheetHeader>

        <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
          <TabsList className="mx-300 mt-150 shrink-0 self-start">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="log">Delivery log</TabsTrigger>
            <TabsTrigger value="signing">Signing</TabsTrigger>
            <TabsTrigger value="test">Test fire</TabsTrigger>
          </TabsList>

          {/* Overview */}
          <TabsContent
            value="overview"
            className="min-h-0 flex-1 space-y-200 overflow-y-auto px-300 py-200"
          >
            <div className="grid grid-cols-3 gap-150">
              <SloTile
                label="Success · 24h"
                value={`${rate24}%`}
                tone={rate24 >= 98 ? "ok" : rate24 >= 90 ? "warn" : "bad"}
              />
              <SloTile
                label="Success · 7d"
                value={`${rate7d}%`}
                tone={rate7d >= 98 ? "ok" : rate7d >= 90 ? "warn" : "bad"}
              />
              <SloTile
                label="p95 latency"
                value={`${p95}ms`}
                tone={p95 < 500 ? "ok" : p95 < 1500 ? "warn" : "bad"}
              />
            </div>
            <div>
              <div className="mb-050 text-body-small font-semibold text-text">
                Subscribed events
              </div>
              <div className="flex flex-wrap gap-050">
                {endpoint.events.map((e) => (
                  <span
                    key={e}
                    className="rounded bg-background-brand-subtlest px-075 py-025 font-mono text-body-small text-text-brand"
                  >
                    {e}
                  </span>
                ))}
              </div>
              {/* Subscriptions are edited in the one form that validates them. */}
              <Button
                variant="link"
                size="sm"
                className="mt-050 px-0"
                onClick={() => onEdit(endpoint)}
              >
                Edit endpoint
              </Button>
            </div>
            <div>
              <div className="mb-050 text-body-small font-semibold text-text">Retry policy</div>
              <div className="text-body-small text-text-subtle">
                {endpoint.retry.attempts} attempts · {endpoint.retry.backoff} backoff · max age{" "}
                {endpoint.retry.maxAgeHours}h
              </div>
            </div>
            <div className="flex gap-100 pt-100">
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  onUpdate({
                    ...endpoint,
                    status: endpoint.status === "paused" ? "active" : "paused",
                  })
                }
              >
                {endpoint.status === "paused" ? (
                  <>
                    <Play className="mr-075 h-3.5 w-3.5" /> Resume
                  </>
                ) : (
                  <>
                    <Pause className="mr-075 h-3.5 w-3.5" /> Pause
                  </>
                )}
              </Button>
              <Button variant="outline" size="sm" onClick={() => onRotate(endpoint)}>
                <KeyRound className="mr-075 h-3.5 w-3.5" /> Rotate secret
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="text-text-danger hover:text-text-danger-bolder"
                onClick={() => onDelete(endpoint)}
              >
                <Trash2 className="mr-075 h-3.5 w-3.5" /> Delete
              </Button>
            </div>
          </TabsContent>

          {/* Delivery log */}
          <TabsContent
            value="log"
            className="min-h-0 flex-1 space-y-075 overflow-y-auto px-300 py-200"
          >
            {epDeliveries.length === 0 ? (
              <div className="grid h-full place-items-center text-body-small text-text-subtlest">
                No deliveries yet.
              </div>
            ) : (
              epDeliveries.map((d) => (
                <DeliveryRow key={d.id} delivery={d} endpoint={endpoint} onRetry={onRetry} />
              ))
            )}
          </TabsContent>

          {/* Signing */}
          <TabsContent
            value="signing"
            className="min-h-0 flex-1 space-y-200 overflow-y-auto px-300 py-200"
          >
            <div>
              <div className="mb-050 text-body-small font-semibold text-text">Algorithm</div>
              <Badge variant="outline">{endpoint.algo}</Badge>
            </div>
            <div>
              <div className="mb-050 flex items-center justify-between">
                <span className="text-body-small font-semibold text-text">Signing secret</span>
                <Button size="sm" variant="ghost" onClick={() => onRotate(endpoint)}>
                  <KeyRound className="h-3.5 w-3.5" />
                </Button>
              </div>
              <code className="block rounded bg-surface-sunken px-100 py-075 font-mono text-body-small">
                {endpoint.secretRef}
              </code>
              <p className="mt-050 text-body-small text-text-subtlest">
                Shown once, at create and rotate. Rotate to issue a new one.
              </p>
            </div>
            <div>
              <div className="mb-050 text-body-small font-semibold text-text">
                Sample signature header
              </div>
              <code className="block overflow-x-auto rounded bg-surface-sunken px-100 py-075 font-mono text-body-small">
                {SIGNATURE_HEADER_EXAMPLE}
              </code>
              <p className="mt-050 text-body-small text-text-subtlest">
                The HMAC is computed over the raw request body.
              </p>
            </div>
            <div>
              <div className="mb-050 flex items-center justify-between">
                <span className="text-body-small font-semibold text-text">Verify — Node.js</span>
                <Button size="sm" variant="ghost" onClick={() => copy(nodeSnippet, "Snippet")}>
                  <Copy className="h-3.5 w-3.5" />
                </Button>
              </div>
              <pre className="overflow-x-auto rounded-large bg-background-neutral p-100 font-mono text-body-small leading-snug text-text-code-default">
                {nodeSnippet}
              </pre>
            </div>
            <div>
              <div className="mb-050 flex items-center justify-between">
                <span className="text-body-small font-semibold text-text">Verify — Python</span>
                <Button size="sm" variant="ghost" onClick={() => copy(pySnippet, "Snippet")}>
                  <Copy className="h-3.5 w-3.5" />
                </Button>
              </div>
              <pre className="overflow-x-auto rounded-large bg-background-neutral p-100 font-mono text-body-small leading-snug text-text-code-default">
                {pySnippet}
              </pre>
            </div>
          </TabsContent>

          {/* Test fire */}
          <TabsContent
            value="test"
            className="min-h-0 flex-1 space-y-150 overflow-y-auto px-300 py-200"
          >
            <div className="space-y-075">
              <span className="text-body-small font-semibold text-text">Event</span>
              <Select
                value={testEvent}
                onValueChange={(v) => {
                  const k = v as EventKey;
                  setTestEvent(k);
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {endpoint.events.map((e) => (
                    <SelectItem key={e} value={e}>
                      {e}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <p className="text-body-small text-text-subtlest">
              The server builds the payload for the selected event and records the delivery as
              simulated.
            </p>
            <Button onClick={fireTest} className="w-full" disabled={testBusy}>
              <Zap className="mr-075 h-3.5 w-3.5" /> {testBusy ? "Sending…" : "Send test delivery"}
            </Button>
          </TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}

function SloTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "ok" | "warn" | "bad";
}) {
  return (
    <div className="rounded-medium border border-border p-150">
      <div className="text-body-small font-medium text-text-subtlest">{label}</div>
      <div
        className={cn(
          "mt-050 heading-medium font-semibold",
          tone === "ok" && "text-text-code-default",
          tone === "warn" && "text-text-warning",
          tone === "bad" && "text-text-danger",
        )}
      >
        {value}
      </div>
    </div>
  );
}
