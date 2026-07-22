import { useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import type { AuditEntry } from "@/data/routing-seed";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const ACTION_COLOR: Record<string, string> = {
  created: "bg-emerald-50 text-emerald-700 border-emerald-200",
  edited: "bg-blue-50 text-blue-700 border-blue-200",
  toggled: "bg-amber-50 text-amber-700 border-amber-200",
  reordered: "bg-violet-50 text-violet-700 border-violet-200",
  deleted: "bg-red-50 text-red-700 border-red-200",
  duplicated: "bg-slate-50 text-slate-700 border-slate-200",
};

export function AuditLog({ entries }: { entries: AuditEntry[] }) {
  const [q, setQ] = useState("");
  const [author, setAuthor] = useState<string>("all");
  const authors = useMemo(() => Array.from(new Set(entries.map(e => e.author))), [entries]);

  const rows = entries
    .filter(e => author === "all" || e.author === author)
    .filter(e => !q || e.ruleName.toLowerCase().includes(q.toLowerCase()) || e.summary.toLowerCase().includes(q.toLowerCase()))
    .slice()
    .reverse();

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-[var(--border-token)] bg-surface-card px-3 py-2">
        <Input placeholder="Search rule or change…" className="h-8 flex-1 text-[12px]" value={q} onChange={e => setQ(e.target.value)} />
        <Select value={author} onValueChange={setAuthor}>
          <SelectTrigger className="h-8 w-[140px] text-[12px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All authors</SelectItem>
            {authors.map(a => <SelectItem key={a} value={a}>{a}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <ul className="space-y-2">
          {rows.map(e => (
            <li key={e.id} className="rounded-lg border border-[var(--border-token)] bg-surface-card p-2.5">
              <div className="flex items-center gap-2">
                <span className={`rounded-full border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${ACTION_COLOR[e.action]}`}>{e.action}</span>
                <span className="flex-1 truncate text-[12px] font-medium text-brand-navy">{e.ruleName}</span>
                <span className="text-[10px] text-text-muted">{new Date(e.at).toLocaleString()}</span>
              </div>
              <div className="mt-1 text-[11px] text-text-secondary">{e.summary}</div>
              <div className="mt-0.5 text-[10px] text-text-muted">by {e.author}</div>
            </li>
          ))}
          {rows.length === 0 && <li className="p-4 text-center text-[12px] text-text-muted">No entries.</li>}
        </ul>
      </div>
    </div>
  );
}
