import { useEffect, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { FaqPair, KbDocument } from "@/data/kb-seed";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";

const BASE_INTENTS = [
  "late-fee",
  "emi",
  "foreclosure",
  "documents",
  "statement",
  "topup",
  "cibil",
  "dispute",
  "language",
  "consent",
  "compliance",
  "hardship",
  "restructure",
  "car",
  "home",
  "travel",
  "other",
];

export function FaqEditorSheet({
  open,
  faq,
  documents,
  onClose,
  onSave,
  onDelete,
}: {
  open: boolean;
  faq: FaqPair | null;
  documents: KbDocument[];
  onClose: () => void;
  onSave: (f: Omit<FaqPair, "id" | "updatedAt"> & { id?: string }) => void | Promise<void>;
  onDelete?: (id: string) => void | Promise<void>;
}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [intent, setIntent] = useState("other");
  const [linkedDocId, setLinkedDocId] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const intents = Array.from(new Set([...BASE_INTENTS, faq?.intent].filter(Boolean) as string[]));
  const canDelete = Boolean(faq?.id && onDelete);

  useEffect(() => {
    if (!open) return;
    setQuestion(faq?.question ?? "");
    setAnswer(faq?.answer ?? "");
    setIntent(faq?.intent ?? "other");
    setLinkedDocId(faq?.linkedDocId ?? "");
    setSaving(false);
    setDeleting(false);
    setConfirmDelete(false);
    // Keyed on the FAQ's identity, not the object reference: the list is
    // polled, so an unchanged FAQ arriving as a fresh object wiped whatever the
    // user had typed into the open sheet.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, faq?.id]);

  const save = async () => {
    if (!question.trim() || !answer.trim() || saving || deleting) return;
    setSaving(true);
    try {
      await Promise.resolve(
        onSave({
          id: faq?.id,
          question: question.trim(),
          answer: answer.trim(),
          intent,
          enabled: faq?.enabled ?? true,
          linkedDocId: linkedDocId || undefined,
        }),
      );
    } catch (e) {
      // remove() already surfaced its failures; save() rejected silently, so a
      // failed write looked identical to a successful one.
      toast.error(e instanceof Error ? e.message : "Failed to save FAQ");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!faq?.id || !onDelete || deleting || saving) return;
    setDeleting(true);
    try {
      await Promise.resolve(onDelete(faq.id));
      setConfirmDelete(false);
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete FAQ");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{faq?.id ? "Edit FAQ" : "New FAQ pair"}</SheetTitle>
        </SheetHeader>
        <div className="mt-200 space-y-200 overflow-y-auto pr-050">
          <div>
            <Label>Question</Label>
            <Input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. What are the foreclosure charges?"
            />
          </div>
          <div>
            <Label>Answer</Label>
            <Textarea
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              rows={7}
              placeholder="Concise, factual answer the bot will use as retrieval augment."
            />
          </div>
          <div className="grid grid-cols-2 gap-150">
            <div>
              <Label>Intent</Label>
              <Select value={intent} onValueChange={setIntent}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {intents.map((i) => (
                    <SelectItem key={i} value={i}>{i}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Linked document</Label>
              <Select value={linkedDocId || "none"} onValueChange={(v) => setLinkedDocId(v === "none" ? "" : v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">— None —</SelectItem>
                  {documents.map((d) => (
                    <SelectItem key={d.id} value={d.id}>{d.title}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
        <SheetFooter className="mt-200 flex-row justify-between gap-100 sm:justify-between">
          {canDelete ? (
            <Button
              variant="outline"
              className="border-border-danger/40 text-text-danger hover:bg-background-danger"
              onClick={() => setConfirmDelete(true)}
              disabled={saving || deleting}
            >
              {deleting ? "Deleting…" : "Delete"}
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-100">
            <Button variant="outline" onClick={onClose} disabled={saving || deleting}>
              Cancel
            </Button>
            <Button
              onClick={() => void save()}
              disabled={saving || deleting || !question.trim() || !answer.trim()}
            >
              {faq?.id ? "Save changes" : "Create FAQ"}
            </Button>
          </div>
        </SheetFooter>
        <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete this FAQ pair?</AlertDialogTitle>
              <AlertDialogDescription>
                Linked analytics gaps will keep their question but lose the FAQ link.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
              <AlertDialogAction
                className="bg-background-danger-bold hover:bg-background-danger-bold-pressed"
                disabled={deleting}
                onClick={(e) => {
                  e.preventDefault();
                  void remove();
                }}
              >
                {deleting ? "Deleting…" : "Delete"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </SheetContent>
    </Sheet>
  );
}
