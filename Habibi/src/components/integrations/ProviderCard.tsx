import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Settings2, PlayCircle } from "lucide-react";
import { healthTone, usageSeries, type Env, type Provider } from "@/data/integrations-seed";
import { cn } from "@/lib/utils";

type Props = {
  provider: Provider;
  env: Env;
  selected: boolean;
  testing: boolean;
  onOpen: () => void;
  onTest: () => void;
  onToggle: (v: boolean) => void;
};

function Sparkline({ id, env }: { id: Provider["id"]; env: Env }) {
  const values = usageSeries(id, env);
  const max = Math.max(...values, 1);
  const w = 120, h = 28;
  const step = w / (values.length - 1);
  const path = values.map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(h - (v / max) * h).toFixed(1)}`).join(" ");
  const area = `${path} L${w},${h} L0,${h} Z`;
  return (
    <svg width={w} height={h} className="text-brand-primary">
      <path d={area} fill="currentColor" opacity="0.12" />
      <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

export function ProviderCard({ provider, env, selected, testing, onOpen, onTest, onToggle }: Props) {
  const cfg = provider.perEnv[env];
  const t = healthTone(cfg.health);
  return (
    <div
      className={cn(
        "flex flex-col rounded-lg border bg-surface-card p-4 transition-all",
        selected ? "border-brand-primary ring-1 ring-brand-primary/30" : "border-[var(--border-token)] hover:border-brand-primary/40",
        !cfg.enabled && "opacity-75",
      )}
    >
      <div className="flex items-start gap-3">
        <div className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-md font-semibold", provider.brandColor)}>
          {provider.brandInitial}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <div className="truncate text-[13px] font-semibold text-brand-navy">{provider.name}</div>
            <span className="rounded-full border border-[var(--border-token)] bg-white px-1.5 py-0.5 text-[10px] font-medium capitalize text-text-secondary">{env}</span>
          </div>
          <div className="text-[11px] text-text-secondary">{provider.capability} · {provider.vendor}</div>
        </div>
        <Switch checked={cfg.enabled} onCheckedChange={onToggle} />
      </div>

      <div className="mt-3 flex items-center gap-2 text-[11px]">
        {testing ? (
          <span className="flex items-center gap-1 text-text-muted"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-primary" /> Testing…</span>
        ) : (
          <>
            <span className={cn("h-1.5 w-1.5 rounded-full", t.dot)} />
            <span className={cn("font-medium", t.text)}>{t.label}</span>
            {cfg.latencyMs > 0 && <span className="text-text-muted">· {cfg.latencyMs} ms</span>}
          </>
        )}
        <span className="ml-auto text-text-muted">{cfg.region}</span>
      </div>

      <div className="mt-3 flex items-end justify-between rounded-md bg-surface-sunken/70 p-2">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-text-muted">This month</div>
          <div className="text-[14px] font-semibold text-brand-navy">{cfg.costMonth}</div>
          <div className="text-[10px] text-text-muted">{cfg.usageStats[0]?.value} {cfg.unitLabel}</div>
        </div>
        <Sparkline id={provider.id} env={env} />
      </div>

      <div className="mt-3 flex items-center gap-2">
        <Button variant="outline" size="sm" className="flex-1 gap-1.5" onClick={onTest} disabled={testing}>
          <PlayCircle className="h-3.5 w-3.5" />Test
        </Button>
        <Button size="sm" className="flex-1 gap-1.5 bg-brand-primary hover:bg-brand-primary-dark" onClick={onOpen}>
          <Settings2 className="h-3.5 w-3.5" />Configure
        </Button>
      </div>
    </div>
  );
}
