import { useEffect, useMemo, useRef, useState } from "react";
import { createLazyFileRoute, useNavigate } from "@tanstack/react-router";
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
  useActiveProdDeployment,
  useDiscardPromptVersion,
  useEnsureStudioDraft,
  useLintPrompt,
  usePersonaPresets,
  useProdDeployments,
  usePromptVersions,
  usePublishStudioDraft,
  useRestorePromptVersionAsDraft,
  useRollbackBotDeployment,
  type PromptLintFinding,
} from "@/api/prompt-studio";
import {
  DEFAULT_GUARDRAILS,
  DEFAULT_PERSONA,
  DEFAULT_VOICE,
  PRESETS,
  nextVersionLabel,
  type Guardrails,
  type PersonaPreset,
  type PersonaState,
  type PromptVersion,
  type VoiceConfig,
} from "@/data/prompt-studio-seed";
import { FileText, Sparkles, Volume2, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";

export const Route = createLazyFileRoute("/prompt-studio")({
  component: PromptStudioPage,
});

type Tab = "prompt" | "persona" | "voice" | "guardrails";
type SaveStatus = "idle" | "saving" | "saved" | "error";

function fingerprint(p: string, persona: PersonaState, voice: VoiceConfig, g: Guardrails) {
  return JSON.stringify({ p, persona, voice, g });
}

function PromptStudioPage() {
  const navigate = useNavigate();
  const { unansweredId, note: gapNote } = Route.useSearch();
  const [gapBannerDismissed, setGapBannerDismissed] = useState(false);
  const versionsQuery = usePromptVersions();
  const presetsQuery = usePersonaPresets();
  const activeDepQuery = useActiveProdDeployment();
  const prodDepsQuery = useProdDeployments();
  const publishMutation = usePublishStudioDraft();
  const restoreMutation = useRestorePromptVersionAsDraft();
  const ensureDraftMutation = useEnsureStudioDraft();
  const discardMutation = useDiscardPromptVersion();
  const rollbackMutation = useRollbackBotDeployment();
  const lintMutation = useLintPrompt();

  const [history, setHistory] = useState<PromptVersion[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<string>("");
  const [persona, setPersona] = useState<PersonaState>(DEFAULT_PERSONA);
  const [voice, setVoice] = useState<VoiceConfig>(DEFAULT_VOICE);
  const [guardrails, setGuardrails] = useState<Guardrails>(DEFAULT_GUARDRAILS);
  const [activePresetId, setActivePresetId] = useState<string>("custom");
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [lintFindings, setLintFindings] = useState<PromptLintFinding[]>([]);

  const [tab, setTab] = useState<Tab>("prompt");
  const [diffOpen, setDiffOpen] = useState(false);
  const [diffBase, setDiffBase] = useState<PromptVersion | undefined>();
  const [publishOpen, setPublishOpen] = useState(false);

  const lastSavedFp = useRef<string>("");
  const autosaveTimer = useRef<number | null>(null);
  const skipAutosave = useRef(false);

  const presets = presetsQuery.data ?? PRESETS;
  const showGapBanner = Boolean((gapNote || unansweredId) && !gapBannerDismissed);
  const activeDeployment = activeDepQuery.data ?? null;
  const priorDeployment = useMemo(() => {
    const rows = prodDepsQuery.data ?? [];
    if (activeDeployment?.rollbackDeploymentId) {
      return rows.find((d) => d.id === activeDeployment.rollbackDeploymentId) ?? null;
    }
    return rows.find((d) => d.status === "retired" || d.status === "rolled_back") ?? null;
  }, [prodDepsQuery.data, activeDeployment]);

  // Hydrate editor from published once; keep history in sync with query refetches.
  useEffect(() => {
    if (!versionsQuery.data?.length) return;
    setHistory(versionsQuery.data);
    if (!hydrated) {
      const live =
        versionsQuery.data.find((v) => v.status === "published") ?? versionsQuery.data[0];
      // Prefer newest draft if present (resume work after refresh).
      const newestDraft = versionsQuery.data.find((v) => v.status === "draft");
      const start = newestDraft ?? live;
      skipAutosave.current = true;
      setPrompt(start.prompt);
      setPersona(start.persona ?? DEFAULT_PERSONA);
      setVoice(start.voice ?? DEFAULT_VOICE);
      setGuardrails(start.guardrails ?? DEFAULT_GUARDRAILS);
      setDraftId(newestDraft?.id ?? null);
      lastSavedFp.current = fingerprint(
        start.prompt,
        start.persona ?? DEFAULT_PERSONA,
        start.voice ?? DEFAULT_VOICE,
        start.guardrails ?? DEFAULT_GUARDRAILS,
      );
      setHydrated(true);
      // Allow autosave after paint.
      window.setTimeout(() => {
        skipAutosave.current = false;
      }, 0);
    }
  }, [versionsQuery.data, hydrated]);

  // Sync persona chip to closest preset (or Custom).
  useEffect(() => {
    const match = presets.find(
      (p) => JSON.stringify(p.traits) === JSON.stringify(persona.traits),
    );
    setActivePresetId(match?.id ?? "custom");
  }, [persona.traits, presets]);

  const published = useMemo(() => {
    return history.find((v) => v.status === "published") ?? history[0];
  }, [history]);

  const dirty = useMemo(() => {
    if (!published) return false;
    return (
      fingerprint(prompt, persona, voice, guardrails) !==
      fingerprint(
        published.prompt,
        published.persona ?? DEFAULT_PERSONA,
        published.voice ?? DEFAULT_VOICE,
        published.guardrails ?? DEFAULT_GUARDRAILS,
      )
    );
  }, [prompt, persona, voice, guardrails, published]);

  const nextLabel = nextVersionLabel(published?.label ?? "v1.0");
  const personaLabel =
    activePresetId === "custom"
      ? "Custom persona"
      : (presets.find((p) => p.id === activePresetId)?.label ?? "Custom persona");
  const busy =
    publishMutation.isPending ||
    restoreMutation.isPending ||
    ensureDraftMutation.isPending ||
    discardMutation.isPending ||
    rollbackMutation.isPending;

  // Debounced autosave while dirty.
  useEffect(() => {
    if (!hydrated || skipAutosave.current) return;
    if (!dirty) {
      setSaveStatus((s) => (s === "saving" ? s : "idle"));
      return;
    }
    const fp = fingerprint(prompt, persona, voice, guardrails);
    if (fp === lastSavedFp.current) return;

    if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current);
    autosaveTimer.current = window.setTimeout(() => {
      void (async () => {
        setSaveStatus("saving");
        try {
          const draft = await ensureDraftMutation.mutateAsync({
            draftId,
            label: nextLabel,
            prompt,
            persona,
            voice,
            guardrails,
            summary: "draft autosave",
          });
          setDraftId(draft.id);
          lastSavedFp.current = fingerprint(draft.prompt, draft.persona, draft.voice, draft.guardrails);
          setSaveStatus("saved");
        } catch {
          setSaveStatus("error");
        }
      })();
    }, 1200);

    return () => {
      if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current);
    };
  }, [
    prompt,
    persona,
    voice,
    guardrails,
    dirty,
    hydrated,
    draftId,
    nextLabel,
    ensureDraftMutation,
  ]);

  const applyPreset = (p: PersonaPreset) => {
    setPrompt(p.promptTemplate);
    setPersona((s) => ({ ...s, traits: p.traits }));
    setActivePresetId(p.id);
    setLintFindings([]);
    toast.success(`Applied preset: ${p.label}`);
  };

  const loadDraft = (v: PromptVersion) => {
    skipAutosave.current = true;
    setDraftId(v.id);
    setPrompt(v.prompt);
    setPersona(v.persona);
    setVoice(v.voice);
    setGuardrails(v.guardrails);
    lastSavedFp.current = fingerprint(v.prompt, v.persona, v.voice, v.guardrails);
    setLintFindings([]);
    setSaveStatus("saved");
    window.setTimeout(() => {
      skipAutosave.current = false;
    }, 0);
    toast.info(`Loaded draft ${v.label || v.id}`);
  };

  const discardDraft = async (v: PromptVersion) => {
    try {
      await discardMutation.mutateAsync(v.id);
      if (draftId === v.id) {
        const live = published;
        if (live) {
          skipAutosave.current = true;
          setDraftId(null);
          setPrompt(live.prompt);
          setPersona(live.persona);
          setVoice(live.voice);
          setGuardrails(live.guardrails);
          lastSavedFp.current = fingerprint(live.prompt, live.persona, live.voice, live.guardrails);
          setSaveStatus("idle");
          window.setTimeout(() => {
            skipAutosave.current = false;
          }, 0);
        }
      }
      toast.success(`Discarded draft ${v.label || v.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Discard failed");
    }
  };

  const restore = async (v: PromptVersion) => {
    try {
      const draft = await restoreMutation.mutateAsync(v.id);
      loadDraft(draft);
      toast.info(`Restored ${v.label} into draft — publish to make it live.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Restore failed");
    }
  };

  const publish = async (note: string) => {
    try {
      const publishedRow = await publishMutation.mutateAsync({
        draftId,
        label: nextLabel,
        prompt,
        persona,
        voice,
        guardrails,
        summary: note,
      });
      skipAutosave.current = true;
      setDraftId(null);
      setPublishOpen(false);
      setPrompt(publishedRow.prompt);
      setPersona(publishedRow.persona);
      setVoice(publishedRow.voice);
      setGuardrails(publishedRow.guardrails);
      lastSavedFp.current = fingerprint(
        publishedRow.prompt,
        publishedRow.persona,
        publishedRow.voice,
        publishedRow.guardrails,
      );
      setSaveStatus("idle");
      setLintFindings([]);
      window.setTimeout(() => {
        skipAutosave.current = false;
      }, 0);
      toast.success(`Published ${publishedRow.label || nextLabel}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Publish failed");
    }
  };

  const onRollback = async () => {
    const targetId = activeDeployment?.rollbackDeploymentId ?? priorDeployment?.id;
    if (!targetId) {
      toast.info("No prior production deployment to roll back to.");
      return;
    }
    try {
      const dep = await rollbackMutation.mutateAsync(targetId);
      const live = (await versionsQuery.refetch()).data?.find((v) => v.id === dep.promptVersionId);
      if (live) {
        skipAutosave.current = true;
        setDraftId(null);
        setPrompt(live.prompt);
        setPersona(live.persona);
        setVoice(live.voice);
        setGuardrails(live.guardrails);
        lastSavedFp.current = fingerprint(live.prompt, live.persona, live.voice, live.guardrails);
        window.setTimeout(() => {
          skipAutosave.current = false;
        }, 0);
      }
      toast.success(`Rolled back live config to ${dep.promptVersionId}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Rollback failed");
    }
  };

  const onLint = async () => {
    try {
      const findings = await lintMutation.mutateAsync({ prompt, guardrails });
      setLintFindings(findings);
      setTab("prompt");
      if (!findings.length) toast.success("Lint clean — no issues found");
      else {
        const errors = findings.filter((f) => f.severity === "error").length;
        toast.message(`Lint: ${findings.length} finding(s)`, {
          description: errors ? `${errors} error(s) to review before publish` : "Warnings only",
        });
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Lint failed");
    }
  };

  const onTestSandbox = async () => {
    try {
      let versionId = published?.id;
      if (dirty) {
        const draft = await ensureDraftMutation.mutateAsync({
          draftId,
          label: nextLabel,
          prompt,
          persona,
          voice,
          guardrails,
          summary: "sandbox try",
        });
        setDraftId(draft.id);
        lastSavedFp.current = fingerprint(draft.prompt, draft.persona, draft.voice, draft.guardrails);
        versionId = draft.id;
      }
      if (!versionId) {
        toast.info("No version to test yet.");
        return;
      }
      void navigate({
        to: "/sandbox",
        search: { promptVersionId: versionId },
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not prepare sandbox draft");
    }
  };

  const TABS: Array<{ key: Tab; label: string; icon: typeof FileText }> = [
    { key: "prompt", label: "System Prompt", icon: FileText },
    { key: "persona", label: "Persona", icon: Sparkles },
    { key: "voice", label: "Voice (TTS)", icon: Volume2 },
    { key: "guardrails", label: "Guardrails", icon: ShieldAlert },
  ];

  const loading = versionsQuery.isLoading && !hydrated;
  const currentSnapshot = {
    label: dirty ? `${nextLabel} (draft)` : published?.label ?? "draft",
    prompt,
    persona,
    voice,
    guardrails,
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <StudioHeader
          currentVersion={published?.label ?? "—"}
          nextVersion={nextLabel}
          dirty={dirty}
          personaLabel={personaLabel}
          saveStatus={saveStatus}
          onTestSandbox={() => void onTestSandbox()}
          onPublish={() => setPublishOpen(true)}
          onLint={() => void onLint()}
          lintBusy={lintMutation.isPending}
        />

        {showGapBanner && (
          <div className="mx-5 mt-3 flex items-start justify-between gap-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-900">
            <div>
              <div className="font-semibold text-amber-950">Fixing unanswered question</div>
              <div className="mt-0.5 text-amber-900/90">
                {gapNote || "Review the system prompt for this coverage gap."}
                {unansweredId ? (
                  <span className="ml-1 font-mono text-[11px] text-amber-800/70">({unansweredId})</span>
                ) : null}
              </div>
              <div className="mt-1 text-[11px] text-amber-800/80">
                Banner only — edit the prompt yourself; nothing is auto-injected.
              </div>
            </div>
            <button
              type="button"
              onClick={() => {
                setGapBannerDismissed(true);
                void navigate({ to: "/prompt-studio", search: {} });
              }}
              className="shrink-0 rounded border border-amber-300 px-2 py-0.5 text-[11px] hover:bg-amber-100"
            >
              Dismiss
            </button>
          </div>
        )}

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

        {loading ? (
          <div className="p-5 text-[13px] text-text-muted">Loading prompt studio…</div>
        ) : versionsQuery.isError ? (
          <div className="p-5 text-[13px] text-rose-700">
            Failed to load prompt versions. Check the API / mock toggle.
          </div>
        ) : (
          <div className="grid min-h-0 flex-1 grid-cols-1 xl:grid-cols-[1fr_320px]">
            <div className="min-h-0 overflow-y-auto p-5">
              {tab === "prompt" && (
                <PromptEditor
                  value={prompt}
                  onChange={setPrompt}
                  onApplyPreset={applyPreset}
                  presets={presets}
                  lintFindings={lintFindings}
                  onClearLint={() => setLintFindings([])}
                />
              )}
              {tab === "persona" && (
                <PersonaSliders
                  value={persona}
                  onChange={setPersona}
                  presets={presets}
                  voice={voice}
                />
              )}
              {tab === "voice" && (
                <VoicePanel value={voice} onChange={setVoice} />
              )}
              {tab === "guardrails" && (
                <GuardrailsPanel value={guardrails} onChange={setGuardrails} />
              )}
            </div>
            <div className="hidden min-h-0 xl:block">
              <VersionHistory
                versions={history}
                activeDraftId={draftId}
                activeDeployment={activeDeployment}
                priorDeployment={priorDeployment}
                onCompare={(v) => {
                  setDiffBase(v);
                  setDiffOpen(true);
                }}
                onRestore={(v) => void restore(v)}
                onLoadDraft={loadDraft}
                onDiscardDraft={(v) => void discardDraft(v)}
                onRollback={() => void onRollback()}
                rollbackBusy={rollbackMutation.isPending}
              />
            </div>
          </div>
        )}

        <DiffModal
          open={diffOpen}
          onOpenChange={setDiffOpen}
          base={diffBase}
          current={currentSnapshot}
        />

        <PublishDialog
          open={publishOpen}
          onOpenChange={setPublishOpen}
          fromLabel={published?.label ?? "—"}
          toLabel={nextLabel}
          from={{
            prompt: published?.prompt ?? "",
            persona: published?.persona ?? DEFAULT_PERSONA,
            voice: published?.voice ?? DEFAULT_VOICE,
            guardrails: published?.guardrails ?? DEFAULT_GUARDRAILS,
          }}
          to={{ prompt, persona, voice, guardrails }}
          onConfirm={(note) => void publish(note)}
        />

        {busy && (
          <div className="pointer-events-none fixed bottom-4 right-4 rounded-md bg-brand-navy/90 px-3 py-1.5 text-[11px] text-white shadow-lg">
            Saving…
          </div>
        )}
      </div>
    </AppShell>
  );
}
