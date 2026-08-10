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
      <aside className="flex h-full w-full max-w-[37.5rem] flex-col bg-surface shadow-overlay">
        {/* Header */}
        <div className="shrink-0 border-b border-border px-200 py-150">
          <div className="flex items-start justify-between gap-100">
            <div className="min-w-0">
              <div className="flex items-center gap-100">
                <Link
                  to="/customers/$customerId"
                  params={{ customerId: d.customerId }}
                  className="truncate text-[0.875rem] font-semibold text-text hover:underline"
                >
                  {d.customerName}
                </Link>
                <span className="text-body-small text-text-subtlest">#{d.accountTail} · {d.id}</span>
              </div>
              <div className="mt-050 flex flex-wrap items-center gap-075">
                <span className="rounded bg-surface-sunken px-075 py-025 text-body-small font-medium text-text-subtle">
                  {DOC_TYPE_LABELS[d.docType]}
                </span>
                {d.period && (
                  <span className="rounded bg-background-brand-subtlest px-075 py-025 text-body-small font-semibold text-text-brand">
                    {d.period}
                  </span>
                )}
                <span className={cn("rounded px-075 py-025 text-body-small font-medium",
                  d.status === "sent" ? "bg-background-success-subtler text-text-success-bolder" :
                  d.status === "failed" ? "bg-background-danger-subtler text-text-danger-bolder" :
                  d.status === "generating" ? "bg-background-warning-subtler text-text-warning-bolder" :
                  "bg-background-brand-subtlest text-text-brand",
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
        <div className="shrink-0 border-b border-border bg-surface-sunken/60 px-200 py-100">
          <div className="flex flex-wrap items-center gap-100 text-body-small text-text-subtle">
            {d.requestedVia.startsWith("bot") ? <Bot className="h-3.5 w-3.5" /> : <User className="h-3.5 w-3.5" />}
            <SIcon className="h-3.5 w-3.5" />
            <span>{VIA_LABELS[d.requestedVia]}</span>
            <span>·</span>
            <span>{fmtDate(d.requestedAt, { dateStyle: "medium", timeStyle: "short" })}</span>
            <Link to="/inbox" className="ml-auto inline-flex items-center gap-050 text-text-brand hover:underline">
              Open conversation <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
        </div>

        {/* Tabs */}
        <div className="shrink-0 border-b border-border px-100">
          <div className="flex gap-050">
            {(["details", "preview", "audit"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={cn(
                  "border-b-2 px-150 py-100 text-body-small capitalize",
                  tab === t
                    ? "border-border-brand text-text-brand font-semibold"
                    : "border-transparent text-text-subtle hover:text-text",
                )}
              >
                {t === "audit" ? "Audit" : t === "preview" ? "Template preview" : "Details"}
                {t === "audit" && (
                  <span className="ml-050 rounded bg-surface-sunken px-050 text-body-small text-text-subtlest">{d.events.length}</span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto px-200 py-150">
          {tab === "details" && (
            <div className="space-y-150">
              <Field label="Assignee">
                <select
                  value={d.assignee}
                  disabled={busy}
                  onChange={(e) => {
                    void run(() => assignDocument(d, e.target.value), `Assigned to ${e.target.value}`);
                  }}
                  className="h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small"
                >
                  {assigneeOptions.map((a) => (
                    <option key={a} value={a}>{a}</option>
                  ))}
                </select>
              </Field>

              <Field label="Delivery channel">
                <div className="flex gap-075">
                  {(Object.keys(CHANNEL_LABELS) as DocChannel[]).map((c) => (
                    <button
                      key={c}
                      disabled={busy}
                      onClick={() => {
                        void run(() => reassignChannel(d, c), `Channel → ${CHANNEL_LABELS[c]}`);
                      }}
                      className={cn(
                        "flex-1 rounded-medium border px-100 py-075 text-body-small",
                        d.deliveryChannel === c
                          ? "border-border-brand bg-background-brand-subtlest text-text-brand font-semibold"
                          : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
                      )}
                    >
                      {CHANNEL_LABELS[c]}
                    </button>
                  ))}
                </div>
                <div className="mt-050 text-body-small text-text-subtlest">Delivering to: {d.deliveryTarget}</div>
              </Field>

              <Field label="Template">
                <select
                  value={d.templateId}
                  disabled={busy}
                  onChange={(e) => {
                    void run(() => changeTemplate(d, e.target.value), "Template updated");
                  }}
                  className="h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small"
                >
                  {templates.map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
                <div className="mt-050 text-body-small text-text-subtlest">{tpl.description}</div>
              </Field>

              <div className="grid grid-cols-2 gap-150">
                <Field label="Attempts"><div className="text-body text-text">{d.attempts}</div></Field>
                <Field label="File size"><div className="text-body text-text">{d.sizeKb ? `${d.sizeKb} KB` : "—"}</div></Field>
                <Field label="Requested"><div className="text-body text-text">{fmtDate(d.requestedAt, { dateStyle: "medium", timeStyle: "short" })}</div></Field>
                <Field label="Delivered"><div className="text-body text-text">{d.sentAt ? fmtDate(d.sentAt, { dateStyle: "medium", timeStyle: "short" }) : "—"}</div></Field>
              </div>

              {d.status === "failed" && d.failedReason && (
                <div className="rounded-medium border border-border-danger-subtle bg-background-danger-subtler/60 p-150 text-body-small text-text-danger-bolder">
                  <div className="text-body-small font-semibold">Last failure</div>
                  <div>{d.failedReason}</div>
                </div>
              )}
            </div>
          )}

          {tab === "preview" && (
            <div className="space-y-100">
              <div className="flex items-center gap-100 text-body-small text-text-subtlest">
                <FileText className="h-3.5 w-3.5" />
                <span>{tpl.name}</span>
              </div>
              <div className="rounded-medium border border-border bg-surface p-200">
                {renderPreview(tpl, d).map((line, i) => (
                  <p key={i} className={cn("text-[0.75rem] leading-relaxed text-text", i === 0 && "font-semibold text-[0.875rem]")}>
                    {line}
                  </p>
                ))}
                <div className="mt-200 border-t border-dashed border-border pt-100 text-body-small text-text-subtlest">
                  Preview only · full document generated on demand.
                </div>
              </div>
            </div>
          )}

          {tab === "audit" && (
            <ol className="relative space-y-150 border-l border-border pl-200">
              {[...d.events].reverse().map((e, i) => (
                <li key={i} className="relative">
                  <span
                    className={cn(
                      "absolute -left-250 top-1 h-2.5 w-2.5 rounded-full ring-2 ring-surface",
                      e.tone === "success" ? "bg-background-success-bold" :
                      e.tone === "warn" ? "bg-background-warning-bold" :
                      e.tone === "danger" ? "bg-background-danger-bold" :
                      "bg-background-brand-bold",
                    )}
                  />
                  <div className="text-body-small text-text">{e.label}</div>
                  <div className="text-body-small text-text-subtlest">
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
          <div className="shrink-0 border-t border-border px-200 py-100">
            <div className="flex items-center justify-end gap-100">
              {d.status === "failed" && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-400 text-body-small"
                  disabled={busy}
                  onClick={() => {
                    void run(() => retryDocument(d), "Retry queued");
                  }}
                >
                  <RotateCw className="mr-050 h-3.5 w-3.5" /> Retry
                </Button>
              )}
              {(d.status === "requested" || d.status === "failed") && (
                <Button size="sm" className="h-400 text-body-small" disabled={busy} onClick={() => onGenerate(d)}>
                  <Send className="mr-050 h-3.5 w-3.5" /> Generate & send
                </Button>
              )}
              {d.status === "generating" && (
                <div className="text-body-small text-text-warning-bolder">Generation in flight…</div>
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
      <div className="text-body-small font-semibold text-text-subtlest">{label}</div>
      <div className="mt-050">{children}</div>
    </div>
  );
}
