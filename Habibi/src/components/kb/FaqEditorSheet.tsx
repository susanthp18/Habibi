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
import { documents, type FaqPair } from "@/data/kb-seed";

const INTENTS = ["late-fee", "emi", "foreclosure", "documents", "statement", "topup", "cibil", "dispute", "language", "consent", "compliance", "hardship", "restructure", "other"];

export function FaqEditorSheet({
  open,
  faq,
  onClose,
  onSave,
}: {
  open: boolean;
  faq: FaqPair | null;
  onClose: () => void;
  onSave: (f: FaqPair) => void;
}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [intent, setIntent] = useState("other");
  const [linkedDocId, setLinkedDocId] = useState<string>("");

  useEffect(() => {
    if (!open) return;
    setQuestion(faq?.question ?? "");
    setAnswer(faq?.answer ?? "");
    setIntent(faq?.intent ?? "other");
    setLinkedDocId(faq?.linkedDocId ?? "");
  }, [open, faq]);

  const save = () => {
    if (!question.trim() || !answer.trim()) return;
    onSave({
      id: faq?.id ?? `f-${Date.now()}`,
      question: question.trim(),
      answer: answer.trim(),
      intent,
      enabled: faq?.enabled ?? true,
      updatedAt: new Date().toISOString(),
      linkedDocId: linkedDocId || undefined,
    });
  };

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{faq ? "Edit FAQ" : "New FAQ pair"}</SheetTitle>
        </SheetHeader>
        <div className="mt-4 space-y-4 overflow-y-auto pr-1">
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
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Intent</Label>
              <Select value={intent} onValueChange={setIntent}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {INTENTS.map((i) => (
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
        <SheetFooter className="mt-4">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save}>{faq ? "Save changes" : "Create FAQ"}</Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
