import { Search, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ThreadStatus, ThreadSummary } from "@/api/types/inbox";
import { INBOX_LIST_LIMIT } from "@/api/inbox";
import { Avatar, resolveChannelMeta, slaColor, statusMeta } from "./meta";
import { Badge } from "@/components/ui/badge";
import { useMemo, useState, type KeyboardEvent } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type Filter = "all" | ThreadStatus | "mine" | "others";

const primaryFilters: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "needs_human", label: "Needs human" },
  { key: "mine", label: "Mine" },
];

const moreFilters: { key: Filter; label: string }[] = [
  { key: "others", label: "Held by others" },
  { key: "bot", label: "Bot-handled" },
  { key: "escalated", label: "Escalated" },
];

const statusDot: Record<string, string> = {
  bot: "bg-background-brand-bold",
  needs_human: "bg-background-warning-bold",
  escalated: "bg-background-danger-bold",
  assigned: "bg-background-neutral-bold",
  mine: "bg-background-success-bold",
};

const SLA_WORDS = {
  ok: "waiting under 4 hours",
  warn: "waiting over 4 hours",
  breach: "waiting over 24 hours",
} as const;

function matches(t: ThreadSummary, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "mine") return t.isMine;
  if (filter === "others") return t.status === "assigned" && !t.isMine;
  return t.status === filter;
}

/**
 * The row's dot: how long the customer has waited when they are waiting,
 * otherwise who holds the thread. Its colour and its name always come from
 * the same fact -- they used to be the SLA's colour under the status's name.
 */
function rowDot(t: ThreadSummary): { className: string; label: string } {
  if (t.awaitingReply > 0) {
    return { className: slaColor[t.sla], label: `Customer ${SLA_WORDS[t.sla]}` };
  }
  const chip = t.isMine ? "mine" : t.status;
  return { className: statusDot[chip] ?? "bg-text-subtlest", label: statusMeta[chip].label };
}

export function ConversationList({
  threads,
  activeId,
  onSelect,
  search,
  onSearchChange,
  searching,
  searchFailed,
}: {
  threads: ThreadSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  /** Searched on the server, across every message and the whole inbox. */
  search: string;
  onSearchChange: (value: string) => void;
  searching: boolean;
  searchFailed: boolean;
}) {
  const [filter, setFilter] = useState<Filter>("all");

  const counts = useMemo(() => {
    const c = {} as Record<Filter, number>;
    for (const f of [...primaryFilters, ...moreFilters]) {
      c[f.key] = threads.filter((t) => matches(t, f.key)).length;
    }
    return c;
  }, [threads]);

  const filtered = useMemo(() => threads.filter((t) => matches(t, filter)), [threads, filter]);
  const moreActive = moreFilters.some((f) => f.key === filter);
  const moreLabel = moreFilters.find((f) => f.key === filter)?.label ?? "More";
  const full = !search.trim() && threads.length >= INBOX_LIST_LIMIT;

  // Up/Down move between rows: this is a keyboard-first triage list.
  const onRowKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const list = e.currentTarget.closest("ul");
    if (!list) return;
    const rows = Array.from(list.querySelectorAll<HTMLButtonElement>("button[data-row]"));
    const at = rows.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      rows[Math.min(rows.length - 1, Math.max(0, at + (e.key === "ArrowDown" ? 1 : -1)))];
    if (next) {
      e.preventDefault();
      next.focus();
    }
  };

  return (
    <aside className="flex h-full min-h-0 w-full flex-col border-r border-border bg-surface">
      <div className="shrink-0 border-b border-border px-150 py-150">
        <h2 className="mb-100 heading-xsmall text-text">Inbox</h2>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
          <input
            type="search"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            aria-label="Search conversations by customer, account or any message"
            placeholder="Search customer, account, any message"
            className="focus-ring h-9 w-full rounded-medium border border-border-input bg-background-input py-075 pl-400 pr-100 text-body transition-colors duration-token-short placeholder:text-text-subtlest hover:bg-background-input-hovered focus:border-border-focused focus:bg-background-input-pressed"
          />
        </div>
        <div className="mt-150 flex items-center gap-050 overflow-x-auto">
          {primaryFilters.map((f) => (
            <button
              key={f.key}
              type="button"
              aria-pressed={filter === f.key}
              onClick={() => setFilter(f.key)}
              className={cn(
                "focus-ring inline-flex shrink-0 items-center gap-075 rounded-full border px-150 py-050 text-body-small font-medium transition-colors",
                filter === f.key
                  ? "border-border-brand bg-background-brand-subtlest text-text-brand"
                  : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
              )}
            >
              {f.label}
              <Badge
                className={cn(
                  filter === f.key
                    ? "bg-surface text-text-brand"
                    : "bg-surface-sunken text-text-subtle",
                )}
              >
                {counts[f.key]}
              </Badge>
            </button>
          ))}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-pressed={moreActive}
                className={cn(
                  "focus-ring inline-flex shrink-0 items-center gap-075 rounded-full border px-150 py-050 text-body-small font-medium transition-colors",
                  moreActive
                    ? "border-border-brand bg-background-brand-subtlest text-text-brand"
                    : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
                )}
              >
                {moreLabel}
                {moreActive && (
                  <Badge className="bg-surface text-text-brand">{counts[filter]}</Badge>
                )}
                <ChevronDown className="h-3 w-3" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {moreFilters.map((f) => (
                <DropdownMenuItem key={f.key} onSelect={() => setFilter(f.key)}>
                  <span className="flex-1">{f.label}</span>
                  <span className="text-body-small text-text-subtlest">{counts[f.key]}</span>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        {search.trim() && (
          <p role="status" className="mt-100 text-body-small text-text-subtle">
            {searchFailed
              ? "Search failed — try again."
              : searching
                ? "Searching…"
                : `${threads.length} matching conversation${threads.length === 1 ? "" : "s"}`}
          </p>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {filtered.length === 0 && !searching && (
          <div className="p-300 text-center text-body text-text-subtle">
            No conversations match.
          </div>
        )}
        <ul aria-label="Conversations">
          {filtered.map((t, i) => {
            const isActive = t.id === activeId;
            const dot = rowDot(t);
            const channel = resolveChannelMeta(t.channel);
            const ChannelIcon = channel.icon;
            return (
              <li key={t.id}>
                <button
                  type="button"
                  data-row
                  aria-current={isActive ? "true" : undefined}
                  onClick={() => onSelect(t.id)}
                  onKeyDown={onRowKeyDown}
                  style={{ animationDelay: `${Math.min(i, 20) * 25}ms` }}
                  className={cn(
                    "focus-ring animate-fade-up relative flex w-full gap-150 border-b border-border px-150 py-150 text-left transition-colors",
                    isActive ? "bg-background-brand-subtlest" : "hover:bg-surface-sunken",
                  )}
                >
                  {isActive && (
                    <span className="absolute inset-y-0 left-0 w-050 bg-background-brand-bold" />
                  )}
                  <Avatar name={t.customer} size={36} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-075">
                      <span className="truncate text-body font-semibold text-text">
                        {t.customer}
                      </span>
                      <ChannelIcon
                        className="h-3.5 w-3.5 shrink-0 text-text-subtlest"
                        aria-label={channel.label}
                      />
                      <span className="ml-auto whitespace-nowrap text-body-small text-text-subtlest">
                        {t.lastTime}
                      </span>
                    </div>
                    <div className="mt-025 flex items-center gap-075">
                      <span
                        role="img"
                        aria-label={dot.label}
                        title={dot.label}
                        className={cn("h-1.5 w-1.5 shrink-0 rounded-full", dot.className)}
                      />
                      <p className="min-w-0 flex-1 truncate text-body-small text-text-subtle">
                        {t.botTyping ? (
                          <span className="font-medium text-text-brand">Bot is typing…</span>
                        ) : (
                          <>
                            {t.lastFrom === "bot"
                              ? "Bot: "
                              : t.lastFrom === "agent"
                                ? "Agent: "
                                : t.lastFrom === "system"
                                  ? "System: "
                                  : ""}
                            {t.lastPreview}
                          </>
                        )}
                      </p>
                      {t.awaitingReply > 0 && (
                        <Badge
                          className="ml-050 bg-background-brand-bold text-text-inverse tabular"
                          title={`${t.awaitingReply} customer message${t.awaitingReply === 1 ? "" : "s"} awaiting a reply`}
                        >
                          {t.awaitingReply}
                        </Badge>
                      )}
                    </div>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
        {full && (
          <p className="px-150 py-200 text-center text-body-small text-text-subtle">
            Showing the {INBOX_LIST_LIMIT} most recently active conversations. Search to find older
            ones.
          </p>
        )}
      </div>
    </aside>
  );
}
