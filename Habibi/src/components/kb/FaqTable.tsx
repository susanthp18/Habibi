import { Switch } from "@/components/ui/switch";
import type { FaqPair } from "@/data/kb-seed";
import { cn, formatKbDate } from "@/lib/utils";
import { Trash2 } from "lucide-react";
import { Lozenge } from "@/components/ui/lozenge";

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
      <div className="flex min-h-[11.25rem] flex-col items-center justify-center rounded-large border border-dashed border-border bg-surface px-300 py-500 text-center">
        <p className="text-body font-medium text-text">No FAQ pairs</p>
        <p className="mt-050 text-body-small text-text-subtlest">
          Add an FAQ or sync from source_db to load product Q&amp;A.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-large border border-border bg-surface">
      <table className="w-full text-body">
        <thead className="bg-surface-sunken text-body-small font-medium text-text-subtlest">
          <tr>
            <th className="px-150 py-100 text-left">Question</th>
            <th className="px-150 py-100 text-left">Answer preview</th>
            <th className="px-150 py-100 text-left">Intent</th>
            <th className="px-150 py-100 text-left">Updated</th>
            <th className="px-150 py-100 text-center">Enabled</th>
            <th className="px-100 py-100" />
          </tr>
        </thead>
        <tbody>
          {faqs.map((f) => (
            <tr
              key={f.id}
              onClick={() => onSelect(f)}
              className={cn(
                "cursor-pointer border-t border-border hover:bg-surface-sunken/60",
                selectedId === f.id && "bg-background-brand-subtlest/40",
              )}
            >
              <td className="px-150 py-150 align-top">
                <div className="max-w-md font-medium text-text">{f.question}</div>
              </td>
              <td className="px-150 py-150 align-top">
                <div className="line-clamp-2 max-w-lg text-body-small text-text-subtle">
                  {f.answer}
                </div>
              </td>
              <td className="px-150 py-150 align-top">
                <Lozenge tone="selected">
                  {f.intent}
                </Lozenge>
              </td>
              <td className="px-150 py-150 align-top text-body-small text-text-subtle">
                {formatKbDate(f.updatedAt, { day: "2-digit", month: "short" })}
              </td>
              <td className="px-150 py-150 text-center align-top" onClick={(e) => e.stopPropagation()}>
                <Switch checked={f.enabled} onCheckedChange={(v) => onToggle(f.id, v)} />
              </td>
              <td className="px-100 py-150 text-right align-top" onClick={(e) => e.stopPropagation()}>
                {onDelete && (
                  <button
                    type="button"
                    onClick={() => onDelete(f.id)}
                    className="rounded-medium p-075 text-text-subtlest hover:bg-background-danger-subtler hover:text-text-danger-bolder"
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
