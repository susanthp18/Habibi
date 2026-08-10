import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Settings2, PlayCircle } from "lucide-react";
import { healthTone, usageSeries, type Env, type Provider } from "@/data/integrations-seed";
import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";

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
    <svg width={w} height={h} className="text-text-brand">
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
        "flex flex-col rounded-large border bg-surface p-200 transition-all",
        selected ? "border-border-brand ring-1 ring-border-brand/30" : "border-border hover:border-border-brand/40",
        !cfg.enabled && "opacity-75",
      )}
    >
      <div className="flex items-start gap-150">
        <div className={cn("grid h-500 w-500 shrink-0 place-items-center rounded-medium font-semibold", provider.brandColor)}>
          {provider.brandInitial}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-100">
            <div className="truncate text-body font-semibold text-text">{provider.name}</div>
            <Lozenge tone="neutral" className="border-border capitalize">{env}</Lozenge>
          </div>
          <div className="text-body-small text-text-subtle">{provider.capability} · {provider.vendor}</div>
        </div>
        <Switch checked={cfg.enabled} onCheckedChange={onToggle} />
      </div>

      <div className="mt-150 flex items-center gap-100 text-body-small">
        {testing ? (
          <span className="flex items-center gap-050 text-text-subtlest"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-background-brand-bold" /> Testing…</span>
        ) : (
          <>
            <span className={cn("h-1.5 w-1.5 rounded-full", t.dot)} />
            <span className={cn("font-medium", t.text)}>{t.label}</span>
            {cfg.latencyMs > 0 && <span className="text-text-subtlest">· {cfg.latencyMs} ms</span>}
          </>
        )}
        <span className="ml-auto text-text-subtlest">{cfg.region}</span>
      </div>

      <div className="mt-150 flex items-end justify-between rounded-medium bg-surface-sunken/70 p-100">
        <div>
          <div className="text-body-small text-text-subtlest">This month</div>
          <div className="text-body font-semibold text-text">{cfg.costMonth}</div>
          <div className="text-body-small text-text-subtlest">{cfg.usageStats[0]?.value} {cfg.unitLabel}</div>
        </div>
        <Sparkline id={provider.id} env={env} />
      </div>

      <div className="mt-150 flex items-center gap-100">
        <Button variant="outline" size="sm" className="flex-1 gap-075" onClick={onTest} disabled={testing}>
          <PlayCircle className="h-3.5 w-3.5" />Test
        </Button>
        <Button size="sm" className="flex-1 gap-075 bg-background-brand-bold hover:bg-background-brand-bold-pressed" onClick={onOpen}>
          <Settings2 className="h-3.5 w-3.5" />Configure
        </Button>
      </div>
    </div>
  );
}
