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
      <div className="min-h-0 flex-1 overflow-y-auto p-200">
        <div className="mb-150">
          <div className="mb-075 text-body-small font-medium text-text-subtlest">Presets</div>
          <div className="flex flex-wrap gap-075">
            {PRESET_CONTEXTS.map(p => (
              <button
                key={p.label}
                onClick={() => { setCtx(p.ctx); setRan(false); }}
                className="rounded-full border border-border bg-surface px-150 py-050 text-body-small font-medium text-text-subtle hover:border-border-brand/40 hover:text-text-brand"
              >{p.label}</button>
            ))}
          </div>
        </div>

        <div className="rounded-large border border-border bg-surface p-150">
          <div className="mb-100 text-body-small font-semibold text-text-subtlest">Mock call context</div>
          <div className="grid grid-cols-2 gap-100">
            {FIELDS.map(f => (
              <div key={f.key}>
                <Label className="text-body-small text-text-subtlest">{f.label}</Label>
                {f.type === "enum" ? (
                  <Select value={String((ctx as any)[f.key])} onValueChange={(v) => update(f.key as keyof SimContext, v)}>
                    <SelectTrigger className="mt-025 h-400 text-body-small"><SelectValue /></SelectTrigger>
                    <SelectContent>{f.options!.map(o => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
                  </Select>
                ) : f.type === "boolean" ? (
                  <div className="mt-075"><Switch aria-label={f.label} checked={Boolean((ctx as any)[f.key])} onCheckedChange={(v) => update(f.key as keyof SimContext, v)} /></div>
                ) : (
                  <Input
                    className="mt-025 h-400 text-body-small"
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
          <div className="mt-200">
            <div className="mb-100 flex items-center justify-between">
              <div className="text-body-small font-semibold text-text-subtlest">Evaluation</div>
              <div className="text-body-small text-text-subtlest">
                {results.length} rules · {results.filter(r => r.matched).length} matched
              </div>
            </div>
            {firing && (
              <div className="mb-150 rounded-large border border-border-success bg-background-success-subtler p-150">
                <div className="flex items-center gap-100 text-body-small font-semibold text-text-success-bolder">
                  <ArrowRight className="h-4 w-4" /> Firing action
                </div>
                <div className="mt-050 text-body font-semibold text-text">{ACTION_LABEL[firing.then.key]}</div>
                <div className="text-body-small text-text-subtle">from rule: {firing.name}</div>
              </div>
            )}
            {!firing && (
              <div className="mb-150 rounded-large border border-border bg-surface-sunken p-150 text-body-small text-text-subtle">
                No rule matched — default flow continues.
              </div>
            )}
            <div className="space-y-075">
              {results.map(r => (
                <div key={r.rule.id} className={cn(
                  "rounded-medium border p-100",
                  r.matched ? "border-border-success-subtle bg-background-success-subtler/60" : "border-border bg-surface",
                  firing?.id === r.rule.id && "ring-1 ring-border-border-success",
                )}>
                  <div className="flex items-center gap-100 text-body-small">
                    {r.matched ? <CheckCircle2 className="h-3.5 w-3.5 text-text-success" /> : <XCircle className="h-3.5 w-3.5 text-text-subtlest" />}
                    <span className="flex-1 font-medium text-text">{r.rule.name}</span>
                    <span className="font-mono text-body-small text-text-subtlest">{r.latencyMs} ms</span>
                  </div>
                  <div className="mt-050 flex flex-wrap gap-050">
                    {r.nodes.flatMap(n => n.conditions).map(c => (
                      <span key={c.id} className={cn(
                        "rounded px-075 py-025 font-mono text-body-small",
                        c.matched ? "bg-background-success-subtler text-text-success-bolder" : "bg-background-danger-subtler text-text-danger",
                      )}>{c.label}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="flex shrink-0 items-center justify-end gap-100 border-t border-border bg-surface px-200 py-150">
        <Button size="sm" className="gap-075 bg-background-brand-bold hover:bg-background-brand-bold-pressed" onClick={run}>
          <Play className="h-3.5 w-3.5" /> Run evaluation
        </Button>
      </div>
    </div>
  );
}
