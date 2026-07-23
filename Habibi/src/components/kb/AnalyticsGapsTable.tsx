import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import type { KbGap } from "@/api/kb";
import type { KbDocument } from "@/data/kb-seed";
import { cn, formatKbDate } from "@/lib/utils";
import { CheckCircle2, MessageSquarePlus, BookOpen, Link2 } from "lucide-react";

export function AnalyticsGapsTable({
  gaps,
  documents,
  faqs,
  onCreateFaq,
  onAttachDoc,
  onUploadForGap,
}: {
  gaps: KbGap[];
  documents: KbDocument[];
  faqs?: Array<{ id: string; question: string }>;
  onCreateFaq: (gap: KbGap) => void;
  onAttachDoc: (gapId: string, documentId: string) => void | Promise<void>;
  onUploadForGap: (gap: KbGap) => void;
}) {
  const [showResolved, setShowResolved] = useState(false);
  const [attachGap, setAttachGap] = useState<KbGap | null>(null);
  const [pickedDocId, setPickedDocId] = useState("");
  const [linking, setLinking] = useState(false);

  const docById = useMemo(() => {
    const map = new Map<string, KbDocument>();
    for (const d of documents) map.set(d.id, d);
    return map;
  }, [documents]);

  const faqById = useMemo(() => {
    const map = new Map<string, string>();
    for (const f of faqs ?? []) map.set(f.id, f.question);
    return map;
  }, [faqs]);

  const rows = useMemo(() => {
    return gaps.filter((q) => (showResolved ? true : !q.resolved));
  }, [gaps, showResolved]);

  const confirmAttach = async () => {
    if (!attachGap || !pickedDocId || linking) return;
    setLinking(true);
    try {
      await Promise.resolve(onAttachDoc(attachGap.id, pickedDocId));
      setAttachGap(null);
      setPickedDocId("");
    } finally {
      setLinking(false);
    }
  };

  return (
    <>
      <div className="overflow-hidden rounded-lg border border-[var(--border-token)] bg-surface-card">
        <div className="flex items-center justify-between border-b border-[var(--border-token)] px-3 py-2">
          <div className="text-[13px] font-medium text-brand-navy">
            Coverage gaps <span className="text-text-muted">(from Bot Analytics)</span>
          </div>
          <label className="flex items-center gap-2 text-[12px] text-text-secondary">
            <Switch checked={showResolved} onCheckedChange={setShowResolved} />
            Show resolved
          </label>
        </div>
        {rows.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 p-10 text-center">
            <CheckCircle2 className="h-8 w-8 text-emerald-500" />
            <div className="text-[13px] font-medium text-brand-navy">
              No open gaps — the bot is fully covered.
            </div>
          </div>
        ) : (
          <table className="w-full text-[13px]">
            <thead className="bg-surface-sunken text-[11px] font-medium uppercase tracking-wide text-text-muted">
              <tr>
                <th className="px-3 py-2 text-left">Unanswered question</th>
                <th className="px-3 py-2 text-right">Hits</th>
                <th className="px-3 py-2 text-left">Top intent</th>
                <th className="px-3 py-2 text-left">Linked</th>
                <th className="px-3 py-2 text-left">Last seen</th>
                <th className="px-3 py-2 text-left">Suggestion</th>
                <th className="px-3 py-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((q) => {
                const done = q.resolved;
                const linkedDoc = q.linkedDocumentId
                  ? docById.get(q.linkedDocumentId)
                  : undefined;
                const linkedFaqQ = q.linkedFaqId ? faqById.get(q.linkedFaqId) : undefined;
                return (
                  <tr
                    key={q.id}
                    className={cn(
                      "border-t border-[var(--border-token)]",
                      done && "opacity-60",
                    )}
                  >
                    <td className="px-3 py-2.5 text-text-primary">{q.text}</td>
                    <td className="px-3 py-2.5 text-right font-mono tabular-nums text-text-secondary">
                      {q.hits}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className="rounded-full bg-brand-tint px-2 py-0.5 text-[11px] font-medium text-brand-primary-dark">
                        {q.topIntent}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex max-w-[200px] flex-col gap-1">
                        {(q.hasFaq || q.linkedFaqId) && (
                          <span
                            className="inline-flex items-center gap-1 truncate rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-800"
                            title={linkedFaqQ || q.linkedFaqId || "FAQ linked"}
                          >
                            <Link2 className="h-3 w-3 shrink-0" />
                            FAQ{linkedFaqQ ? `: ${linkedFaqQ.slice(0, 36)}${linkedFaqQ.length > 36 ? "…" : ""}` : ""}
                          </span>
                        )}
                        {(q.hasKbDoc || q.linkedDocumentId) && (
                          <span
                            className="inline-flex items-center gap-1 truncate rounded-full border border-brand-primary/30 bg-brand-tint px-2 py-0.5 text-[10px] font-medium text-brand-primary-dark"
                            title={linkedDoc?.title || q.linkedDocumentId || "Document linked"}
                          >
                            <BookOpen className="h-3 w-3 shrink-0" />
                            {linkedDoc?.title
                              ? linkedDoc.title.length > 28
                                ? `${linkedDoc.title.slice(0, 28)}…`
                                : linkedDoc.title
                              : "Doc linked"}
                          </span>
                        )}
                        {!q.hasFaq && !q.linkedFaqId && !q.hasKbDoc && !q.linkedDocumentId && (
                          <span className="text-[11px] text-text-muted">—</span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-[12px] text-text-secondary">
                      {formatKbDate(q.lastSeen, { day: "2-digit", month: "short" })}
                    </td>
                    <td className="px-3 py-2.5">
                      <span
                        className={cn(
                          "rounded-full border px-2 py-0.5 text-[11px] font-medium",
                          q.suggestedFix === "kb"
                            ? "border-brand-primary/30 bg-brand-tint text-brand-primary-dark"
                            : q.suggestedFix === "prompt"
                              ? "border-amber-200 bg-amber-50 text-amber-700"
                              : "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700",
                        )}
                      >
                        {q.suggestedFix === "kb"
                          ? "Add to KB"
                          : q.suggestedFix === "prompt"
                            ? "Fix prompt"
                            : "KB + Prompt"}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      {done ? (
                        <span className="inline-flex items-center gap-1 text-[11px] text-emerald-700">
                          <CheckCircle2 className="h-3.5 w-3.5" /> Resolved
                        </span>
                      ) : (
                        <div className="flex justify-end gap-1">
                          <Button size="sm" variant="outline" onClick={() => onCreateFaq(q)}>
                            <MessageSquarePlus className="mr-1 h-3 w-3" /> Create FAQ
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setAttachGap(q)}>
                            <BookOpen className="mr-1 h-3 w-3" /> Attach doc
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <Dialog
        open={Boolean(attachGap)}
        onOpenChange={(o) => {
          if (!o) {
            setAttachGap(null);
            setPickedDocId("");
          }
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Attach document to gap</DialogTitle>
          </DialogHeader>
          <p className="text-[12px] text-text-muted line-clamp-3">{attachGap?.text}</p>
          <div className="space-y-2">
            <Label>Existing KB document</Label>
            <Select value={pickedDocId || undefined} onValueChange={setPickedDocId}>
              <SelectTrigger>
                <SelectValue placeholder="Select a document…" />
              </SelectTrigger>
              <SelectContent>
                {documents.map((d) => (
                  <SelectItem key={d.id} value={d.id}>
                    {d.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="outline"
              onClick={() => {
                if (attachGap) onUploadForGap(attachGap);
                setAttachGap(null);
              }}
            >
              Upload new…
            </Button>
            <Button onClick={() => void confirmAttach()} disabled={!pickedDocId || linking}>
              Link document
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
