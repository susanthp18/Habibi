import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { StudioHeader } from "@/components/prompt-studio/StudioHeader";
import { PromptEditor } from "@/components/prompt-studio/PromptEditor";
import { PersonaSliders } from "@/components/prompt-studio/PersonaSliders";
import { VoicePanel } from "@/components/prompt-studio/VoicePanel";
import { GuardrailsPanel } from "@/components/prompt-studio/GuardrailsPanel";
import { VersionHistory } from "@/components/prompt-studio/VersionHistory";
import { DiffModal } from "@/components/prompt-studio/DiffModal";
import { PublishDialog } from "@/components/prompt-studio/PublishDialog";
import {
  DEFAULT_GUARDRAILS,
  DEFAULT_PERSONA,
  DEFAULT_VOICE,
  PRESETS,
  VERSION_HISTORY,
  nextVersionLabel,
  type Guardrails,
  type PersonaPreset,
  type PersonaState,
  type PromptVersion,
  type VoiceConfig,
} from "@/data/prompt-studio-seed";
import { FileText, Sparkles, Volume2, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/prompt-studio")({
  head: () => ({
    meta: [
      { title: "Persona & Prompt Studio — Collections Agent" },
      {
        name: "description",
        content:
          "Tune the collections bot's system prompt, persona sliders, TTS voice and guardrails. Version, diff, preview and publish safely.",
      },
      { property: "og:title", content: "Persona & Prompt Studio" },
      {
        property: "og:description",
        content: "Author, version and publish the AI voice agent's prompt, persona and guardrails.",
      },
    ],
  }),
  component: PromptStudioPage,
});

type Tab = "prompt" | "persona" | "voice" | "guardrails";

function PromptStudioPage() {
  const published = VERSION_HISTORY.find((v) => v.status === "published") ?? VERSION_HISTORY[0];

  const [history, setHistory] = useState<PromptVersion[]>(VERSION_HISTORY);
  const [prompt, setPrompt] = useState<string>(published.prompt);
  const [persona, setPersona] = useState<PersonaState>(published.persona ?? DEFAULT_PERSONA);
  const [voice, setVoice] = useState<VoiceConfig>(published.voice ?? DEFAULT_VOICE);
  const [guardrails, setGuardrails] = useState<Guardrails>(published.guardrails ?? DEFAULT_GUARDRAILS);
  const [activePresetId, setActivePresetId] = useState<string>(PRESETS[0].id);

  const [tab, setTab] = useState<Tab>("prompt");
  const [diffOpen, setDiffOpen] = useState(false);
  const [diffBase, setDiffBase] = useState<PromptVersion | undefined>();
  const [publishOpen, setPublishOpen] = useState(false);

  const dirty = useMemo(() => {
    return (
      prompt !== published.prompt ||
      JSON.stringify(persona) !== JSON.stringify(published.persona) ||
      JSON.stringify(voice) !== JSON.stringify(published.voice) ||
      JSON.stringify(guardrails) !== JSON.stringify(published.guardrails)
    );
  }, [prompt, persona, voice, guardrails, published]);

  const nextLabel = nextVersionLabel(published.label);
  const personaLabel = PRESETS.find((p) => p.id === activePresetId)?.label ?? "Custom persona";

  const applyPreset = (p: PersonaPreset) => {
    setPrompt(p.promptTemplate);
    setPersona((s) => ({ ...s, traits: p.traits }));
    setActivePresetId(p.id);
    toast.success(`Applied preset: ${p.label}`);
  };

  const restore = (v: PromptVersion) => {
    setPrompt(v.prompt);
    setPersona(v.persona);
    setVoice(v.voice);
    setGuardrails(v.guardrails);
    toast.info(`Restored ${v.label} into draft — publish to make it live.`);
  };

  const publish = (note: string) => {
    const newVersion: PromptVersion = {
      id: nextLabel.replace(".", "_"),
      label: nextLabel,
      author: "You",
      status: "published",
      createdAt: new Date().toISOString(),
      summary: note,
      prompt,
      persona,
      voice,
      guardrails,
    };
    setHistory((prev) => [newVersion, ...prev.map((v) => (v.status === "published" ? { ...v, status: "archived" as const } : v))]);
    setPublishOpen(false);
    toast.success(`Published ${nextLabel}`);
  };

  const TABS: Array<{ key: Tab; label: string; icon: any }> = [
    { key: "prompt", label: "System Prompt", icon: FileText },
    { key: "persona", label: "Persona", icon: Sparkles },
    { key: "voice", label: "Voice (TTS)", icon: Volume2 },
    { key: "guardrails", label: "Guardrails", icon: ShieldAlert },
  ];

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <StudioHeader
          currentVersion={published.label}
          nextVersion={nextLabel}
          dirty={dirty}
          personaLabel={personaLabel}
          onTestSandbox={() => toast.info("Config staged for Call Simulation Sandbox (module 4.3).")}
          onPublish={() => setPublishOpen(true)}
        />

        <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-5">
          <div className="flex gap-1">
            {TABS.map((t) => {
              const Icon = t.icon;
              return (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={cn(
                    "inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-[12.5px]",
                    tab === t.key
                      ? "border-brand-primary font-semibold text-brand-primary-dark"
                      : "border-transparent text-text-secondary hover:text-text-primary",
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {t.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 xl:grid-cols-[1fr_320px]">
          <div className="min-h-0 overflow-y-auto p-5">
            {tab === "prompt" && (
              <PromptEditor value={prompt} onChange={setPrompt} onApplyPreset={applyPreset} />
            )}
            {tab === "persona" && <PersonaSliders value={persona} onChange={setPersona} />}
            {tab === "voice" && <VoicePanel value={voice} onChange={setVoice} />}
            {tab === "guardrails" && <GuardrailsPanel value={guardrails} onChange={setGuardrails} />}
          </div>
          <div className="hidden min-h-0 xl:block">
            <VersionHistory
              versions={history}
              onCompare={(v) => {
                setDiffBase(v);
                setDiffOpen(true);
              }}
              onRestore={restore}
            />
          </div>
        </div>

        <DiffModal
          open={diffOpen}
          onOpenChange={setDiffOpen}
          base={diffBase}
          current={{ label: dirty ? `${nextLabel} (draft)` : published.label, prompt }}
        />

        <PublishDialog
          open={publishOpen}
          onOpenChange={setPublishOpen}
          fromLabel={published.label}
          toLabel={nextLabel}
          fromPrompt={published.prompt}
          toPrompt={prompt}
          onConfirm={publish}
        />
      </div>
    </AppShell>
  );
}
