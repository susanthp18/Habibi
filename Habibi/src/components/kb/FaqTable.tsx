import { Switch } from "@/components/ui/switch";
import type { FaqPair } from "@/data/kb-seed";
import { cn, formatKbDate } from "@/lib/utils";
import { Trash2 } from "lucide-react";

export function FaqTable({
  faqs,
  onSelect,
  onToggle,
  onDelete,
  selectedId,
}: {
  faqs: FaqPair[];
  onSelect: (f: FaqPair) => void;
  onToggle: (id: string, enabled: boolean) => void;
  onDelete?: (id: string) => void;
  selectedId?: string | null;
}) {
  if (faqs.length === 0) {
    return (
      <div className="flex min-h-[180px] flex-col items-center justify-center rounded-lg border border-dashed border-[var(--border-token)] bg-surface-card px-6 py-10 text-center">
        <p className="text-[13px] font-medium text-brand-navy">No FAQ pairs</p>
        <p className="mt-1 text-[12px] text-text-muted">
          Add an FAQ or sync from source_db to load product Q&amp;A.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border-token)] bg-surface-card">
      <table className="w-full text-[13px]">
        <thead className="bg-surface-sunken text-[11px] font-medium uppercase tracking-wide text-text-muted">
          <tr>
            <th className="px-3 py-2 text-left">Question</th>
            <th className="px-3 py-2 text-left">Answer preview</th>
            <th className="px-3 py-2 text-left">Intent</th>
            <th className="px-3 py-2 text-left">Updated</th>
            <th className="px-3 py-2 text-center">Enabled</th>
            <th className="px-2 py-2" />
          </tr>
        </thead>
        <tbody>
          {faqs.map((f) => (
            <tr
              key={f.id}
              onClick={() => onSelect(f)}
              className={cn(
                "cursor-pointer border-t border-[var(--border-token)] hover:bg-surface-sunken/60",
                selectedId === f.id && "bg-brand-tint/40",
              )}
            >
              <td className="px-3 py-2.5 align-top">
                <div className="max-w-md font-medium text-brand-navy">{f.question}</div>
              </td>
              <td className="px-3 py-2.5 align-top">
                <div className="line-clamp-2 max-w-lg text-[12px] text-text-secondary">
                  {f.answer}
                </div>
              </td>
              <td className="px-3 py-2.5 align-top">
                <span className="rounded-full bg-brand-tint px-2 py-0.5 text-[11px] font-medium text-brand-primary-dark">
                  {f.intent}
                </span>
              </td>
              <td className="px-3 py-2.5 align-top text-[12px] text-text-secondary">
                {formatKbDate(f.updatedAt, { day: "2-digit", month: "short" })}
              </td>
              <td className="px-3 py-2.5 text-center align-top" onClick={(e) => e.stopPropagation()}>
                <Switch checked={f.enabled} onCheckedChange={(v) => onToggle(f.id, v)} />
              </td>
              <td className="px-2 py-2.5 text-right align-top" onClick={(e) => e.stopPropagation()}>
                {onDelete && (
                  <button
                    type="button"
                    onClick={() => onDelete(f.id)}
                    className="rounded-md p-1.5 text-text-muted hover:bg-red-50 hover:text-red-700"
                    aria-label="Delete FAQ"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
