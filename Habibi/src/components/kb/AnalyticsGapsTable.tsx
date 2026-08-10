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
import { Lozenge } from "@/components/ui/lozenge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import type { KbGap } from "@/api/kb";
import type { KbDocument } from "@/data/kb-seed";
import { cn, formatKbDate } from "@/lib/utils";
import { CheckCircle2, MessageSquarePlus, BookOpen, Link2 } from "lucide-react";
import { toast } from "sonner";

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
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to link document");
    } finally {
      setLinking(false);
    }
  };

  return (
    <>
      <div className="overflow-hidden rounded-large border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border px-150 py-100">
          <div className="text-body font-medium text-text">
            Coverage gaps <span className="text-text-subtlest">(from Bot Analytics)</span>
          </div>
          <label className="flex items-center gap-100 text-body-small text-text-subtle">
            <Switch checked={showResolved} onCheckedChange={setShowResolved} />
            Show resolved
          </label>
        </div>
        {rows.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-100 p-500 text-center">
            <CheckCircle2 className="h-400 w-400 text-text-success" />
            <div className="text-body font-medium text-text">
              No open gaps — the bot is fully covered.
            </div>
          </div>
        ) : (
          <table className="w-full text-body">
            <thead className="bg-surface-sunken text-body-small font-medium text-text-subtlest">
              <tr>
                <th className="px-150 py-100 text-left">Unanswered question</th>
                <th className="px-150 py-100 text-right">Hits</th>
                <th className="px-150 py-100 text-left">Top intent</th>
                <th className="px-150 py-100 text-left">Linked</th>
                <th className="px-150 py-100 text-left">Last seen</th>
                <th className="px-150 py-100 text-left">Suggestion</th>
                <th className="px-150 py-100 text-right">Action</th>
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
                      "border-t border-border",
                      done && "opacity-60",
                    )}
                  >
                    <td className="px-150 py-150 text-text">{q.text}</td>
                    <td className="px-150 py-150 text-right font-mono tabular-nums text-text-subtle">
                      {q.hits}
                    </td>
                    <td className="px-150 py-150">
                      <Lozenge tone="selected">
                        {q.topIntent}
                      </Lozenge>
                    </td>
                    <td className="px-150 py-150">
                      <div className="flex max-w-[12.5rem] flex-col gap-050">
                        {(q.hasFaq || q.linkedFaqId) && (
                          <Lozenge
                            tone="success"
                            className="truncate"
                            title={linkedFaqQ || q.linkedFaqId || "FAQ linked"}
                          >
                            <Link2 />
                            FAQ{linkedFaqQ ? `: ${linkedFaqQ.slice(0, 36)}${linkedFaqQ.length > 36 ? "…" : ""}` : ""}
                          </Lozenge>
                        )}
                        {(q.hasKbDoc || q.linkedDocumentId) && (
                          <Lozenge
                            tone="selected"
                            className="truncate"
                            title={linkedDoc?.title || q.linkedDocumentId || "Document linked"}
                          >
                            <BookOpen />
                            {linkedDoc?.title
                              ? linkedDoc.title.length > 28
                                ? `${linkedDoc.title.slice(0, 28)}…`
                                : linkedDoc.title
                              : "Doc linked"}
                          </Lozenge>
                        )}
                        {!q.hasFaq && !q.linkedFaqId && !q.hasKbDoc && !q.linkedDocumentId && (
                          <span className="text-body-small text-text-subtlest">—</span>
                        )}
                      </div>
                    </td>
                    <td className="px-150 py-150 text-body-small text-text-subtle">
                      {formatKbDate(q.lastSeen, { day: "2-digit", month: "short" })}
                    </td>
                    <td className="px-150 py-150">
                      <Lozenge
                        tone={
                          q.suggestedFix === "kb"
                            ? "selected"
                            : q.suggestedFix === "prompt"
                              ? "warning"
                              : "discovery"
                        }
                      >
                        {q.suggestedFix === "kb"
                          ? "Add to KB"
                          : q.suggestedFix === "prompt"
                            ? "Fix prompt"
                            : "KB + Prompt"}
                      </Lozenge>
                    </td>
                    <td className="px-150 py-150 text-right">
                      {done ? (
                        <span className="inline-flex items-center gap-050 text-body-small text-text-success-bolder">
                          <CheckCircle2 className="h-3.5 w-3.5" /> Resolved
                        </span>
                      ) : (
                        <div className="flex justify-end gap-050">
                          <Button size="sm" variant="outline" onClick={() => onCreateFaq(q)}>
                            <MessageSquarePlus className="mr-050 h-3 w-3" /> Create FAQ
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setAttachGap(q)}>
                            <BookOpen className="mr-050 h-3 w-3" /> Attach doc
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
          <p className="text-body-small text-text-subtlest line-clamp-3">{attachGap?.text}</p>
          <div className="space-y-100">
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
          <DialogFooter className="gap-100 sm:gap-0">
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
