import { useEffect, useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Settings2, ShieldCheck, CheckCircle2 } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { RedactionStatsStrip } from "@/components/redaction/RedactionStatsStrip";
import { RecordPicker } from "@/components/redaction/RecordPicker";
import { TranscriptRedactor } from "@/components/redaction/TranscriptRedactor";
import { AudioBeepTimeline } from "@/components/redaction/AudioBeepTimeline";
import { PiiLegend } from "@/components/redaction/PiiLegend";
import { ExportConfigPanel } from "@/components/redaction/ExportConfigPanel";
import { ExportAuditLog } from "@/components/redaction/ExportAuditLog";
import { RulesSheet } from "@/components/redaction/RulesSheet";
import {
  bumpExportDownload,
  createExportJob,
  markRedactionReviewed,
  patchRedactionRuleEnabled,
  retryExportJob,
  toggleAudioMuted,
  toggleFindingAccepted,
  useExportJobs,
  useRedactionRecords,
  useRedactionRules,
} from "@/api/redaction";
import { Lozenge } from "@/components/ui/lozenge";
import {
  DEFAULT_RULES,
  ENTITY_TYPES,
  defaultFilter,
  filterRecords,
  formatDateTime,
  statsFor,
  type ExportFormat,
  type ExportScope,
  type PiiEntityType,
  type RecordFilter,
  type RedactionRecord,
  type RedactionRules,
} from "@/data/redaction-seed";

export const Route = createFileRoute("/redaction")({
  head: () => ({
    meta: [
      { title: "Redaction & Export Hub — BigBound AI" },
      {
        name: "description",
        content:
          "Compliance-controlled export workflow — auto-detect PII in transcripts and audio, preview masks, and ship watermarked bundles with an immutable audit log.",
      },
      { property: "og:title", content: "Redaction & Export Hub" },
      {
        property: "og:description",
        content:
          "Select call records, preview PII detection, tune redaction rules, and export watermarked evidence for regulators.",
      },
    ],
  }),
  component: RedactionPage,
});

function RedactionPage() {
  const queryClient = useQueryClient();
  const { data: remoteRecords } = useRedactionRecords();
  const { data: remoteRules } = useRedactionRules();
  const { data: remoteExports } = useExportJobs();

  const [filter, setFilter] = useState<RecordFilter>(defaultFilter);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [rulesOpen, setRulesOpen] = useState(false);

  const [format, setFormat] = useState<ExportFormat>("pdf");
  const [scope, setScope] = useState<ExportScope[]>(["transcript", "metadata"]);
  const [watermark, setWatermark] = useState("HDFC-CONFIDENTIAL · Compliance review");
  const [accessRole, setAccessRole] = useState("Compliance Officer");

  const rules = remoteRules ?? DEFAULT_RULES;
  const recordState = remoteRecords ?? [];
  const exports = remoteExports ?? [];

  const invalidateRecords = () =>
    queryClient.invalidateQueries({ queryKey: ["redaction-records"] });
  const invalidateRules = () => queryClient.invalidateQueries({ queryKey: ["redaction-rules"] });
  const invalidateExports = () => queryClient.invalidateQueries({ queryKey: ["export-jobs"] });

  useEffect(() => {
    if (!activeId && recordState.length > 0) {
      setActiveId(recordState[0]!.id);
    }
  }, [activeId, recordState]);

  const activeTypes = useMemo(
    () => new Set<PiiEntityType>(ENTITY_TYPES.filter((t) => rules[t].enabled)),
    [rules],
  );

  const visibleRecords = useMemo(() => filterRecords(recordState, filter), [recordState, filter]);

  const active = useMemo(
    () => recordState.find((r) => r.id === activeId) ?? null,
    [recordState, activeId],
  );

  const activeForRender: RedactionRecord | null = useMemo(() => {
    if (!active) return null;
    return {
      ...active,
      findings: active.findings.filter((f) => activeTypes.has(f.type)),
      audioSegments: active.audioSegments.filter((s) => activeTypes.has(s.type)),
    };
  }, [active, activeTypes]);

  const stats = useMemo(() => statsFor(recordState, exports), [recordState, exports]);

  const toggleFinding = (findingId: string) => {
    if (!activeId) return;
    const base = recordState.find((r) => r.id === activeId);
    if (!base) return;
    const finding = base.findings.find((f) => f.id === findingId);
    if (!finding) return;
    const next = !finding.accepted;
    void toggleFindingAccepted(findingId, next)
      .then(() => invalidateRecords())
      .catch((err: Error) => toast.error("Could not update finding", { description: err.message }));
  };

  const toggleSegment = (findingId: string) => {
    if (!activeId) return;
    const base = recordState.find((r) => r.id === activeId);
    if (!base) return;
    const seg = base.audioSegments.find((s) => s.findingId === findingId);
    if (!seg) return;
    void toggleAudioMuted(activeId, findingId, !seg.muted)
      .then(() => invalidateRecords())
      .catch((err: Error) => toast.error("Could not mute segment", { description: err.message }));
  };

  const toggleSelect = (id: string) => {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  };

  const selectAllWithPii = () => {
    setSelected(new Set(visibleRecords.filter((r) => r.findings.length > 0).map((r) => r.id)));
  };

  const toggleRule = (t: PiiEntityType) => {
    const enabled = !rules[t].enabled;
    void patchRedactionRuleEnabled(t, enabled)
      .then(() => invalidateRules())
      .catch((err: Error) => toast.error("Could not update rule", { description: err.message }));
  };

  const markReviewed = () => {
    if (!active) return;
    void markRedactionReviewed(active.id)
      .then(() => {
        invalidateRecords();
        toast.success(`Marked ${active.id} as reviewed`);
      })
      .catch((err: Error) => toast.error("Could not mark reviewed", { description: err.message }));
  };

  const generateExport = () => {
    if (selected.size === 0) return;
    const ids = Array.from(selected);
    void createExportJob({
      recordIds: ids,
      format,
      scope,
      watermark,
      actorRole: accessRole,
    })
      .then((job) => {
        invalidateExports();
        toast.success(`${job.id} ready`, {
          description: `${ids.length} record(s) · ${job.entitiesRedacted} PII entities`,
        });
        setSelected(new Set());
      })
      .catch((err: Error) => toast.error("Export failed", { description: err.message }));
  };

  const download = (id: string) => {
    void bumpExportDownload(id)
      .then(() => {
        invalidateExports();
        toast.success(`Downloading ${id}`);
      })
      .catch((err: Error) => toast.error("Download failed", { description: err.message }));
  };

  const retry = (id: string) => {
    void retryExportJob(id)
      .then(() => {
        invalidateExports();
        toast.success(`${id} re-queued`);
      })
      .catch((err: Error) => toast.error("Retry failed", { description: err.message }));
  };

  const pendingReviewInSelection = recordState.filter(
    (r) => selected.has(r.id) && !r.reviewed && r.findings.length > 0,
  ).length;

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
          <div className="flex items-center gap-100">
            <h1 className="heading-medium font-semibold text-text">Redaction & export hub</h1>
            <Lozenge tone="selected">
              <ShieldCheck className="h-3 w-3" /> Compliance Officer
            </Lozenge>
            <button
              onClick={() => setRulesOpen(true)}
              className="ml-auto inline-flex items-center gap-050 rounded-medium border border-border bg-surface px-150 py-050 text-body-small text-text hover:bg-surface-sunken"
            >
              <Settings2 className="h-3.5 w-3.5" /> Redaction rules
            </button>
          </div>
          <p className="text-body-small text-text-subtle">
            Auto-detect and mask PII in transcripts and audio, then ship watermarked evidence to
            regulators — every download logged.
          </p>
        </header>

        <RedactionStatsStrip
          monthlyExports={stats.monthlyExports}
          entitiesMasked={stats.entitiesMasked}
          pendingReview={stats.pendingReview}
          totalFindings={stats.totalFindings}
          failed={stats.failed}
        />

        <div className="flex min-h-0 flex-1">
          <RecordPicker
            records={visibleRecords}
            filter={filter}
            onFilter={setFilter}
            selected={selected}
            onToggle={toggleSelect}
            onSelectAllWithPii={selectAllWithPii}
            onClearSelection={() => setSelected(new Set())}
            activeId={activeId}
            onOpen={setActiveId}
          />

          <section className="flex min-h-0 flex-1 flex-col bg-surface">
            {activeForRender ? (
              <>
                <div className="shrink-0 border-b border-border bg-surface px-250 py-150">
                  <div className="flex items-center gap-100">
                    <div className="text-body font-semibold text-text">
                      {activeForRender.customer}
                    </div>
                    <span className="text-body-small text-text-subtlest">
                      {activeForRender.id} · {activeForRender.callId} ·{" "}
                      {formatDateTime(activeForRender.occurredAt)} · {activeForRender.handler}
                    </span>
                    <button
                      onClick={markReviewed}
                      className="ml-auto inline-flex items-center gap-050 rounded-medium border border-border px-100 py-050 text-body-small text-text hover:bg-background-brand-subtlest"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      {active?.reviewed ? "Reviewed" : "Mark reviewed"}
                    </button>
                  </div>
                  <div className="mt-100 flex items-center gap-150">
                    <span className="text-body-small text-text-subtlest">Detectors:</span>
                    <PiiLegend active={activeTypes} onToggle={toggleRule} />
                  </div>
                </div>

                <div className="min-h-0 flex-1 space-y-200 overflow-y-auto px-250 py-200">
                  <AudioBeepTimeline record={activeForRender} onToggleSegment={toggleSegment} />
                  <div className="rounded-large border border-border bg-surface p-200">
                    <div className="mb-150 flex items-center justify-between">
                      <div className="text-body font-semibold text-text">Transcript preview</div>
                      <div className="text-body-small text-text-subtlest">
                        Click any mask to toggle ·{" "}
                        {activeForRender.findings.filter((f) => f.accepted).length} of{" "}
                        {activeForRender.findings.length} applied
                      </div>
                    </div>
                    <TranscriptRedactor record={activeForRender} onToggleFinding={toggleFinding} />
                  </div>
                </div>
              </>
            ) : (
              <div className="grid flex-1 place-items-center text-body text-text-subtlest">
                Select a record to preview PII detection
              </div>
            )}
          </section>

          <aside className="hidden h-full min-h-0 w-[21.25rem] shrink-0 flex-col gap-150 overflow-y-auto border-l border-border bg-surface p-150 xl:flex">
            <div className="flex items-center gap-100 px-025">
              <span className="text-body-small font-semibold text-text-subtlest">Export</span>
            </div>
            <ExportConfigPanel
              selectedCount={selected.size}
              pendingReview={pendingReviewInSelection}
              format={format}
              scope={scope}
              watermark={watermark}
              accessRole={accessRole}
              onFormat={setFormat}
              onScope={setScope}
              onWatermark={setWatermark}
              onAccessRole={setAccessRole}
              onGenerate={generateExport}
            />
            <ExportAuditLog jobs={exports} onDownload={download} onRetry={retry} />
          </aside>
        </div>
      </div>

      <RulesSheet
        open={rulesOpen}
        onOpenChange={setRulesOpen}
        rules={rules}
        onChange={(next) => {
          void (async () => {
            try {
              for (const t of ENTITY_TYPES) {
                if (next[t].enabled !== rules[t].enabled) {
                  await patchRedactionRuleEnabled(t, next[t].enabled);
                }
              }
            } catch (err) {
              toast.error("Could not update rules", {
                description: err instanceof Error ? err.message : String(err),
              });
            } finally {
              invalidateRules();
            }
          })();
        }}
      />
    </AppShell>
  );
}
