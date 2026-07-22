import { Send, RotateCw, ArrowRightLeft, X, Mail, MessageCircle, Smartphone } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { DocChannel } from "@/data/documents-seed";

interface Props {
  count: number;
  onGenerate: () => void;
  onResend: () => void;
  onReassignChannel: (c: DocChannel) => void;
  onClear: () => void;
}

export function BulkActionBar({ count, onGenerate, onResend, onReassignChannel, onClear }: Props) {
  return (
    <div className="shrink-0 flex items-center gap-2 rounded-lg border border-brand-primary/40 bg-brand-tint px-2.5 py-1.5">
      <div className="text-[12px] font-semibold text-brand-primary-dark">{count} selected</div>
      <div className="flex-1" />
      <Button size="sm" className="h-7 text-[11px]" onClick={onGenerate}>
        <Send className="mr-1 h-3 w-3" /> Generate & send
      </Button>
      <Button size="sm" variant="outline" className="h-7 text-[11px]" onClick={onResend}>
        <RotateCw className="mr-1 h-3 w-3" /> Resend
      </Button>
      <div className="flex items-center gap-1 rounded-md border border-[var(--border-token)] bg-surface-card px-1.5 py-1">
        <ArrowRightLeft className="h-3 w-3 text-text-muted" />
        <button
          onClick={() => onReassignChannel("whatsapp")}
          className="rounded p-0.5 hover:bg-surface-sunken"
          title="Switch to WhatsApp"
        >
          <MessageCircle className="h-3.5 w-3.5 text-emerald-600" />
        </button>
        <button onClick={() => onReassignChannel("email")} className="rounded p-0.5 hover:bg-surface-sunken" title="Switch to Email">
          <Mail className="h-3.5 w-3.5 text-brand-primary" />
        </button>
        <button onClick={() => onReassignChannel("sms")} className="rounded p-0.5 hover:bg-surface-sunken" title="Switch to SMS">
          <Smartphone className="h-3.5 w-3.5 text-amber-600" />
        </button>
      </div>
      <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClear} aria-label="Clear selection">
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
