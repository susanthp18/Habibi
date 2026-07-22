import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Thread, ThreadStatus } from "@/data/inbox-seed";
import { Avatar, channelMeta, chipStatus, slaColor, statusMeta } from "./meta";
import { useMemo, useState } from "react";

type Filter = "all" | ThreadStatus | "mine";

const filters: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "bot", label: "Bot-handled" },
  { key: "needs_human", label: "Needs human" },
  { key: "escalated", label: "Escalated" },
  { key: "mine", label: "Mine" },
];

export function ConversationList({
  threads,
  activeId,
  onSelect,
}: {
  threads: Thread[];
  activeId: string;
  onSelect: (id: string) => void;
}) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  const counts = useMemo(() => {
    const c: Record<Filter, number> = {
      all: threads.length,
      bot: 0,
      needs_human: 0,
      escalated: 0,
      assigned: 0,
      mine: 0,
    };
    for (const t of threads) {
      c[t.status] += 1;
      if (t.isMine) c.mine += 1;
    }
    return c;
  }, [threads]);

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    return threads.filter((t) => {
      if (filter === "mine") {
        if (!t.isMine) return false;
      } else if (filter !== "all" && t.status !== filter) {
        return false;
      }
      if (!term) return true;
      return (
        t.customer.toLowerCase().includes(term) ||
        t.lastPreview.toLowerCase().includes(term) ||
        t.accountId.toLowerCase().includes(term)
      );
    });
  }, [threads, q, filter]);

  return (
    <aside className="flex min-h-0 w-[280px] shrink-0 flex-col border-r border-[var(--border-token)] bg-surface-card xl:w-[320px]">
      <div className="shrink-0 border-b border-[var(--border-token)] px-3 py-3">
        <h2 className="mb-2 text-[15px] font-semibold text-brand-navy">Inbox</h2>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search customer, account, message"
            className="w-full rounded-md border border-[var(--border-token)] bg-surface-sunken py-2 pl-8 pr-2 text-[13px] placeholder:text-text-muted focus:border-brand-primary focus:bg-white focus:outline-none"
          />
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          {filters.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
                filter === f.key
                  ? "border-brand-primary bg-brand-tint text-brand-primary-dark"
                  : "border-[var(--border-token)] bg-white text-text-secondary hover:bg-surface-sunken",
              )}
            >
              {f.label}
              <span
                className={cn(
                  "rounded-full px-1.5 text-[10px] font-semibold",
                  filter === f.key ? "bg-white text-brand-primary" : "bg-surface-sunken text-text-secondary",
                )}
              >
                {counts[f.key]}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {filtered.length === 0 && (
          <div className="p-6 text-center text-[13px] text-text-secondary">
            No conversations match.
          </div>
        )}
        <ul>
          {filtered.map((t, i) => {
            const isActive = t.id === activeId;
            const ChanIcon = channelMeta[t.channel].icon;
            const chip = chipStatus(t);
            return (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => onSelect(t.id)}
                  style={{ animationDelay: `${i * 25}ms` }}
                  className={cn(
                    "animate-fade-up relative flex w-full gap-3 border-b border-[var(--border-token)] px-3 py-3 text-left transition-colors",
                    isActive ? "bg-brand-tint" : "hover:bg-surface-sunken",
                  )}
                >
                  {isActive && (
                    <span className="absolute inset-y-0 left-0 w-[3px] bg-brand-primary" />
                  )}
                  <Avatar name={t.customer} size={40} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <ChanIcon className="h-3.5 w-3.5 shrink-0 text-text-muted" />
                      <span className="truncate text-[13px] font-semibold text-text-primary">
                        {t.customer}
                      </span>
                      <span className="ml-auto whitespace-nowrap text-[11px] text-text-muted">
                        {t.lastTime}
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-1.5">
                      <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", slaColor[t.sla])} />
                      <p className="min-w-0 truncate text-[12px] text-text-secondary">
                        {t.lastFrom === "bot"
                          ? "Bot: "
                          : t.lastFrom === "agent"
                            ? "You: "
                            : ""}
                        {t.lastPreview}
                      </p>
                    </div>
                    <div className="mt-1.5 flex items-center gap-1.5">
                      <span
                        className={cn(
                          "rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                          statusMeta[chip].className,
                        )}
                      >
                        {statusMeta[chip].label}
                      </span>
                      <span className="font-mono text-[10px] text-text-muted">
                        {t.accountId}
                      </span>
                      {t.unread > 0 && (
                        <span className="ml-auto rounded-full bg-brand-primary px-1.5 py-0.5 text-[10px] font-semibold text-white tabular">
                          {t.unread}
                        </span>
                      )}
                    </div>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </aside>
  );
}
