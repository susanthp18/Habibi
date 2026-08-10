import { useMemo, useState } from "react";
import { toast } from "sonner";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Copy, Eye, EyeOff, KeyRound, Pause, Play, Trash2, Zap } from "lucide-react";
import {
  EVENT_CATALOG,
  EVENT_CATEGORIES,
  EVENT_INDEX,
  simulateDelivery,
  signaturePreview,
  successRate,
  within,
  type Delivery,
  type Endpoint,
  type EventKey,
} from "@/data/webhooks-seed";
import { DeliveryRow } from "./DeliveryRow";
import { cn } from "@/lib/utils";

export function EndpointDrawer({
  open,
  onOpenChange,
  endpoint,
  deliveries,
  onUpdate,
  onDelete,
  onAppendDelivery,
  onRotate,
  onRetry,
  onTestFire,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  endpoint: Endpoint | null;
  deliveries: Delivery[];
  onUpdate: (ep: Endpoint) => void;
  onDelete: (ep: Endpoint) => void;
  onAppendDelivery: (d: Delivery) => void;
  onRotate: (ep: Endpoint) => void;
  onRetry: (d: Delivery) => void;
  /** Prefer API test-fire when provided (live mode). */
  onTestFire?: (ep: Endpoint, event: EventKey) => void | Promise<void>;
}) {
  const [tab, setTab] = useState("overview");
  const [revealSecret, setRevealSecret] = useState(false);
  const [testEvent, setTestEvent] = useState<EventKey>("call.completed");
  const [testJson, setTestJson] = useState<string>(
    JSON.stringify(EVENT_INDEX["call.completed"].sample, null, 2),
  );
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

  const toggleEvent = (k: EventKey) => {
    const next = endpoint.events.includes(k)
      ? endpoint.events.filter((x) => x !== k)
      : [...endpoint.events, k];
    onUpdate({ ...endpoint, events: next });
  };

  const copy = (text: string, label: string) => {
    navigator.clipboard?.writeText(text).catch(() => {});
    toast.success(`${label} copied`);
  };

  const fireTest = () => {
    void (async () => {
      if (onTestFire) {
        setTestBusy(true);
        try {
          await onTestFire(endpoint, testEvent);
        } finally {
          setTestBusy(false);
        }
        return;
      }
      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(testJson);
      } catch {
        toast.error("Invalid JSON payload");
        return;
      }
      const d = simulateDelivery(endpoint, testEvent, payload);
      onAppendDelivery(d);
      if (d.status === "success") toast.success(`Test → ${d.httpStatus} in ${d.latencyMs}ms`);
      else toast.error(`Test → ${d.httpStatus} in ${d.latencyMs}ms`);
    })();
  };

  const signatureLine = `X-Coll-Signature: ${signaturePreview(endpoint.secret, "{...}")}`;

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
      <SheetContent side="right" className="flex w-full max-w-[50rem] flex-col overflow-hidden p-0 sm:max-w-[50rem]">
        <SheetHeader className="shrink-0 border-b border-border px-300 py-200">
          <SheetTitle className="flex items-center gap-100 text-[0.875rem] font-semibold text-text">
            {endpoint.name}
            <Badge variant="outline" className="text-body-small">{endpoint.target}</Badge>
          </SheetTitle>
          <p className="truncate font-mono text-body-small text-text-subtle">{endpoint.url}</p>
        </SheetHeader>

        <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
          <TabsList className="mx-300 mt-150 shrink-0 self-start">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="events">Events</TabsTrigger>
            <TabsTrigger value="log">Delivery log</TabsTrigger>
            <TabsTrigger value="signing">Signing</TabsTrigger>
            <TabsTrigger value="test">Test fire</TabsTrigger>
          </TabsList>

          {/* Overview */}
          <TabsContent value="overview" className="min-h-0 flex-1 space-y-200 overflow-y-auto px-300 py-200">
            <div className="grid grid-cols-3 gap-150">
              <SloTile label="Success · 24h" value={`${rate24}%`} tone={rate24 >= 98 ? "ok" : rate24 >= 90 ? "warn" : "bad"} />
              <SloTile label="Success · 7d" value={`${rate7d}%`} tone={rate7d >= 98 ? "ok" : rate7d >= 90 ? "warn" : "bad"} />
              <SloTile label="p95 latency" value={`${p95}ms`} tone={p95 < 500 ? "ok" : p95 < 1500 ? "warn" : "bad"} />
            </div>
            <div>
              <div className="mb-050 text-body-small font-semibold text-text">Subscribed events</div>
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
            </div>
            <div>
              <div className="mb-050 text-body-small font-semibold text-text">Retry policy</div>
              <div className="text-body-small text-text-subtle">
                {endpoint.retry.attempts} attempts · {endpoint.retry.backoff} backoff · max age {endpoint.retry.maxAgeHours}h
              </div>
            </div>
            <div className="flex gap-100 pt-100">
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  onUpdate({ ...endpoint, status: endpoint.status === "paused" ? "active" : "paused" })
                }
              >
                {endpoint.status === "paused" ? (
                  <><Play className="mr-075 h-3.5 w-3.5" /> Resume</>
                ) : (
                  <><Pause className="mr-075 h-3.5 w-3.5" /> Pause</>
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

          {/* Events */}
          <TabsContent value="events" className="min-h-0 flex-1 space-y-150 overflow-y-auto px-300 py-200">
            {EVENT_CATEGORIES.map((cat) => (
              <div key={cat} className="rounded-medium border border-border p-150">
                <div className="mb-100 text-body-small font-semibold text-text">{cat}</div>
                <div className="grid grid-cols-1 gap-075">
                  {EVENT_CATALOG.filter((e) => e.category === cat).map((e) => (
                    <label
                      key={e.key}
                      className="flex items-start gap-100 rounded p-075 text-body-small hover:bg-surface-sunken"
                    >
                      <Checkbox
                        checked={endpoint.events.includes(e.key)}
                        onCheckedChange={() => toggleEvent(e.key)}
                        className="mt-025"
                      />
                      <span>
                        <span className="block font-mono text-body-small text-text-brand">{e.key}</span>
                        <span className="block text-body-small text-text-subtle">{e.description}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </TabsContent>

          {/* Delivery log */}
          <TabsContent value="log" className="min-h-0 flex-1 space-y-075 overflow-y-auto px-300 py-200">
            {epDeliveries.length === 0 ? (
              <div className="grid h-full place-items-center text-body-small text-text-subtlest">No deliveries yet.</div>
            ) : (
              epDeliveries.map((d) => (
                <DeliveryRow key={d.id} delivery={d} endpoint={endpoint} onRetry={onRetry} />
              ))
            )}
          </TabsContent>

          {/* Signing */}
          <TabsContent value="signing" className="min-h-0 flex-1 space-y-200 overflow-y-auto px-300 py-200">
            <div>
              <div className="mb-050 text-body-small font-semibold text-text">Algorithm</div>
              <Badge variant="outline">{endpoint.algo}</Badge>
            </div>
            <div>
              <div className="mb-050 flex items-center justify-between">
                <span className="text-body-small font-semibold text-text">Signing secret</span>
                <div className="flex gap-050">
                  <Button size="sm" variant="ghost" onClick={() => setRevealSecret((v) => !v)}>
                    {revealSecret ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => copy(endpoint.secret, "Secret")}>
                    <Copy className="h-3.5 w-3.5" />
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => onRotate(endpoint)}>
                    <KeyRound className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
              <code className="block rounded bg-surface-sunken px-100 py-075 font-mono text-body-small">
                {revealSecret ? endpoint.secret : "•".repeat(endpoint.secret.length)}
              </code>
            </div>
            <div>
              <div className="mb-050 text-body-small font-semibold text-text">Sample signature header</div>
              <code className="block overflow-x-auto rounded bg-surface-sunken px-100 py-075 font-mono text-body-small">
                {signatureLine}
              </code>
              <p className="mt-050 text-body-small text-text-subtlest">
                Preview only — production HMAC is computed over the raw request body.
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
          <TabsContent value="test" className="min-h-0 flex-1 space-y-150 overflow-y-auto px-300 py-200">
            <div className="space-y-075">
              <span className="text-body-small font-semibold text-text">Event</span>
              <Select
                value={testEvent}
                onValueChange={(v) => {
                  const k = v as EventKey;
                  setTestEvent(k);
                  setTestJson(JSON.stringify(EVENT_INDEX[k].sample, null, 2));
                }}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {endpoint.events.map((e) => (
                    <SelectItem key={e} value={e}>{e}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-075">
              <span className="text-body-small font-semibold text-text">Payload (JSON)</span>
              {/* Read-only on the live path: POST /webhooks/{id}/test builds the
                  payload server-side and takes only the event key, so an
                  editable box here was a decoy — whatever you typed was
                  discarded and the delivery showed a different body. */}
              <textarea
                value={testJson}
                onChange={(e) => setTestJson(e.target.value)}
                readOnly={Boolean(onTestFire)}
                className="h-56 w-full resize-none rounded-large border border-border bg-background-neutral p-100 font-mono text-body-small leading-snug text-text-success focus:outline-none focus:ring-2 focus:ring-border-brand read-only:opacity-70"
              />
              {onTestFire && (
                <p className="text-body-small text-text-subtlest">
                  Sample only — the server builds the live test payload from the
                  selected event.
                </p>
              )}
            </div>
            <Button onClick={fireTest} className="w-full" disabled={testBusy}>
              <Zap className="mr-075 h-3.5 w-3.5" /> {testBusy ? "Sending…" : "Send test delivery"}
            </Button>
          </TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}

function SloTile({ label, value, tone }: { label: string; value: string; tone: "ok" | "warn" | "bad" }) {
  return (
    <div className="rounded-medium border border-border p-150">
      <div className="text-body-small font-medium text-text-subtlest">{label}</div>
      <div
        className={cn(
          "mt-050 text-[1.25rem] font-semibold",
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
