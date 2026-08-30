import { useState, type ReactNode } from "react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { TYPE_LABELS, type DisputeType } from "@/data/disputes-seed";

type Kind = "ptp" | "dispute" | "statement" | "call" | null;

type SubmitPayloads = {
  ptp: { amount: number; date: string; channel: string; notes: string };
  dispute: { type: DisputeType; amount: number; notes: string };
  statement: { docType: string; delivery: "email" | "whatsapp" };
  call: { disposition: string; notes: string };
};

type Props = {
  kind: Kind;
  onOpenChange: (open: boolean) => void;
  onSubmit: (kind: Exclude<Kind, null>, payload: SubmitPayloads[Exclude<Kind, null>]) => void;
};

export function ActionSheets({ kind, onOpenChange, onSubmit }: Props) {
  return (
    <Sheet open={kind !== null} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md">
        {kind === "ptp" && (
          <PtpForm onCancel={() => onOpenChange(false)} onSubmit={(p) => onSubmit("ptp", p)} />
        )}
        {kind === "dispute" && (
          <DisputeForm
            onCancel={() => onOpenChange(false)}
            onSubmit={(p) => onSubmit("dispute", p)}
          />
        )}
        {kind === "statement" && (
          <StatementForm
            onCancel={() => onOpenChange(false)}
            onSubmit={(p) => onSubmit("statement", p)}
          />
        )}
        {kind === "call" && (
          <CallForm onCancel={() => onOpenChange(false)} onSubmit={(p) => onSubmit("call", p)} />
        )}
      </SheetContent>
    </Sheet>
  );
}

function FormShell({
  title,
  desc,
  children,
  footer,
}: {
  title: string;
  desc: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <>
      <SheetHeader>
        <SheetTitle>{title}</SheetTitle>
        <SheetDescription>{desc}</SheetDescription>
      </SheetHeader>
      <div className="my-200 space-y-150">{children}</div>
      <SheetFooter>{footer}</SheetFooter>
    </>
  );
}

function PtpForm({
  onCancel,
  onSubmit,
}: {
  onCancel: () => void;
  onSubmit: (p: SubmitPayloads["ptp"]) => void;
}) {
  const [amount, setAmount] = useState("1000");
  const today = new Date(Date.now() + 3 * 86400000).toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const [channel, setChannel] = useState("voice");
  const [notes, setNotes] = useState("");
  return (
    <FormShell
      title="Create Promise-to-Pay"
      desc="Capture what the customer committed. It will show up in the PTP pipeline."
      footer={
        <div className="flex w-full justify-end gap-100">
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            onClick={() => onSubmit({ amount: Number(amount), date, channel, notes })}
            disabled={!amount || !date}
          >
            Save PTP
          </Button>
        </div>
      }
    >
      <Field label="Promised amount (₹)">
        <Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} />
      </Field>
      <Field label="Promised date">
        <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </Field>
      <Field label="Captured via">
        <Select value={channel} onValueChange={setChannel}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="voice">Voice call</SelectItem>
            <SelectItem value="whatsapp">WhatsApp</SelectItem>
            <SelectItem value="chat">Web chat</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      <Field label="Notes">
        <Textarea
          rows={3}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Optional context…"
        />
      </Field>
    </FormShell>
  );
}

function DisputeForm({
  onCancel,
  onSubmit,
}: {
  onCancel: () => void;
  onSubmit: (p: SubmitPayloads["dispute"]) => void;
}) {
  const [type, setType] = useState<DisputeType>("paid_already");
  const [amount, setAmount] = useState("0");
  const [notes, setNotes] = useState("");
  return (
    <FormShell
      title="Raise dispute"
      desc="Log a new dispute for review. It will enter the Disputes queue."
      footer={
        <div className="flex w-full justify-end gap-100">
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            onClick={() => onSubmit({ type, amount: Number(amount), notes })}
            disabled={!type}
          >
            Raise dispute
          </Button>
        </div>
      }
    >
      <Field label="Dispute type">
        {/* Canonical dispute_type values — the same vocabulary the Disputes queue
            and the DB CHECK use, so the chosen type survives the round-trip. */}
        <Select value={type} onValueChange={(v) => setType(v as DisputeType)}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(TYPE_LABELS) as DisputeType[]).map((key) => (
              <SelectItem key={key} value={key}>
                {TYPE_LABELS[key]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field label="Amount in dispute (₹)">
        <Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} />
      </Field>
      <Field label="Customer statement">
        <Textarea
          rows={4}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Quote or paraphrase what the customer said…"
        />
      </Field>
    </FormShell>
  );
}

function StatementForm({
  onCancel,
  onSubmit,
}: {
  onCancel: () => void;
  onSubmit: (p: SubmitPayloads["statement"]) => void;
}) {
  const [docType, setDocType] = useState("6-month account statement");
  const [delivery, setDelivery] = useState<"email" | "whatsapp">("email");
  return (
    <FormShell
      title="Send document"
      desc="Generate a statement or letter and send it to the customer."
      footer={
        <div className="flex w-full justify-end gap-100">
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={() => onSubmit({ docType, delivery })}>Send</Button>
        </div>
      }
    >
      <Field label="Document">
        <Select value={docType} onValueChange={setDocType}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="6-month account statement">6-month account statement</SelectItem>
            <SelectItem value="No-dues certificate">No-dues certificate</SelectItem>
            <SelectItem value="Payment schedule">Payment schedule</SelectItem>
            <SelectItem value="Restructuring quote">Restructuring quote</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      <Field label="Delivery channel">
        <Select value={delivery} onValueChange={(v) => setDelivery(v as "email" | "whatsapp")}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="email">Email</SelectItem>
            <SelectItem value="whatsapp">WhatsApp</SelectItem>
          </SelectContent>
        </Select>
      </Field>
    </FormShell>
  );
}

function CallForm({
  onCancel,
  onSubmit,
}: {
  onCancel: () => void;
  onSubmit: (p: SubmitPayloads["call"]) => void;
}) {
  const [disposition, setDisposition] = useState("Query resolved");
  const [notes, setNotes] = useState("");
  return (
    <FormShell
      title="Log call"
      desc="Manually log an outbound / offline call for this customer."
      footer={
        <div className="flex w-full justify-end gap-100">
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={() => onSubmit({ disposition, notes })}>Log call</Button>
        </div>
      }
    >
      <Field label="Disposition">
        <Select value={disposition} onValueChange={setDisposition}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="Query resolved">Query resolved</SelectItem>
            <SelectItem value="PTP captured">PTP captured</SelectItem>
            <SelectItem value="No answer">No answer</SelectItem>
            <SelectItem value="Escalated">Escalated</SelectItem>
            <SelectItem value="Wrong number">Wrong number</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      <Field label="Notes">
        <Textarea
          rows={4}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="What did you discuss?"
        />
      </Field>
    </FormShell>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-075">
      <Label className="text-xs font-medium text-text-subtle">{label}</Label>
      {children}
    </div>
  );
}
