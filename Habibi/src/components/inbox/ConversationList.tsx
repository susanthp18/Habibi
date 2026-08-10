import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Thread, ThreadStatus } from "@/data/inbox-seed";
import { Avatar, resolveChannelMeta, chipStatus, slaColor, statusMeta } from "./meta";
import { Badge } from "@/components/ui/badge";
import { useMemo, useState } from "react";
import { Lozenge } from "@/components/ui/lozenge";

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
    <aside className="flex h-full min-h-0 w-full flex-col border-r border-border bg-surface">
      <div className="shrink-0 border-b border-border px-150 py-150">
        <h2 className="mb-100 heading-xsmall text-text">Inbox</h2>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search customer, account, message"
            className="focus-ring h-9 w-full rounded-medium border border-border-input bg-background-input py-075 pl-400 pr-100 text-body transition-colors duration-token-short placeholder:text-text-subtlest hover:bg-background-input-hovered focus:border-border-focused focus:bg-background-input-pressed"
          />
        </div>
        <div className="mt-150 flex flex-wrap gap-075">
          {filters.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cn(
                "focus-ring inline-flex items-center gap-075 rounded-full border px-150 py-050 text-body-small font-medium transition-colors",
                filter === f.key
                  ? "border-border-brand bg-background-brand-subtlest text-text-brand"
                  : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
              )}
            >
              {f.label}
              <Badge
                className={cn(
                  filter === f.key ? "bg-surface text-text-brand" : "bg-surface-sunken text-text-subtle",
                )}
              >
                {counts[f.key]}
              </Badge>
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {filtered.length === 0 && (
          <div className="p-300 text-center text-body text-text-subtle">
            No conversations match.
          </div>
        )}
        <ul>
          {filtered.map((t, i) => {
            const isActive = t.id === activeId;
            const chan = resolveChannelMeta(t.channel);
            const ChanIcon = chan.icon;
            const chip = chipStatus(t);
            return (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => onSelect(t.id)}
                  style={{ animationDelay: `${i * 25}ms` }}
                  className={cn(
                    "focus-ring animate-fade-up relative flex w-full gap-150 border-b border-border px-150 py-150 text-left transition-colors",
                    isActive ? "bg-background-brand-subtlest" : "hover:bg-surface-sunken",
                  )}
                >
                  {isActive && (
                    <span className="absolute inset-y-0 left-0 w-050 bg-background-brand-bold" />
                  )}
                  <Avatar name={t.customer} size={40} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-075">
                      <ChanIcon
                        className="h-3.5 w-3.5 shrink-0 text-text-subtlest"
                        aria-hidden="true"
                      />
                      <span className="truncate text-body font-semibold text-text">
                        {t.customer}
                      </span>
                      <span className="ml-auto whitespace-nowrap text-body-small text-text-subtlest">
                        {t.lastTime}
                      </span>
                    </div>
                    <div className="mt-025 flex items-center gap-075">
                      <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", slaColor[t.sla])} />
                      <p className="min-w-0 truncate text-body-small text-text-subtle">
                        {t.botTyping ? (
                          <span className="font-medium text-text-brand">Bot is typing…</span>
                        ) : (
                          <>
                            {t.lastFrom === "bot"
                              ? "Bot: "
                              : t.lastFrom === "agent"
                                ? "You: "
                                : ""}
                            {t.lastPreview}
                          </>
                        )}
                      </p>
                    </div>
                    <div className="mt-075 flex items-center gap-075">
                      <Lozenge tone={statusMeta[chip].tone}>{statusMeta[chip].label}</Lozenge>
                      <span className="font-mono text-body-small text-text-subtlest">
                        {t.accountId}
                      </span>
                      {t.unread > 0 && (
                        <Badge className="ml-auto bg-background-brand-bold text-text-inverse tabular">
                          {t.unread}
                        </Badge>
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
