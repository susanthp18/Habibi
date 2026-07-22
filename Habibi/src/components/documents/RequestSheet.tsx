import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";
import { X, Send, RotateCw, ExternalLink, Bot, User, Mic, MessageSquare, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  CHANNEL_LABELS,
  DOC_TYPE_LABELS,
  TEMPLATES,
  VIA_LABELS,
  agingInfo,
  fmtDate,
  renderPreview,
  templatesFor,
  type DocChannel,
  type DocRequest,
} from "@/data/documents-seed";
import {
  UNASSIGNED,
  assignDocument,
  changeTemplate,
  reassignChannel,
  retryDocument,
} from "@/api/documents";

interface Props {
  d: DocRequest;
  onClose: () => void;
  onGenerate: (d: DocRequest) => void;
  onMutate: () => void;
  /** Live: real people from /staff. Mock: derived from seed rows. */
  assignees: string[];
}

type Tab = "details" | "preview" | "audit";

export function RequestSheet({ d, onClose, onGenerate, onMutate, assignees }: Props) {
  const [tab, setTab] = useState<Tab>("details");
  const [busy, setBusy] = useState(false);
  const tpl = TEMPLATES.find((t) => t.id === d.templateId) ?? TEMPLATES[0];
  const aging = agingInfo(d);
  const closed = d.status === "sent";
  const templates = templatesFor(d.docType);
  const assigneeOptions = [...new Set([UNASSIGNED, ...assignees])];

  const SIcon = d.requestedVia === "bot_voice" ? Mic : d.requestedVia === "bot_chat" ? MessageSquare : User;

  const run = async (fn: () => Promise<void>, okMsg: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      toast.success(okMsg);
      onMutate();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex">
      <button aria-label="Close overlay" onClick={onClose} className="flex-1 bg-black/30" />
      <aside className="flex h-full w-full max-w-[560px] flex-col bg-surface-card shadow-xl">
        {/* Header */}
        <div className="shrink-0 border-b border-[var(--border-token)] px-4 py-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Link
                  to="/customers/$customerId"
                  params={{ customerId: d.customerId }}
                  className="truncate text-[15px] font-semibold text-brand-navy hover:underline"
                >
                  {d.customerName}
                </Link>
                <span className="text-[11px] text-text-muted">#{d.accountTail} · {d.id}</span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <span className="rounded bg-surface-sunken px-1.5 py-0.5 text-[11px] font-medium text-text-secondary">
                  {DOC_TYPE_LABELS[d.docType]}
                </span>
                {d.period && (
                  <span className="rounded bg-brand-tint px-1.5 py-0.5 text-[11px] font-semibold text-brand-primary-dark">
                    {d.period}
                  </span>
                )}
                <span className={cn("rounded px-1.5 py-0.5 text-[11px] font-medium",
                  d.status === "sent" ? "bg-emerald-100 text-emerald-800" :
                  d.status === "failed" ? "bg-red-100 text-red-700" :
                  d.status === "generating" ? "bg-amber-100 text-amber-800" :
                  "bg-brand-tint text-brand-primary-dark",
                )}>
                  {d.status} · {aging.label}
                </span>
              </div>
            </div>
            <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClose} aria-label="Close">
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Captured context */}
        <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-sunken/60 px-4 py-2">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-text-secondary">
            {d.requestedVia.startsWith("bot") ? <Bot className="h-3.5 w-3.5" /> : <User className="h-3.5 w-3.5" />}
            <SIcon className="h-3.5 w-3.5" />
            <span>{VIA_LABELS[d.requestedVia]}</span>
            <span>·</span>
            <span>{fmtDate(d.requestedAt, { dateStyle: "medium", timeStyle: "short" })}</span>
            <Link to="/inbox" className="ml-auto inline-flex items-center gap-1 text-brand-primary hover:underline">
              Open conversation <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
        </div>

        {/* Tabs */}
        <div className="shrink-0 border-b border-[var(--border-token)] px-2">
          <div className="flex gap-1">
            {(["details", "preview", "audit"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={cn(
                  "border-b-2 px-3 py-2 text-[12px] capitalize",
                  tab === t
                    ? "border-brand-primary text-brand-primary-dark font-semibold"
                    : "border-transparent text-text-secondary hover:text-brand-navy",
                )}
              >
                {t === "audit" ? "Audit" : t === "preview" ? "Template preview" : "Details"}
                {t === "audit" && (
                  <span className="ml-1 rounded bg-surface-sunken px-1 text-[10px] text-text-muted">{d.events.length}</span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          {tab === "details" && (
            <div className="space-y-3">
              <Field label="Assignee">
                <select
                  value={d.assignee}
                  disabled={busy}
                  onChange={(e) => {
                    void run(() => assignDocument(d, e.target.value), `Assigned to ${e.target.value}`);
                  }}
                  className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
                >
                  {assigneeOptions.map((a) => (
                    <option key={a} value={a}>{a}</option>
                  ))}
                </select>
              </Field>

              <Field label="Delivery channel">
                <div className="flex gap-1.5">
                  {(Object.keys(CHANNEL_LABELS) as DocChannel[]).map((c) => (
                    <button
                      key={c}
                      disabled={busy}
                      onClick={() => {
                        void run(() => reassignChannel(d, c), `Channel → ${CHANNEL_LABELS[c]}`);
                      }}
                      className={cn(
                        "flex-1 rounded-md border px-2 py-1.5 text-[12px]",
                        d.deliveryChannel === c
                          ? "border-brand-primary bg-brand-tint text-brand-primary-dark font-semibold"
                          : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken",
                      )}
                    >
                      {CHANNEL_LABELS[c]}
                    </button>
                  ))}
                </div>
                <div className="mt-1 text-[10.5px] text-text-muted">Delivering to: {d.deliveryTarget}</div>
              </Field>

              <Field label="Template">
                <select
                  value={d.templateId}
                  disabled={busy}
                  onChange={(e) => {
                    void run(() => changeTemplate(d, e.target.value), "Template updated");
                  }}
                  className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
                >
                  {templates.map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
                <div className="mt-1 text-[11px] text-text-muted">{tpl.description}</div>
              </Field>

              <div className="grid grid-cols-2 gap-3">
                <Field label="Attempts"><div className="text-[13px] text-brand-navy">{d.attempts}</div></Field>
                <Field label="File size"><div className="text-[13px] text-brand-navy">{d.sizeKb ? `${d.sizeKb} KB` : "—"}</div></Field>
                <Field label="Requested"><div className="text-[13px] text-brand-navy">{fmtDate(d.requestedAt, { dateStyle: "medium", timeStyle: "short" })}</div></Field>
                <Field label="Delivered"><div className="text-[13px] text-brand-navy">{d.sentAt ? fmtDate(d.sentAt, { dateStyle: "medium", timeStyle: "short" }) : "—"}</div></Field>
              </div>

              {d.status === "failed" && d.failedReason && (
                <div className="rounded-md border border-red-200 bg-red-50/60 p-2.5 text-[12px] text-red-800">
                  <div className="text-[11px] font-semibold uppercase tracking-wide">Last failure</div>
                  <div>{d.failedReason}</div>
                </div>
              )}
            </div>
          )}

          {tab === "preview" && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-[11px] text-text-muted">
                <FileText className="h-3.5 w-3.5" />
                <span>{tpl.name}</span>
              </div>
              <div className="rounded-md border border-[var(--border-token)] bg-white p-4 shadow-sm">
                {renderPreview(tpl, d).map((line, i) => (
                  <p key={i} className={cn("text-[12.5px] leading-relaxed text-brand-navy", i === 0 && "font-semibold text-[13.5px]")}>
                    {line}
                  </p>
                ))}
                <div className="mt-4 border-t border-dashed border-[var(--border-token)] pt-2 text-[10.5px] text-text-muted">
                  Preview only · full document generated on demand.
                </div>
              </div>
            </div>
          )}

          {tab === "audit" && (
            <ol className="relative space-y-3 border-l border-[var(--border-token)] pl-4">
              {[...d.events].reverse().map((e, i) => (
                <li key={i} className="relative">
                  <span
                    className={cn(
                      "absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full ring-2 ring-surface-card",
                      e.tone === "success" ? "bg-emerald-500" :
                      e.tone === "warn" ? "bg-amber-500" :
                      e.tone === "danger" ? "bg-red-500" :
                      "bg-brand-primary",
                    )}
                  />
                  <div className="text-[12.5px] text-brand-navy">{e.label}</div>
                  <div className="text-[10.5px] text-text-muted">
                    {e.actor ? `${e.actor} · ` : ""}
                    {fmtDate(e.at, { dateStyle: "medium", timeStyle: "short" })}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>

        {/* Footer */}
        {!closed && (
          <div className="shrink-0 border-t border-[var(--border-token)] px-4 py-2">
            <div className="flex items-center justify-end gap-2">
              {d.status === "failed" && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 text-[12px]"
                  disabled={busy}
                  onClick={() => {
                    void run(() => retryDocument(d), "Retry queued");
                  }}
                >
                  <RotateCw className="mr-1 h-3.5 w-3.5" /> Retry
                </Button>
              )}
              {(d.status === "requested" || d.status === "failed") && (
                <Button size="sm" className="h-8 text-[12px]" disabled={busy} onClick={() => onGenerate(d)}>
                  <Send className="mr-1 h-3.5 w-3.5" /> Generate & send
                </Button>
              )}
              {d.status === "generating" && (
                <div className="text-[11.5px] text-amber-700">Generation in flight…</div>
              )}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">{label}</div>
      <div className="mt-1">{children}</div>
    </div>
  );
}
