import { Button } from "@/components/ui/button";
import { PlayCircle } from "lucide-react";
import type { Env } from "@/data/integrations-seed";
import { cn } from "@/lib/utils";

type Props = {
  env: Env;
  onEnv: (e: Env) => void;
  onTestAll: () => void;
  testing: boolean;
};

export function IntegrationsHeader({ env, onEnv, onTestAll, testing }: Props) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="text-[18px] font-semibold text-brand-navy">Integrations & API Connections</h1>
        <p className="text-[12px] text-text-secondary">Keys and health for the voice AI stack Pipecat orchestrates on the backend.</p>
      </div>
      <div className="flex items-center gap-2">
        <div className="flex rounded-md border border-[var(--border-token)] bg-white p-0.5 text-[12px]">
          {(["sandbox", "production"] as Env[]).map(e => (
            <button
              key={e}
              onClick={() => onEnv(e)}
              className={cn(
                "rounded px-3 py-1 font-medium capitalize transition-colors",
                env === e ? "bg-brand-primary text-white" : "text-text-secondary hover:text-brand-primary-dark",
              )}
            >{e}</button>
          ))}
        </div>
        <Button size="sm" className="gap-1.5 bg-brand-primary hover:bg-brand-primary-dark" onClick={onTestAll} disabled={testing}>
          <PlayCircle className="h-4 w-4" />{testing ? "Testing…" : "Test all"}
        </Button>
      </div>
    </div>
  );
}
