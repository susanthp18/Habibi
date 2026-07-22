import { useState } from "react";
import { Play, CheckCircle2, XCircle, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  ACTION_LABEL,
  DEFAULT_CONTEXT,
  FIELDS,
  PRESET_CONTEXTS,
  evaluateRules,
  type Rule,
  type RuleEval,
  type SimContext,
} from "@/data/routing-seed";
import { cn } from "@/lib/utils";

export function Simulator({ rules }: { rules: Rule[] }) {
  const [ctx, setCtx] = useState<SimContext>(DEFAULT_CONTEXT);
  const [results, setResults] = useState<RuleEval[]>([]);
  const [firing, setFiring] = useState<Rule | undefined>(undefined);
  const [ran, setRan] = useState(false);

  const run = () => {
    const r = evaluateRules(rules, ctx);
    setResults(r.results);
    setFiring(r.firing?.rule);
    setRan(true);
  };

  const update = (key: keyof SimContext, val: unknown) => setCtx({ ...ctx, [key]: val } as SimContext);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="mb-3">
          <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-text-muted">Presets</div>
          <div className="flex flex-wrap gap-1.5">
            {PRESET_CONTEXTS.map(p => (
              <button
                key={p.label}
                onClick={() => { setCtx(p.ctx); setRan(false); }}
                className="rounded-full border border-[var(--border-token)] bg-white px-2.5 py-1 text-[11px] font-medium text-text-secondary hover:border-brand-primary/40 hover:text-brand-primary-dark"
              >{p.label}</button>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-[var(--border-token)] bg-surface-card p-3">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Mock call context</div>
          <div className="grid grid-cols-2 gap-2">
            {FIELDS.map(f => (
              <div key={f.key}>
                <Label className="text-[10px] text-text-muted">{f.label}</Label>
                {f.type === "enum" ? (
                  <Select value={String((ctx as any)[f.key])} onValueChange={(v) => update(f.key as keyof SimContext, v)}>
                    <SelectTrigger className="mt-0.5 h-8 text-[12px]"><SelectValue /></SelectTrigger>
                    <SelectContent>{f.options!.map(o => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
                  </Select>
                ) : f.type === "boolean" ? (
                  <div className="mt-1.5"><Switch checked={Boolean((ctx as any)[f.key])} onCheckedChange={(v) => update(f.key as keyof SimContext, v)} /></div>
                ) : (
                  <Input
                    className="mt-0.5 h-8 text-[12px]"
                    type="number"
                    value={String((ctx as any)[f.key])}
                    onChange={(e) => update(f.key as keyof SimContext, Number(e.target.value))}
                  />
                )}
              </div>
            ))}
          </div>
        </div>

        {ran && (
          <div className="mt-4">
            <div className="mb-2 flex items-center justify-between">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">Evaluation</div>
              <div className="text-[11px] text-text-muted">
                {results.length} rules · {results.filter(r => r.matched).length} matched
              </div>
            </div>
            {firing && (
              <div className="mb-3 rounded-lg border border-emerald-300 bg-emerald-50 p-3">
                <div className="flex items-center gap-2 text-[12px] font-semibold text-emerald-800">
                  <ArrowRight className="h-4 w-4" /> Firing action
                </div>
                <div className="mt-1 text-[13px] font-semibold text-brand-navy">{ACTION_LABEL[firing.then.key]}</div>
                <div className="text-[11px] text-text-secondary">from rule: {firing.name}</div>
              </div>
            )}
            {!firing && (
              <div className="mb-3 rounded-lg border border-[var(--border-token)] bg-surface-sunken p-3 text-[12px] text-text-secondary">
                No rule matched — default flow continues.
              </div>
            )}
            <div className="space-y-1.5">
              {results.map(r => (
                <div key={r.rule.id} className={cn(
                  "rounded-md border p-2",
                  r.matched ? "border-emerald-200 bg-emerald-50/60" : "border-[var(--border-token)] bg-white",
                  firing?.id === r.rule.id && "ring-1 ring-emerald-400",
                )}>
                  <div className="flex items-center gap-2 text-[12px]">
                    {r.matched ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : <XCircle className="h-3.5 w-3.5 text-text-muted" />}
                    <span className="flex-1 font-medium text-brand-navy">{r.rule.name}</span>
                    <span className="font-mono text-[10px] text-text-muted">{r.latencyMs} ms</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {r.nodes.flatMap(n => n.conditions).map(c => (
                      <span key={c.id} className={cn(
                        "rounded px-1.5 py-0.5 font-mono text-[10px]",
                        c.matched ? "bg-emerald-100 text-emerald-800" : "bg-red-50 text-red-600",
                      )}>{c.label}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="flex shrink-0 items-center justify-end gap-2 border-t border-[var(--border-token)] bg-surface-card px-4 py-2.5">
        <Button size="sm" className="gap-1.5 bg-brand-primary hover:bg-brand-primary-dark" onClick={run}>
          <Play className="h-3.5 w-3.5" /> Run evaluation
        </Button>
      </div>
    </div>
  );
}
