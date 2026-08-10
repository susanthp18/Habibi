import { useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import type { AuditEntry } from "@/data/routing-seed";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";

const ACTION_COLOR: Record<string, LozengeTone> = {
  created: "success",
  edited: "information",
  toggled: "warning",
  reordered: "discovery",
  deleted: "danger",
  duplicated: "neutral",
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
      <div className="flex shrink-0 items-center gap-100 border-b border-border bg-surface px-150 py-100">
        <Input placeholder="Search rule or change…" className="h-400 flex-1 text-body-small" value={q} onChange={e => setQ(e.target.value)} />
        <Select value={author} onValueChange={setAuthor}>
          <SelectTrigger className="h-400 w-[8.75rem] text-body-small"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All authors</SelectItem>
            {authors.map(a => <SelectItem key={a} value={a}>{a}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-150">
        <ul className="space-y-100">
          {rows.map(e => (
            <li key={e.id} className="rounded-large border border-border bg-surface p-150">
              <div className="flex items-center gap-100">
                <Lozenge tone={ACTION_COLOR[e.action]}>{e.action}</Lozenge>
                <span className="flex-1 truncate text-body-small font-medium text-text">{e.ruleName}</span>
                <span className="text-body-small text-text-subtlest">{new Date(e.at).toLocaleString()}</span>
              </div>
              <div className="mt-050 text-body-small text-text-subtle">{e.summary}</div>
              <div className="mt-025 text-body-small text-text-subtlest">by {e.author}</div>
            </li>
          ))}
          {rows.length === 0 && <li className="p-200 text-center text-body-small text-text-subtlest">No entries.</li>}
        </ul>
      </div>
    </div>
  );
}
