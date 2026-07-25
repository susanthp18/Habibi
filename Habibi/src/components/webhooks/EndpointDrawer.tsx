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
  onTestFire?: (ep: Endpoint, event: EventKey) => void;
}) {
  const [tab, setTab] = useState("overview");
  const [revealSecret, setRevealSecret] = useState(false);
  const [testEvent, setTestEvent] = useState<EventKey>("call.completed");
  const [testJson, setTestJson] = useState<string>(
    JSON.stringify(EVENT_INDEX["call.completed"].sample, null, 2),
  );

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
    if (onTestFire) {
      onTestFire(endpoint, testEvent);
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
      <SheetContent side="right" className="flex w-full max-w-[640px] flex-col overflow-hidden p-0 sm:max-w-[640px]">
        <SheetHeader className="shrink-0 border-b border-[var(--border-token)] px-6 py-4">
          <SheetTitle className="flex items-center gap-2 text-[15px] font-semibold text-brand-navy">
            {endpoint.name}
            <Badge variant="outline" className="text-[10px]">{endpoint.target}</Badge>
          </SheetTitle>
          <p className="truncate font-mono text-[11px] text-text-secondary">{endpoint.url}</p>
        </SheetHeader>

        <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
          <TabsList className="mx-6 mt-3 shrink-0 self-start">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="events">Events</TabsTrigger>
            <TabsTrigger value="log">Delivery log</TabsTrigger>
            <TabsTrigger value="signing">Signing</TabsTrigger>
            <TabsTrigger value="test">Test fire</TabsTrigger>
          </TabsList>

          {/* Overview */}
          <TabsContent value="overview" className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-4">
            <div className="grid grid-cols-3 gap-3">
              <SloTile label="Success · 24h" value={`${rate24}%`} tone={rate24 >= 98 ? "ok" : rate24 >= 90 ? "warn" : "bad"} />
              <SloTile label="Success · 7d" value={`${rate7d}%`} tone={rate7d >= 98 ? "ok" : rate7d >= 90 ? "warn" : "bad"} />
              <SloTile label="p95 latency" value={`${p95}ms`} tone={p95 < 500 ? "ok" : p95 < 1500 ? "warn" : "bad"} />
            </div>
            <div>
              <div className="mb-1 text-[12px] font-semibold text-brand-navy">Subscribed events</div>
              <div className="flex flex-wrap gap-1">
                {endpoint.events.map((e) => (
                  <span
                    key={e}
                    className="rounded bg-brand-tint px-1.5 py-0.5 font-mono text-[11px] text-brand-primary-dark"
                  >
                    {e}
                  </span>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-1 text-[12px] font-semibold text-brand-navy">Retry policy</div>
              <div className="text-[12px] text-text-secondary">
                {endpoint.retry.attempts} attempts · {endpoint.retry.backoff} backoff · max age {endpoint.retry.maxAgeHours}h
              </div>
            </div>
            <div className="flex gap-2 pt-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  onUpdate({ ...endpoint, status: endpoint.status === "paused" ? "active" : "paused" })
                }
              >
                {endpoint.status === "paused" ? (
                  <><Play className="mr-1.5 h-3.5 w-3.5" /> Resume</>
                ) : (
                  <><Pause className="mr-1.5 h-3.5 w-3.5" /> Pause</>
                )}
              </Button>
              <Button variant="outline" size="sm" onClick={() => onRotate(endpoint)}>
                <KeyRound className="mr-1.5 h-3.5 w-3.5" /> Rotate secret
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="text-rose-600 hover:text-rose-700"
                onClick={() => onDelete(endpoint)}
              >
                <Trash2 className="mr-1.5 h-3.5 w-3.5" /> Delete
              </Button>
            </div>
          </TabsContent>

          {/* Events */}
          <TabsContent value="events" className="min-h-0 flex-1 space-y-3 overflow-y-auto px-6 py-4">
            {EVENT_CATEGORIES.map((cat) => (
              <div key={cat} className="rounded-md border border-[var(--border-token)] p-3">
                <div className="mb-2 text-[12px] font-semibold text-brand-navy">{cat}</div>
                <div className="grid grid-cols-1 gap-1.5">
                  {EVENT_CATALOG.filter((e) => e.category === cat).map((e) => (
                    <label
                      key={e.key}
                      className="flex items-start gap-2 rounded p-1.5 text-[12px] hover:bg-surface-sunken"
                    >
                      <Checkbox
                        checked={endpoint.events.includes(e.key)}
                        onCheckedChange={() => toggleEvent(e.key)}
                        className="mt-0.5"
                      />
                      <span>
                        <span className="block font-mono text-[11px] text-brand-primary-dark">{e.key}</span>
                        <span className="block text-[10.5px] text-text-secondary">{e.description}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </TabsContent>

          {/* Delivery log */}
          <TabsContent value="log" className="min-h-0 flex-1 space-y-1.5 overflow-y-auto px-6 py-4">
            {epDeliveries.length === 0 ? (
              <div className="grid h-full place-items-center text-[12px] text-text-muted">No deliveries yet.</div>
            ) : (
              epDeliveries.map((d) => (
                <DeliveryRow key={d.id} delivery={d} endpoint={endpoint} onRetry={onRetry} />
              ))
            )}
          </TabsContent>

          {/* Signing */}
          <TabsContent value="signing" className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-4">
            <div>
              <div className="mb-1 text-[12px] font-semibold text-brand-navy">Algorithm</div>
              <Badge variant="outline">{endpoint.algo}</Badge>
            </div>
            <div>
              <div className="mb-1 flex items-center justify-between">
                <span className="text-[12px] font-semibold text-brand-navy">Signing secret</span>
                <div className="flex gap-1">
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
              <code className="block rounded bg-surface-sunken px-2 py-1.5 font-mono text-[12px]">
                {revealSecret ? endpoint.secret : "•".repeat(endpoint.secret.length)}
              </code>
            </div>
            <div>
              <div className="mb-1 text-[12px] font-semibold text-brand-navy">Sample signature header</div>
              <code className="block overflow-x-auto rounded bg-surface-sunken px-2 py-1.5 font-mono text-[11px]">
                {signatureLine}
              </code>
              <p className="mt-1 text-[10.5px] text-text-muted">
                Preview only — production HMAC is computed over the raw request body.
              </p>
            </div>
            <div>
              <div className="mb-1 flex items-center justify-between">
                <span className="text-[12px] font-semibold text-brand-navy">Verify — Node.js</span>
                <Button size="sm" variant="ghost" onClick={() => copy(nodeSnippet, "Snippet")}>
                  <Copy className="h-3.5 w-3.5" />
                </Button>
              </div>
              <pre className="overflow-x-auto rounded bg-slate-950 p-2 font-mono text-[11px] leading-snug text-emerald-300">
{nodeSnippet}
              </pre>
            </div>
            <div>
              <div className="mb-1 flex items-center justify-between">
                <span className="text-[12px] font-semibold text-brand-navy">Verify — Python</span>
                <Button size="sm" variant="ghost" onClick={() => copy(pySnippet, "Snippet")}>
                  <Copy className="h-3.5 w-3.5" />
                </Button>
              </div>
              <pre className="overflow-x-auto rounded bg-slate-950 p-2 font-mono text-[11px] leading-snug text-emerald-300">
{pySnippet}
              </pre>
            </div>
          </TabsContent>

          {/* Test fire */}
          <TabsContent value="test" className="min-h-0 flex-1 space-y-3 overflow-y-auto px-6 py-4">
            <div className="space-y-1.5">
              <span className="text-[12px] font-semibold text-brand-navy">Event</span>
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
            <div className="space-y-1.5">
              <span className="text-[12px] font-semibold text-brand-navy">Payload (JSON)</span>
              <textarea
                value={testJson}
                onChange={(e) => setTestJson(e.target.value)}
                className="h-56 w-full resize-none rounded-md border border-[var(--border-token)] bg-slate-950 p-2 font-mono text-[11px] leading-snug text-emerald-300 focus:outline-none focus:ring-2 focus:ring-brand-primary"
              />
            </div>
            <Button onClick={fireTest} className="w-full">
              <Zap className="mr-1.5 h-3.5 w-3.5" /> Send test delivery
            </Button>
          </TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}

function SloTile({ label, value, tone }: { label: string; value: string; tone: "ok" | "warn" | "bad" }) {
  return (
    <div className="rounded-md border border-[var(--border-token)] p-3">
      <div className="text-[10.5px] font-medium uppercase tracking-wider text-text-muted">{label}</div>
      <div
        className={cn(
          "mt-1 text-[18px] font-semibold",
          tone === "ok" && "text-emerald-600",
          tone === "warn" && "text-amber-600",
          tone === "bad" && "text-rose-600",
        )}
      >
        {value}
      </div>
    </div>
  );
}
