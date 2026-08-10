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
    <div className="shrink-0 flex items-center gap-100 rounded-large border border-border-brand/40 bg-background-brand-subtlest px-150 py-075">
      <div className="text-body-small font-semibold text-text-brand">{count} selected</div>
      <div className="flex-1" />
      <Button size="sm" className="h-7 text-body-small" onClick={onGenerate}>
        <Send className="mr-050 h-3 w-3" /> Generate & send
      </Button>
      <Button size="sm" variant="outline" className="h-7 text-body-small" onClick={onResend}>
        <RotateCw className="mr-050 h-3 w-3" /> Resend
      </Button>
      <div className="flex items-center gap-050 rounded-medium border border-border bg-surface px-075 py-050">
        <ArrowRightLeft className="h-3 w-3 text-text-subtlest" />
        <button
          onClick={() => onReassignChannel("whatsapp")}
          className="rounded p-025 hover:bg-surface-sunken"
          title="Switch to WhatsApp"
        >
          <MessageCircle className="h-3.5 w-3.5 text-text-success" />
        </button>
        <button onClick={() => onReassignChannel("email")} className="rounded p-025 hover:bg-surface-sunken" title="Switch to Email">
          <Mail className="h-3.5 w-3.5 text-text-brand" />
        </button>
        <button onClick={() => onReassignChannel("sms")} className="rounded p-025 hover:bg-surface-sunken" title="Switch to SMS">
          <Smartphone className="h-3.5 w-3.5 text-text-warning" />
        </button>
      </div>
      <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClear} aria-label="Clear selection">
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
