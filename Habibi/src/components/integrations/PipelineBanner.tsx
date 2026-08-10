import { PROVIDERS, healthTone, type Env, type Provider } from "@/data/integrations-seed";
import { cn } from "@/lib/utils";
import { ArrowRight, Phone, MessageSquare, Cpu, Mic, Volume2, Database, Workflow } from "lucide-react";

const ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  twilio: Phone, azure_speech_stt: Mic, azure_openai: Cpu, openai: Cpu, azure_speech_tts: Volume2,
  whatsapp: MessageSquare, cbs: Database, pipecat: Workflow,
};

const MAIN = ["twilio", "azure_speech_stt", "azure_openai", "azure_speech_tts"];
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
      className="group flex min-w-[7.5rem] flex-col items-center gap-050 rounded-large border border-border bg-surface px-150 py-100 transition-all hover:border-border-brand"
    >
      <div className={cn("grid h-9 w-9 place-items-center rounded-medium", p.brandColor)}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="text-body-small font-semibold text-text">{p.name}</div>
      <div className="flex items-center gap-050 text-body-small">
        <span className={cn("h-1.5 w-1.5 rounded-full", t.dot)} />
        <span className={t.text}>{t.label}</span>
      </div>
    </button>
  );
}

export function PipelineBanner({ env, onOpen, providers }: Props & { providers?: Provider[] }) {
  const catalog = providers?.length ? providers : PROVIDERS;
  const byId = (id: string) => catalog.find((p) => p.id === id);
  const main = MAIN.map(byId).filter(Boolean) as Provider[];
  const side = SIDE.map(byId).filter(Boolean) as Provider[];
  const orchestrator = byId("pipecat");

  return (
    <div className="rounded-large border border-border-brand/30 bg-gradient-to-br from-background-brand-subtlest/60 to-white p-200">
      <div className="mb-150 flex items-center justify-between">
        <div>
          <div className="text-body-small font-semibold text-text-brand">Pipecat pipeline</div>
          <p className="text-body-small text-text-subtle">Each stage below is where the Pipecat backend plugs into this workspace. Click a node to configure it.</p>
        </div>
        {orchestrator ? <Node p={orchestrator} env={env} onOpen={onOpen} /> : null}
      </div>
      <div className="flex flex-wrap items-center gap-100">
        {main.map((p, i) => (
          <div key={p.id} className="flex items-center gap-100">
            <Node p={p} env={env} onOpen={onOpen} />
            {i < main.length - 1 && <ArrowRight className="h-4 w-4 text-text-brand/50" />}
          </div>
        ))}
        {side.length > 0 && (
          <>
            <div className="mx-100 h-400 w-px bg-border" />
            <div className="text-body-small font-medium text-text-subtlest">Side channels</div>
            {side.map((p) => (
              <Node key={p.id} p={p} env={env} onOpen={onOpen} />
            ))}
          </>
        )}
      </div>
    </div>
  );
}
