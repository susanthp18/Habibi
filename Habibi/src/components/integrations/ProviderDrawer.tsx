import { useMemo, useState } from "react";
import { X, ExternalLink, Copy, Check, PlayCircle, CheckCircle2, XCircle } from "lucide-react";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  healthTone,
  pipecatSnippet,
  runMockHealthCheck,
  usageSeries,
  type Env,
  type Provider,
  type TestLogEntry,
} from "@/data/integrations-seed";
import { MaskedInput } from "./MaskedInput";
import { toast } from "sonner";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { cn } from "@/lib/utils";

type Props = {
  provider: Provider | null;
  env: Env;
  logs: TestLogEntry[];
  onClose: () => void;
  onUpdate: (p: Provider) => void;
  onAppendLog: (e: TestLogEntry) => void;
  /** Live mode: run API health check instead of mock. */
  onTestLive?: (p: Provider) => void;
};

export function ProviderDrawer({ provider, env, logs, onClose, onUpdate, onAppendLog, onTestLive }: Props) {
  const [copiedSnippet, setCopiedSnippet] = useState(false);
  const [testing, setTesting] = useState(false);

  if (!provider) return null;
  const cfg = provider.perEnv[env];
  const locked = Boolean(cfg.credentialsLocked);
  const t = healthTone(cfg.health);

  const usage = usageSeries(provider.id, env).map((v, i) => ({ day: `D${i + 1}`, value: v }));
  const providerLogs = logs.filter(l => l.providerId === provider.id).slice().reverse();

  const setField = (key: string, val: string) => {
    onUpdate({
      ...provider,
      perEnv: { ...provider.perEnv, [env]: { ...cfg, values: { ...cfg.values, [key]: val } } },
    });
  };

  const rotate = (key: string) => {
    if (locked) {
      toast.message("Rotate secrets via ops vault / env — not from this UI.");
      return;
    }
    const fresh = `rot-${Math.random().toString(36).slice(2, 10)}-${Date.now().toString(36).slice(-6)}`;
    setField(key, fresh);
    toast.success("Key rotated — restart Pipecat worker to pick it up.");
  };

  const runTest = async () => {
    setTesting(true);
    try {
      if (onTestLive) {
        onTestLive(provider);
      } else {
        const entry = await runMockHealthCheck(provider, env);
        onAppendLog(entry);
        entry.ok
          ? toast.success(`${provider.name} · ${entry.latencyMs} ms`)
          : toast.error(`${provider.name} · ${entry.message}`);
      }
    } finally {
      setTesting(false);
    }
  };

  const snippet = useMemo(() => pipecatSnippet(provider, env), [provider, env]);
  const copySnippet = async () => {
    try { await navigator.clipboard.writeText(snippet); setCopiedSnippet(true); setTimeout(() => setCopiedSnippet(false), 1400); } catch { /* ignore */ }
  };

  return (
    <Sheet open={!!provider} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-hidden p-0 sm:max-w-[560px]">
        <div className="flex h-full flex-col">
          <div className="flex shrink-0 items-start gap-3 border-b border-[var(--border-token)] bg-surface-card p-4">
            <div className={cn("grid h-10 w-10 place-items-center rounded-md font-semibold", provider.brandColor)}>{provider.brandInitial}</div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <div className="text-[14px] font-semibold text-brand-navy">{provider.name}</div>
                <span className="rounded-full border border-[var(--border-token)] bg-white px-1.5 py-0.5 text-[10px] font-medium capitalize text-text-secondary">{env}</span>
              </div>
              <div className="text-[12px] text-text-secondary">{provider.capability} · {provider.vendor}</div>
              <div className="mt-1 flex items-center gap-1 text-[11px]">
                <span className={cn("h-1.5 w-1.5 rounded-full", t.dot)} />
                <span className={cn("font-medium", t.text)}>{t.label}</span>
                {cfg.latencyMs > 0 && <span className="text-text-muted">· {cfg.latencyMs} ms</span>}
                <span className="ml-2 text-text-muted">{cfg.region}</span>
              </div>
            </div>
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}><X className="h-4 w-4" /></Button>
          </div>

          <Tabs defaultValue="overview" className="flex min-h-0 flex-1 flex-col">
            <TabsList className="h-10 w-full shrink-0 justify-start rounded-none border-b border-[var(--border-token)] bg-surface-card p-0">
              {["overview", "credentials", "usage", "test", "pipecat"].map(v => (
                <TabsTrigger key={v} value={v} className="rounded-none border-b-2 border-transparent px-3 text-[12px] capitalize data-[state=active]:border-brand-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                  {v === "pipecat" ? "Pipecat wiring" : v}
                </TabsTrigger>
              ))}
            </TabsList>

            <TabsContent value="overview" className="mt-0 min-h-0 flex-1 overflow-y-auto p-4">
              <p className="text-[13px] leading-relaxed text-text-primary">{provider.description}</p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {provider.capabilities.map(c => (
                  <span key={c} className="rounded-full border border-[var(--border-token)] bg-brand-tint/60 px-2 py-0.5 text-[11px] font-medium text-brand-primary-dark">{c}</span>
                ))}
              </div>
              <a href={provider.docsUrl} target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-1.5 text-[12px] font-medium text-brand-primary hover:underline">
                Provider documentation <ExternalLink className="h-3 w-3" />
              </a>
            </TabsContent>

            <TabsContent value="credentials" className="mt-0 min-h-0 flex-1 overflow-y-auto p-4">
              {locked ? (
                <div className="mb-3 rounded-md border border-sky-200 bg-sky-50 p-2 text-[11px] text-sky-900">
                  Credentials are managed via process environment / ops vault. This screen shows
                  configuration status only — plaintext keys are never stored in the CRM DB or JS bundle.
                </div>
              ) : env === "production" ? (
                <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 p-2 text-[11px] text-amber-800">
                  Rotating keys here will restart the Pipecat worker.
                </div>
              ) : null}
              <div className="space-y-3">
                {provider.fields.map(f => (
                  <div key={f.key}>
                    <Label className="text-[11px] font-medium uppercase tracking-wide text-text-muted">{f.label}</Label>
                    {f.secret ? (
                      <MaskedInput
                        value={cfg.values[f.key] ?? ""}
                        onChange={(v) => !locked && setField(f.key, v)}
                        onRotate={locked ? undefined : () => rotate(f.key)}
                        placeholder={locked ? "•••••••• (env/vault)" : f.placeholder}
                      />
                    ) : (
                      <Input
                        className="h-8 font-mono text-[11px]"
                        value={cfg.values[f.key] ?? ""}
                        placeholder={f.placeholder}
                        readOnly={locked}
                        onChange={(e) => !locked && setField(f.key, e.target.value)}
                      />
                    )}
                  </div>
                ))}
              </div>
              <div className="mt-4 text-[10px] text-text-muted">
                {locked
                  ? "Set AZURE_*/TWILIO_*/WHATSAPP_* in backend/.env (or your secret manager)."
                  : "Demo values are placeholders only — never commit real secrets."}
              </div>
            </TabsContent>

            <TabsContent value="usage" className="mt-0 min-h-0 flex-1 overflow-y-auto p-4">
              <div className="grid grid-cols-3 gap-2">
                {cfg.usageStats.map(s => (
                  <div key={s.label} className="rounded-md border border-[var(--border-token)] bg-surface-card p-2">
                    <div className="text-[10px] uppercase tracking-wider text-text-muted">{s.label}</div>
                    <div className="text-[14px] font-semibold text-brand-navy">{s.value}</div>
                  </div>
                ))}
              </div>
              <div className="mt-3 rounded-md border border-[var(--border-token)] bg-surface-card p-2">
                <div className="mb-1 flex items-center justify-between">
                  <div className="text-[11px] font-semibold text-brand-navy">14-day {cfg.unitLabel} volume</div>
                  <div className="text-[11px] text-text-muted">Cost: {cfg.costMonth}</div>
                </div>
                <div className="h-32">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={usage} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                      <defs>
                        <linearGradient id={`grad-${provider.id}`} x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="var(--brand-primary)" stopOpacity={0.4} />
                          <stop offset="100%" stopColor="var(--brand-primary)" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="day" tick={{ fontSize: 9 }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 9 }} axisLine={false} tickLine={false} width={30} />
                      <Tooltip cursor={{ stroke: "rgba(0,0,0,0.1)" }} contentStyle={{ fontSize: 11, borderRadius: 6 }} />
                      <Area type="monotone" dataKey="value" stroke="var(--brand-primary)" strokeWidth={1.5} fill={`url(#grad-${provider.id})`} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </TabsContent>

            <TabsContent value="test" className="mt-0 flex min-h-0 flex-1 flex-col">
              <div className="border-b border-[var(--border-token)] bg-surface-card px-4 py-2">
                <Button size="sm" className="w-full gap-1.5 bg-brand-primary hover:bg-brand-primary-dark" onClick={runTest} disabled={testing}>
                  <PlayCircle className="h-3.5 w-3.5" /> {testing ? "Testing…" : "Run test connection"}
                </Button>
              </div>
              <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-4">
                {providerLogs.length === 0 && (
                  <div className="rounded-md border border-dashed border-[var(--border-token)] p-6 text-center text-[11px] text-text-muted">No tests yet. Run one to see request/response.</div>
                )}
                {providerLogs.map(l => (
                  <div key={l.id} className={cn("rounded-md border p-2", l.ok ? "border-emerald-200 bg-emerald-50/60" : "border-red-200 bg-red-50/60")}>
                    <div className="flex items-center gap-2 text-[12px]">
                      {l.ok ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : <XCircle className="h-3.5 w-3.5 text-red-600" />}
                      <span className="flex-1 font-medium text-brand-navy">{l.message}</span>
                      <span className="font-mono text-[10px] text-text-muted">{l.latencyMs} ms</span>
                    </div>
                    <div className="mt-1 text-[10px] text-text-muted">{new Date(l.at).toLocaleTimeString()} · {l.env}</div>
                    {l.payload && (
                      <pre className="mt-1 max-h-32 overflow-auto rounded bg-white p-2 font-mono text-[10px] text-text-primary">{l.payload}</pre>
                    )}
                  </div>
                ))}
              </div>
            </TabsContent>

            <TabsContent value="pipecat" className="mt-0 min-h-0 flex-1 overflow-y-auto p-4">
              <div className="mb-2 flex items-center justify-between">
                <div className="text-[12px] font-semibold text-brand-navy">Pipecat wiring</div>
                <Button variant="outline" size="sm" className="h-7 gap-1 text-[11px]" onClick={copySnippet}>
                  {copiedSnippet ? <Check className="h-3 w-3 text-emerald-600" /> : <Copy className="h-3 w-3" />} Copy
                </Button>
              </div>
              <pre className="rounded-md border border-[var(--border-token)] bg-brand-navy/95 p-3 font-mono text-[11px] leading-relaxed text-white/90">{snippet}</pre>
              <p className="mt-2 text-[11px] text-text-muted">This is the exact stage the Pipecat worker instantiates for {provider.name}. Values reference environment variables the deploy pipeline injects from this connector's stored credentials.</p>
            </TabsContent>
          </Tabs>
        </div>
      </SheetContent>
    </Sheet>
  );
}
