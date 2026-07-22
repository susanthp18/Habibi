import { useState } from "react";
import { Eye, EyeOff, Copy, RotateCw, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";

function mask(v: string) {
  if (!v) return "";
  if (v.length <= 8) return "•".repeat(v.length);
  return `${v.slice(0, 3)}${"•".repeat(Math.max(6, v.length - 7))}${v.slice(-4)}`;
}

type Props = {
  value: string;
  onChange: (v: string) => void;
  onRotate?: () => void;
  placeholder?: string;
};

export function MaskedInput({ value, onChange, onRotate, placeholder }: Props) {
  const [revealed, setRevealed] = useState(false);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try { await navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1200); toast.success("Copied to clipboard"); } catch { /* ignore */ }
  };

  return (
    <div className="flex items-center gap-1">
      <Input
        className="h-8 flex-1 font-mono text-[11px]"
        value={revealed ? value : mask(value)}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        readOnly={!revealed}
      />
      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setRevealed(v => !v)} title={revealed ? "Hide" : "Reveal"}>
        {revealed ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
      </Button>
      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={copy} title="Copy">
        {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
      </Button>
      {onRotate && (
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onRotate} title="Rotate">
          <RotateCw className="h-3.5 w-3.5" />
        </Button>
      )}
    </div>
  );
}
