import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
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
import { formatKbDate } from "@/lib/utils";
import { CheckCircle2, MessageSquarePlus, BookOpen, Link2 } from "lucide-react";
import { toast } from "sonner";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";
import { RecordsTag } from "@/components/records/RecordsTag";

export function AnalyticsGapsTable({
  gaps,
  documents,
  faqs,
  onCreateFaq,
  onAttachDoc,
  onUploadForGap,
  showResolved,
  loading = false,
}: {
  gaps: KbGap[];
  documents: KbDocument[];
  faqs?: Array<{ id: string; question: string }>;
  onCreateFaq: (gap: KbGap) => void;
  onAttachDoc: (gapId: string, documentId: string) => void | Promise<void>;
  onUploadForGap: (gap: KbGap) => void;
  showResolved: boolean;
  loading?: boolean;
}) {
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

  const columns = useMemo<RecordsColumn<KbGap>[]>(
    () => [
      {
        id: "question",
        header: "Unanswered question",
        sticky: true,
        sortable: true,
        sortValue: (q) => q.text,
        className: "min-w-[16rem]",
        cell: (q) => (
          <span className="line-clamp-2 text-body text-text" title={q.text}>
            {q.text}
          </span>
        ),
        footer: (visible) => (
          <span className="text-body-small">
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">gaps</span>
          </span>
        ),
      },
      {
        id: "hits",
        header: "Hits",
        sortable: true,
        sortValue: (q) => q.hits,
        align: "right",
        className: "min-w-[4.5rem] whitespace-nowrap",
        cell: (q) => <span className="tabular-nums text-text-subtle">{q.hits}</span>,
        footer: (visible) => (
          <span className="tabular-nums">{visible.reduce((s, q) => s + q.hits, 0)}</span>
        ),
      },
      {
        id: "intent",
        header: "Top intent",
        sortable: true,
        sortValue: (q) => q.topIntent,
        className: "min-w-[8rem] whitespace-nowrap",
        cell: (q) => <RecordsTag name={q.topIntent} />,
      },
      {
        id: "linked",
        header: "Linked",
        className: "min-w-[12rem]",
        cell: (q) => {
          const linkedDoc = q.linkedDocumentId ? docById.get(q.linkedDocumentId) : undefined;
          const linkedFaqQ = q.linkedFaqId ? faqById.get(q.linkedFaqId) : undefined;
          return (
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
          );
        },
      },
      {
        id: "lastSeen",
        header: "Last seen",
        sortable: true,
        sortValue: (q) => q.lastSeen,
        className: "min-w-[7rem] whitespace-nowrap",
        cell: (q) => (
          <span className="text-body-small text-text-subtle">
            {formatKbDate(q.lastSeen, { day: "2-digit", month: "short" })}
          </span>
        ),
      },
      {
        id: "suggestion",
        header: "Suggestion",
        sortable: true,
        sortValue: (q) => q.suggestedFix,
        className: "min-w-[8rem] whitespace-nowrap",
        cell: (q) => (
          <Lozenge
            tone={
              q.suggestedFix === "kb" ? "selected" : q.suggestedFix === "prompt" ? "warning" : "discovery"
            }
          >
            {q.suggestedFix === "kb" ? "Add to KB" : q.suggestedFix === "prompt" ? "Fix prompt" : "KB + Prompt"}
          </Lozenge>
        ),
      },
      {
        id: "action",
        header: "Action",
        align: "right",
        className: "min-w-[16rem] whitespace-nowrap",
        cell: (q) =>
          q.resolved ? (
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
          ),
      },
    ],
    [docById, faqById, onCreateFaq],
  );

  return (
    <>
      {!loading && rows.length === 0 ? (
        <div className="flex h-full flex-col items-center justify-center gap-100 p-500 text-center">
          <CheckCircle2 className="h-400 w-400 text-text-success" />
          <div className="text-body font-medium text-text">
            {showResolved ? "No gaps in this view." : "No open gaps — the bot is fully covered."}
          </div>
        </div>
      ) : (
        <RecordsTable
          rows={rows}
          getRowId={(q) => q.id}
          columns={columns}
          isLoading={loading}
          defaultSort={{ id: "hits", dir: -1 }}
          ariaLabel="Knowledge coverage gaps"
          tableClassName="min-w-[64rem]"
          className="h-full rounded-none border-0"
          emptyMessage="No open gaps — the bot is fully covered."
        />
      )}

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
