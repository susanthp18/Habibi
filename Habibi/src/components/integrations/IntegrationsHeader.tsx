import { Button } from "@/components/ui/button";
import { PlayCircle } from "lucide-react";
import type { Env } from "@/data/integrations-seed";
import { cn } from "@/lib/utils";

type Props = {
  env: Env;
  onEnv: (e: Env) => void;
  onTestAll: () => void;
  testing: boolean;
  showTestAll?: boolean;
};

export function IntegrationsHeader({ env, onEnv, onTestAll, testing, showTestAll = true }: Props) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-150">
      <div>
        <h1 className="text-[1.25rem] font-semibold text-text">Integrations & API connections</h1>
        <p className="text-body-small text-text-subtle">Keys and health for the voice AI stack Pipecat orchestrates on the backend.</p>
      </div>
      <div className="flex items-center gap-100">
        <div className="flex rounded-medium border border-border bg-surface p-025 text-body-small">
          {(["sandbox", "production"] as Env[]).map(e => (
            <button
              key={e}
              onClick={() => onEnv(e)}
              className={cn(
                "rounded px-150 py-050 font-medium capitalize transition-colors",
                env === e ? "bg-background-brand-bold text-white" : "text-text-subtle hover:text-text-brand",
              )}
            >{e}</button>
          ))}
        </div>
        {showTestAll ? (
        <Button size="sm" className="gap-075 bg-background-brand-bold hover:bg-background-brand-bold-pressed" onClick={onTestAll} disabled={testing}>
          <PlayCircle className="h-4 w-4" />{testing ? "Testing…" : "Test all"}
        </Button>
        ) : null}
      </div>
    </div>
  );
}
