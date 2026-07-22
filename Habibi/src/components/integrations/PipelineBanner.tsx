import { PROVIDERS, healthTone, type Env, type Provider } from "@/data/integrations-seed";
import { cn } from "@/lib/utils";
import { ArrowRight, Phone, MessageSquare, Cpu, Mic, Volume2, Database, Workflow } from "lucide-react";

const ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  twilio: Phone, deepgram: Mic, azure_openai: Cpu, openai: Cpu, elevenlabs: Volume2,
  whatsapp: MessageSquare, cbs: Database, pipecat: Workflow,
};

const MAIN = ["twilio", "deepgram", "azure_openai", "elevenlabs"];
const SIDE = ["whatsapp", "cbs"];

type Props = {
  env: Env;
  onOpen: (id: string) => void;
};

function Node({ p, env, onOpen }: { p: Provider; env: Env; onOpen: (id: string) => void }) {
  const t = healthTone(p.perEnv[env].health);
  const Icon = ICON[p.id] ?? Cpu;
  return (
    <button
      onClick={() => onOpen(p.id)}
      className="group flex min-w-[120px] flex-col items-center gap-1 rounded-lg border border-[var(--border-token)] bg-white px-3 py-2 shadow-sm transition-all hover:border-brand-primary hover:shadow"
    >
      <div className={cn("grid h-9 w-9 place-items-center rounded-md", p.brandColor)}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="text-[11px] font-semibold text-brand-navy">{p.name}</div>
      <div className="flex items-center gap-1 text-[10px]">
        <span className={cn("h-1.5 w-1.5 rounded-full", t.dot)} />
        <span className={t.text}>{t.label}</span>
      </div>
    </button>
  );
}

export function PipelineBanner({ env, onOpen }: Props) {
  const main = MAIN.map(id => PROVIDERS.find(p => p.id === id)!).filter(Boolean);
  const side = SIDE.map(id => PROVIDERS.find(p => p.id === id)!).filter(Boolean);
  const orchestrator = PROVIDERS.find(p => p.id === "pipecat")!;

  return (
    <div className="rounded-lg border border-brand-primary/30 bg-gradient-to-br from-brand-tint/60 to-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-[12px] font-semibold uppercase tracking-wide text-brand-primary-dark">Pipecat pipeline</div>
          <p className="text-[11px] text-text-secondary">Each stage below is where the Pipecat backend plugs into this workspace. Click a node to configure it.</p>
        </div>
        <Node p={orchestrator} env={env} onOpen={onOpen} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {main.map((p, i) => (
          <div key={p.id} className="flex items-center gap-2">
            <Node p={p} env={env} onOpen={onOpen} />
            {i < main.length - 1 && <ArrowRight className="h-4 w-4 text-brand-primary/50" />}
          </div>
        ))}
        <div className="mx-2 h-8 w-px bg-[var(--border-token)]" />
        <div className="text-[10px] font-medium uppercase tracking-wider text-text-muted">Side channels</div>
        {side.map(p => <Node key={p.id} p={p} env={env} onOpen={onOpen} />)}
      </div>
    </div>
  );
}
