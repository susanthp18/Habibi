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
import { Lozenge } from "@/components/ui/lozenge";
import { MaskedInput } from "./MaskedInput";
import { toast } from "sonner";
import { ChartStage, LivelineTrend, SnapshotPill } from "@/components/charts";
import { cn } from "@/lib/utils";

type Props = {
  provider: Provider | null;
  env: Env;
  logs: TestLogEntry[];
  onClose: () => void;
  onUpdate: (p: Provider) => void;
  onAppendLog: (e: TestLogEntry) => void;
  /** Live mode: run API health check instead of mock. */
  onTestLive?: (p: Provider) => void | Promise<void>;
};

export function ProviderDrawer({ provider, env, logs, onClose, onUpdate, onAppendLog, onTestLive }: Props) {
  const [copiedSnippet, setCopiedSnippet] = useState(false);
  const [testing, setTesting] = useState(false);

  const snippet = useMemo(
    () => (provider ? pipecatSnippet(provider, env) : ""),
    [provider, env],
  );

  if (!provider) return null;
  const cfg = provider.perEnv[env];
  const locked = Boolean(cfg.credentialsLocked);
  const t = healthTone(cfg.health);

  const usageValues = usageSeries(provider.id, env);
  const usageLabels = usageValues.map((_, i) => `D${i + 1}`);
  const providerLogs = logs.filter(l => l.providerId === provider.id).slice().reverse();

  const setField = (key: string, val: string) => {
    // Enforced here, not only at the call sites: credentials for a locked
    // provider come from the ops vault / env, and a new caller that forgot the
    // `!locked &&` guard would silently write over them.
    if (locked) return;
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
        await onTestLive(provider);
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

  const copySnippet = async () => {
    try { await navigator.clipboard.writeText(snippet); setCopiedSnippet(true); setTimeout(() => setCopiedSnippet(false), 1400); } catch { /* ignore */ }
  };

  return (
    <Sheet open={!!provider} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-hidden p-0 sm:max-w-[37.5rem]">
        <div className="flex h-full flex-col">
          <div className="flex shrink-0 items-start gap-150 border-b border-border bg-surface p-200">
            <div className={cn("grid h-500 w-500 place-items-center rounded-medium font-semibold", provider.brandColor)}>{provider.brandInitial}</div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-100">
                <div className="text-body font-semibold text-text">{provider.name}</div>
                <Lozenge tone="neutral" className="border-border capitalize">{env}</Lozenge>
              </div>
              <div className="text-body-small text-text-subtle">{provider.capability} · {provider.vendor}</div>
              <div className="mt-050 flex items-center gap-050 text-body-small">
                <span className={cn("h-1.5 w-1.5 rounded-full", t.dot)} />
                <span className={cn("font-medium", t.text)}>{t.label}</span>
                {cfg.latencyMs > 0 && <span className="text-text-subtlest">· {cfg.latencyMs} ms</span>}
                <span className="ml-100 text-text-subtlest">{cfg.region}</span>
              </div>
            </div>
            <Button variant="ghost" size="icon" className="h-400 w-400" onClick={onClose}><X className="h-4 w-4" /></Button>
          </div>

          <Tabs defaultValue="overview" className="flex min-h-0 flex-1 flex-col">
            <TabsList className="h-500 w-full shrink-0 justify-start rounded-none border-b border-border bg-surface p-0">
              {["overview", "credentials", "usage", "test", "pipecat"].map(v => (
                <TabsTrigger key={v} value={v} className="rounded-none border-b-2 border-transparent px-150 text-body-small capitalize data-[state=active]:border-border-brand data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                  {v === "pipecat" ? "Pipecat wiring" : v}
                </TabsTrigger>
              ))}
            </TabsList>

            <TabsContent value="overview" className="mt-0 min-h-0 flex-1 overflow-y-auto p-200">
              <p className="text-body leading-relaxed text-text">{provider.description}</p>
              <div className="mt-150 flex flex-wrap gap-075">
                {provider.capabilities.map(c => (
                  <Lozenge key={c} tone="selected">{c}</Lozenge>
                ))}
              </div>
              <a href={provider.docsUrl} target="_blank" rel="noreferrer" className="mt-200 inline-flex items-center gap-075 text-body-small font-medium text-text-brand hover:underline">
                Provider documentation <ExternalLink className="h-3 w-3" />
              </a>
            </TabsContent>

            <TabsContent value="credentials" className="mt-0 min-h-0 flex-1 overflow-y-auto p-200">
              {locked ? (
                <div className="mb-150 rounded-medium border border-border-information-subtle bg-background-information-subtler p-100 text-body-small text-text-information-bolder">
                  Credentials are managed via process environment / ops vault. This screen shows
                  configuration status only — plaintext keys are never stored in the CRM DB or JS bundle.
                </div>
              ) : env === "production" ? (
                <div className="mb-150 rounded-medium border border-border-warning-subtle bg-background-warning-subtler p-100 text-body-small text-text-warning-bolder">
                  Rotating keys here will restart the Pipecat worker.
                </div>
              ) : null}
              <div className="space-y-150">
                {provider.fields.map(f => (
                  <div key={f.key}>
                    <Label className="text-body-small font-medium text-text-subtlest">{f.label}</Label>
                    {f.secret ? (
                      <MaskedInput
                        value={cfg.values[f.key] ?? ""}
                        onChange={(v) => !locked && setField(f.key, v)}
                        onRotate={locked ? undefined : () => rotate(f.key)}
                        placeholder={locked ? "•••••••• (env/vault)" : f.placeholder}
                      />
                    ) : (
                      <Input
                        className="h-400 font-mono text-body-small"
                        value={cfg.values[f.key] ?? ""}
                        placeholder={f.placeholder}
                        readOnly={locked}
                        onChange={(e) => !locked && setField(f.key, e.target.value)}
                      />
                    )}
                  </div>
                ))}
              </div>
              <div className="mt-200 text-body-small text-text-subtlest">
                {locked
                  ? "Set AZURE_*/TWILIO_*/WHATSAPP_* in backend/.env (or your secret manager)."
                  : "Demo values are placeholders only — never commit real secrets."}
              </div>
            </TabsContent>

            <TabsContent value="usage" className="mt-0 min-h-0 flex-1 overflow-y-auto p-200">
              <div className="grid grid-cols-3 gap-100">
                {cfg.usageStats.map(s => (
                  <div key={s.label} className="rounded-medium border border-border bg-surface p-100">
                    <div className="text-body-small text-text-subtlest">{s.label}</div>
                    <div className="text-body font-semibold text-text">{s.value}</div>
                  </div>
                ))}
              </div>
              <div className="mt-150">
                <div className="mb-050 flex items-center justify-between">
                  <div className="text-body-small font-semibold text-text">14-day {cfg.unitLabel} volume</div>
                  <div className="text-body-small text-text-subtlest">Cost: {cfg.costMonth}</div>
                </div>
                <ChartStage
                  toolbar={
                    <>
                      <span className="text-[11px] text-text-subtlest">Usage snapshot</span>
                      <SnapshotPill />
                    </>
                  }
                >
                  <LivelineTrend
                    values={usageValues}
                    labels={usageLabels}
                    color="#1868db"
                    height={128}
                    formatValue={(v) => Math.round(v).toLocaleString()}
                    formatTime={(i) => usageLabels[i] ?? ""}
                    fill
                  />
                </ChartStage>
              </div>
            </TabsContent>

            <TabsContent value="test" className="mt-0 flex min-h-0 flex-1 flex-col">
              <div className="border-b border-border bg-surface px-200 py-100">
                <Button size="sm" className="w-full gap-075 bg-background-brand-bold hover:bg-background-brand-bold-pressed" onClick={runTest} disabled={testing}>
                  <PlayCircle className="h-3.5 w-3.5" /> {testing ? "Testing…" : "Run test connection"}
                </Button>
              </div>
              <div className="min-h-0 flex-1 space-y-100 overflow-y-auto p-200">
                {providerLogs.length === 0 && (
                  <div className="rounded-medium border border-dashed border-border p-300 text-center text-body-small text-text-subtlest">No tests yet. Run one to see request/response.</div>
                )}
                {providerLogs.map(l => (
                  <div key={l.id} className={cn("rounded-medium border p-100", l.ok ? "border-border-success-subtle bg-background-success-subtler/60" : "border-border-danger-subtle bg-background-danger-subtler/60")}>
                    <div className="flex items-center gap-100 text-body-small">
                      {l.ok ? <CheckCircle2 className="h-3.5 w-3.5 text-text-success" /> : <XCircle className="h-3.5 w-3.5 text-text-danger" />}
                      <span className="flex-1 font-medium text-text">{l.message}</span>
                      <span className="font-mono text-body-small text-text-subtlest">{l.latencyMs} ms</span>
                    </div>
                    <div className="mt-050 text-body-small text-text-subtlest">{new Date(l.at).toLocaleTimeString()} · {l.env}</div>
                    {l.payload && (
                      <pre className="mt-050 max-h-32 overflow-auto rounded bg-surface p-100 font-mono text-body-small text-text">{l.payload}</pre>
                    )}
                  </div>
                ))}
              </div>
            </TabsContent>

            <TabsContent value="pipecat" className="mt-0 min-h-0 flex-1 overflow-y-auto p-200">
              <div className="mb-100 flex items-center justify-between">
                <div className="text-body-small font-semibold text-text">Pipecat wiring</div>
                <Button variant="outline" size="sm" className="h-7 gap-050 text-body-small" onClick={copySnippet}>
                  {copiedSnippet ? <Check className="h-3 w-3 text-text-success" /> : <Copy className="h-3 w-3" />} Copy
                </Button>
              </div>
              <pre className="rounded-medium border border-border bg-background-brand-boldest/95 p-150 font-mono text-body-small leading-relaxed text-white/90">{snippet}</pre>
              <p className="mt-100 text-body-small text-text-subtlest">This is the exact stage the Pipecat worker instantiates for {provider.name}. Values reference environment variables the deploy pipeline injects from this connector's stored credentials.</p>
            </TabsContent>
          </Tabs>
        </div>
      </SheetContent>
    </Sheet>
  );
}
