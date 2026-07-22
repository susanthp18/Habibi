import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
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
  records as seedRecords,
  initialExports,
  DEFAULT_RULES,
  ENTITY_TYPES,
  defaultFilter,
  filterRecords,
  formatDateTime,
  statsFor,
  type ExportFormat,
  type ExportJob,
  type ExportScope,
  type PiiEntityType,
  type RecordFilter,
  type RedactionRecord,
  type RedactionRules,
} from "@/data/redaction-seed";

export const Route = createFileRoute("/redaction")({
  head: () => ({
    meta: [
      { title: "Redaction & Export Hub — Collections Agent" },
      {
        name: "description",
        content: "Compliance-controlled export workflow — auto-detect PII in transcripts and audio, preview masks, and ship watermarked bundles with an immutable audit log.",
      },
      { property: "og:title", content: "Redaction & Export Hub" },
      {
        property: "og:description",
        content: "Select call records, preview PII detection, tune redaction rules, and export watermarked evidence for regulators.",
      },
    ],
  }),
  component: RedactionPage,
});

function RedactionPage() {
  const [recordState, setRecordState] = useState<RedactionRecord[]>(seedRecords);
  const [exports, setExports] = useState<ExportJob[]>(initialExports);
  const [filter, setFilter] = useState<RecordFilter>(defaultFilter);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(seedRecords[0]?.id ?? null);
  const [rules, setRules] = useState<RedactionRules>(DEFAULT_RULES);
  const [rulesOpen, setRulesOpen] = useState(false);

  // Export config state
  const [format, setFormat] = useState<ExportFormat>("pdf");
  const [scope, setScope] = useState<ExportScope[]>(["transcript", "metadata"]);
  const [watermark, setWatermark] = useState("HDFC-CONFIDENTIAL · Compliance review");
  const [accessRole, setAccessRole] = useState("Compliance Officer");

  const activeTypes = useMemo(
    () => new Set<PiiEntityType>(ENTITY_TYPES.filter((t) => rules[t].enabled)),
    [rules],
  );

  const visibleRecords = useMemo(
    () => filterRecords(recordState, filter),
    [recordState, filter],
  );

  const active = useMemo(
    () => recordState.find((r) => r.id === activeId) ?? null,
    [recordState, activeId],
  );

  // Filter findings against enabled rules for preview
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
    setRecordState((rs) =>
      rs.map((r) =>
        r.id !== activeId
          ? r
          : { ...r, findings: r.findings.map((f) => (f.id === findingId ? { ...f, accepted: !f.accepted } : f)) },
      ),
    );
  };

  const toggleSegment = (findingId: string) => {
    setRecordState((rs) =>
      rs.map((r) =>
        r.id !== activeId
          ? r
          : { ...r, audioSegments: r.audioSegments.map((s) => (s.findingId === findingId ? { ...s, muted: !s.muted } : s)) },
      ),
    );
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
    setRules((r) => ({ ...r, [t]: { ...r[t], enabled: !r[t].enabled } }));
  };

  const markReviewed = () => {
    if (!active) return;
    setRecordState((rs) => rs.map((r) => (r.id === active.id ? { ...r, reviewed: true } : r)));
    toast.success(`Marked ${active.id} as reviewed`);
  };

  const generateExport = () => {
    if (selected.size === 0) return;
    const ids = Array.from(selected);
    const entitiesRedacted = recordState
      .filter((r) => selected.has(r.id))
      .reduce((s, r) => s + r.findings.filter((f) => f.accepted && activeTypes.has(f.type)).length, 0);

    const jobId = `EX-${2050 + exports.length}`;
    const job: ExportJob = {
      id: jobId,
      at: new Date().toISOString(),
      actor: "Meera Joshi",
      actorRole: accessRole,
      recordIds: ids,
      format,
      scope,
      watermark,
      status: "queued",
      downloadCount: 0,
      entitiesRedacted,
    };
    setExports((es) => [job, ...es]);
    toast.info(`${jobId} queued`, { description: `${ids.length} record(s) · ${entitiesRedacted} PII entities` });

    setTimeout(() => {
      setExports((es) => es.map((e) => (e.id === jobId ? { ...e, status: "ready" as const } : e)));
      toast.success(`${jobId} ready to download`, { description: `Watermark: "${watermark}"` });
    }, 1200);

    setSelected(new Set());
  };

  const download = (id: string) => {
    setExports((es) => es.map((e) => (e.id === id ? { ...e, downloadCount: e.downloadCount + 1 } : e)));
    toast.success(`Downloading ${id}`, { description: "Access logged to immutable audit trail." });
  };

  const retry = (id: string) => {
    setExports((es) => es.map((e) => (e.id === id ? { ...e, status: "queued" as const } : e)));
    setTimeout(() => {
      setExports((es) => es.map((e) => (e.id === id ? { ...e, status: "ready" as const } : e)));
      toast.success(`${id} regenerated`);
    }, 1000);
  };

  const pendingReviewInSelection = recordState.filter(
    (r) => selected.has(r.id) && !r.reviewed && r.findings.length > 0,
  ).length;

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <header className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-5 py-3">
          <div className="flex items-center gap-2">
            <h1 className="text-[18px] font-semibold text-brand-navy">Redaction & Export Hub</h1>
            <span className="inline-flex items-center gap-1 rounded-full bg-brand-tint px-2 py-0.5 text-[11px] font-medium text-brand-primary-dark">
              <ShieldCheck className="h-3 w-3" /> Compliance Officer
            </span>
            <button
              onClick={() => setRulesOpen(true)}
              className="ml-auto inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] bg-surface-card px-2.5 py-1 text-[12px] text-text-primary hover:bg-surface-sunken"
            >
              <Settings2 className="h-3.5 w-3.5" /> Redaction rules
            </button>
          </div>
          <p className="text-[12px] text-text-secondary">
            Auto-detect and mask PII in transcripts and audio, then ship watermarked evidence to regulators — every download logged.
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

          {/* Center: PII preview */}
          <section className="flex min-h-0 flex-1 flex-col bg-surface-app">
            {activeForRender ? (
              <>
                <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-5 py-3">
                  <div className="flex items-center gap-2">
                    <div className="text-[14px] font-semibold text-brand-navy">
                      {activeForRender.customer}
                    </div>
                    <span className="text-[11px] text-text-muted">
                      {activeForRender.id} · {activeForRender.callId} · {formatDateTime(activeForRender.occurredAt)} · {activeForRender.handler}
                    </span>
                    <button
                      onClick={markReviewed}
                      className="ml-auto inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2 py-1 text-[12px] text-text-primary hover:bg-brand-tint"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      {active?.reviewed ? "Reviewed" : "Mark reviewed"}
                    </button>
                  </div>
                  <div className="mt-2 flex items-center gap-3">
                    <span className="text-[11px] text-text-muted">Detectors:</span>
                    <PiiLegend active={activeTypes} onToggle={toggleRule} />
                  </div>
                </div>

                <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
                  <AudioBeepTimeline record={activeForRender} onToggleSegment={toggleSegment} />
                  <div className="rounded-lg border border-[var(--border-token)] bg-surface-card p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <div className="text-[13px] font-semibold text-brand-navy">Transcript preview</div>
                      <div className="text-[10px] text-text-muted">
                        Click any mask to toggle · {activeForRender.findings.filter((f) => f.accepted).length} of {activeForRender.findings.length} applied
                      </div>
                    </div>
                    <TranscriptRedactor record={activeForRender} onToggleFinding={toggleFinding} />
                  </div>
                </div>
              </>
            ) : (
              <div className="grid flex-1 place-items-center text-[13px] text-text-muted">
                Select a record to preview PII detection
              </div>
            )}
          </section>

          {/* Right: export + audit */}
          <aside className="hidden h-full min-h-0 w-[340px] shrink-0 flex-col gap-3 overflow-y-auto border-l border-[var(--border-token)] bg-surface-app p-3 xl:flex">
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

      <RulesSheet open={rulesOpen} onOpenChange={setRulesOpen} rules={rules} onChange={setRules} />
    </AppShell>
  );
}
