import { Switch } from "@/components/ui/switch";
import type { FaqPair } from "@/data/kb-seed";
import { cn } from "@/lib/utils";

export function FaqTable({
  faqs,
  onSelect,
  onToggle,
  selectedId,
}: {
  faqs: FaqPair[];
  onSelect: (f: FaqPair) => void;
  onToggle: (id: string, enabled: boolean) => void;
  selectedId?: string | null;
}) {
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
                {new Date(f.updatedAt).toLocaleDateString(undefined, {
                  day: "2-digit",
                  month: "short",
                })}
              </td>
              <td className="px-3 py-2.5 text-center align-top" onClick={(e) => e.stopPropagation()}>
                <Switch checked={f.enabled} onCheckedChange={(v) => onToggle(f.id, v)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
