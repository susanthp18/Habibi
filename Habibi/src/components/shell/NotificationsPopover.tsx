import { useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Bell, CheckCheck } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useWorkspaceSummary, useWorkItems } from "@/api/workspace";
import { entityTypeFromSlaLabel, navigateWorkItem } from "@/lib/workspace-nav";
import { cn } from "@/lib/utils";

const READ_KEY = "habibi.workspaceNotifRead";

type Notif = {
  id: string;
  title: string;
  body: string;
  level: "breach" | "warn" | "info";
  href?: { entityType: string; id: string } | { to: string; search?: Record<string, string | boolean> };
};

function readSet(): Set<string> {
  try {
    const raw = localStorage.getItem(READ_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as string[];
    return new Set(Array.isArray(arr) ? arr : []);
  } catch {
    return new Set();
  }
}

function writeSet(ids: Set<string>) {
  try {
    localStorage.setItem(READ_KEY, JSON.stringify([...ids]));
  } catch {
    /* ignore */
  }
}

export function NotificationsPopover() {
  const navigate = useNavigate();
  const { data: summary } = useWorkspaceSummary("me");
  const { data: items = [] } = useWorkItems("me");
  const [open, setOpen] = useState(false);
  const [read, setRead] = useState<Set<string>>(() => readSet());

  const notifications = useMemo(() => {
    const list: Notif[] = [];

    for (const s of summary?.slaCountdowns ?? []) {
      if (s.level !== "breach" && s.level !== "warn") continue;
      const entityType = entityTypeFromSlaLabel(s.label);
      list.push({
        id: `sla:${s.id}`,
        title: s.level === "breach" ? "SLA breach" : "SLA warning",
        body: `${s.label} · ${s.remaining}`,
        level: s.level,
        href: entityType ? { entityType, id: s.id } : undefined,
      });
    }

    const next = summary?.nextCallback;
    if (next && next.inMinutes <= 120) {
      list.push({
        id: `cb:${next.id}`,
        title: next.inMinutes <= 0 ? "Callback due now" : "Upcoming callback",
        body: `${next.customer} · ${next.time} ${next.timezone} (${next.inMinutes}m)`,
        level: next.inMinutes <= 15 ? "warn" : "info",
        href: { to: "/callbacks", search: { id: next.id } },
      });
    }

    const outside = summary?.outsideWindowCount ?? 0;
    if (outside > 0) {
      list.push({
        id: `outside:${outside}`,
        title: "Outside contact window",
        body: `${outside} scheduled item${outside === 1 ? "" : "s"} outside permitted hours`,
        level: "warn",
        href: { to: "/consent" },
      });
    }

    // Breach/warn work items not already covered by SLA strip
    for (const w of items) {
      if (w.sla !== "breach" && w.sla !== "warn") continue;
      const id = `wi:${w.entityType}:${w.id}`;
      if (list.some((n) => n.id === `sla:${w.id}`)) continue;
      list.push({
        id,
        title: w.sla === "breach" ? "Queue breach" : "Queue warning",
        body: `${w.customer} · ${w.type} · ${w.slaLabel}`,
        level: w.sla,
        href: { entityType: w.entityType, id: w.id },
      });
    }

    return list.slice(0, 12);
  }, [summary, items]);

  const unread = notifications.filter((n) => !read.has(n.id));
  const badge = unread.length;

  const markAllRead = () => {
    const next = new Set(read);
    for (const n of notifications) next.add(n.id);
    setRead(next);
    writeSet(next);
  };

  const onClick = (n: Notif) => {
    const next = new Set(read);
    next.add(n.id);
    setRead(next);
    writeSet(next);
    setOpen(false);
    if (!n.href) return;
    if ("to" in n.href) {
      void (navigate as (opts: { to: string; search?: Record<string, unknown> }) => unknown)(
        n.href.search ? { to: n.href.to, search: n.href.search } : { to: n.href.to },
      );
      return;
    }
    navigateWorkItem(navigate as (opts: { to: string; search?: Record<string, unknown> }) => unknown, {
      id: n.href.id,
      entityType: n.href.entityType,
    });
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="relative grid h-9 w-9 place-items-center rounded-md text-text-secondary transition-colors hover:bg-surface-sunken"
          aria-label="Notifications"
        >
          <Bell className="h-4.5 w-4.5" />
          {badge > 0 && (
            <span className="absolute right-1.5 top-1.5 flex h-2 min-w-2 items-center justify-center rounded-full bg-danger" />
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[360px] p-0">
        <div className="flex items-center justify-between border-b border-[var(--border-token)] px-3 py-2.5">
          <div>
            <div className="text-[13px] font-semibold text-brand-navy">Notifications</div>
            <div className="text-[11px] text-text-muted">
              {badge > 0 ? `${badge} unread from your queue` : "Caught up"}
            </div>
          </div>
          {notifications.length > 0 && (
            <button
              type="button"
              onClick={markAllRead}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-brand-primary hover:underline"
            >
              <CheckCheck className="h-3.5 w-3.5" />
              Mark all read
            </button>
          )}
        </div>
        <ul className="max-h-[360px] overflow-y-auto">
          {notifications.length === 0 && (
            <li className="px-3 py-8 text-center text-[12px] text-text-muted">
              No SLA alerts or upcoming callbacks right now.
            </li>
          )}
          {notifications.map((n) => {
            const isUnread = !read.has(n.id);
            return (
              <li key={n.id} className="border-b border-[var(--border-token)] last:border-0">
                <button
                  type="button"
                  onClick={() => onClick(n)}
                  className={cn(
                    "flex w-full flex-col gap-0.5 px-3 py-2.5 text-left transition-colors hover:bg-brand-tint/50",
                    isUnread && "bg-surface-sunken/40",
                  )}
                >
                  <div className="flex items-center gap-2">
                    {isUnread && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand-primary" />}
                    <span className="text-[12.5px] font-semibold text-text-primary">{n.title}</span>
                    <span
                      className={cn(
                        "ml-auto rounded-full px-1.5 py-0.5 text-[9px] font-semibold uppercase",
                        n.level === "breach" && "bg-danger-bg text-danger",
                        n.level === "warn" && "bg-warning-bg text-warning",
                        n.level === "info" && "bg-brand-tint text-brand-primary-dark",
                      )}
                    >
                      {n.level}
                    </span>
                  </div>
                  <div className="text-[11.5px] text-text-secondary">{n.body}</div>
                </button>
              </li>
            );
          })}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
