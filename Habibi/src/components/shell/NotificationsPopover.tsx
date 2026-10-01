import { useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Bell, CheckCheck } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useMe } from "@/api/me";
import { dueLabel, liveLevel, useWorkspaceSummary, type WorkItem } from "@/api/workspace";
import { navigateWorkItem } from "@/lib/workspace-nav";
import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";
import { useNow } from "@/lib/use-now";

type Notif = {
  id: string;
  title: string;
  body: string;
  level: "breach" | "warn" | "info";
  item?: WorkItem;
  href?: { to: string; search?: Record<string, string | boolean> };
};

/** Read state is per operator and tenant: one browser shared by two logins
 *  used to mark one person's alerts read for the other. */
function readKey(userId: string | undefined, tenantId: string | undefined) {
  return `habibi.workspaceNotifRead:${tenantId ?? "-"}:${userId ?? "-"}`;
}

function readSet(key: string): Set<string> {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as string[];
    return new Set(Array.isArray(arr) ? arr : []);
  } catch {
    return new Set();
  }
}

function writeSet(key: string, ids: Set<string>) {
  try {
    localStorage.setItem(key, JSON.stringify([...ids]));
  } catch {
    /* ignore */
  }
}

export function NotificationsPopover() {
  const navigate = useNavigate();
  const now = useNow();
  const { data: me } = useMe();
  const key = readKey(me?.id, me?.tenantId);
  const { data: summary, isError, isPending, dataUpdatedAt } = useWorkspaceSummary("me");
  const [open, setOpen] = useState(false);
  const [readState, setRead] = useState<{ key: string; ids: Set<string> }>(() => ({
    key,
    ids: readSet(key),
  }));
  const read = readState.key === key ? readState.ids : readSet(key);

  const notifications = useMemo(() => {
    const list: Notif[] = [];

    // The level is part of the id: a warning that becomes a breach is a new
    // alert, and must not stay marked read. It is the live level, so the
    // title, colour and identity follow the clock between refreshes.
    for (const w of summary?.attention ?? []) {
      const level = liveLevel(w, now);
      list.push({
        id: `wi:${w.entityType}:${w.id}:${level}`,
        title: level === "breach" ? "Overdue" : "Due soon",
        body: `${w.type} · ${w.customer} · ${w.dueAt ? dueLabel(w.dueAt, now) : w.slaLabel}`,
        level: level === "ok" ? "info" : level,
        item: w,
      });
    }

    const next = summary?.nextCallback;
    const mins = next ? Math.round((new Date(next.scheduledAt).getTime() - now) / 60_000) : null;
    if (next && mins !== null && mins <= 120) {
      list.push({
        id: `cb:${next.id}:${mins <= 15 ? "warn" : "info"}`,
        title: mins <= 0 ? "Callback due now" : "Upcoming callback",
        body: `${next.customer} · ${next.time} ${next.timezone} (${dueLabel(next.scheduledAt, now)})`,
        level: mins <= 15 ? "warn" : "info",
        href: { to: "/callbacks", search: { id: next.id } },
      });
    }

    const blocked = summary?.callbacksBlockedCount ?? 0;
    if (blocked > 0) {
      const atLeast = summary?.callbacksBlockedPartial ? "At least " : "";
      list.push({
        id: `blocked:${atLeast}${blocked}`,
        title: "Callback the contact rules would refuse",
        body: `${atLeast}${blocked} upcoming callback${blocked === 1 ? "" : "s"} booked for a blocked time`,
        level: "warn",
        href: { to: "/callbacks" },
      });
    }
    return list;
  }, [summary, now]);

  const counts = summary?.queueCounts;
  const more = counts
    ? Math.max(0, counts.overdue + counts.dueSoon - (summary?.attention.length ?? 0))
    : 0;
  const unread = notifications.filter((n) => !read.has(n.id));
  const badge = unread.length;

  const markRead = (ids: string[]) => {
    const next = new Set(read);
    for (const id of ids) next.add(id);
    setRead({ key, ids: next });
    writeSet(key, next);
  };

  const markAllRead = () => markRead(notifications.map((n) => n.id));

  const onClick = (n: Notif) => {
    markRead([n.id]);
    setOpen(false);
    if (n.item) navigateWorkItem(navigate, n.item);
    else if (n.href) void navigate(n.href);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="relative grid h-9 w-9 place-items-center rounded-medium text-text-subtle transition-colors hover:bg-surface-sunken"
          aria-label="Notifications"
        >
          <Bell className="h-4.5 w-4.5" />
          {badge > 0 && (
            <span className="absolute right-1.5 top-1.5 flex h-100 min-w-100 items-center justify-center rounded-full bg-background-danger" />
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[22.5rem] p-0">
        <div className="flex items-center justify-between border-b border-border px-150 py-150">
          <div>
            <div className="text-body font-semibold text-text">Notifications</div>
            <div className="text-body-small text-text-subtlest">
              {isError && !summary
                ? "Couldn’t load your alerts"
                : isError
                  ? `Couldn’t refresh — alerts as of ${new Date(dataUpdatedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
                  : isPending
                    ? "Loading…"
                    : badge > 0
                      ? `${badge} unread from your queue`
                      : "Caught up"}
            </div>
          </div>
          {notifications.length > 0 && (
            <button
              type="button"
              onClick={markAllRead}
              className="inline-flex items-center gap-050 text-body-small font-medium text-text-brand hover:underline"
            >
              <CheckCheck className="h-3.5 w-3.5" />
              Mark all read
            </button>
          )}
        </div>
        <ul className="max-h-[22.5rem] overflow-y-auto">
          {notifications.length === 0 && summary && !isError && (
            <li className="px-150 py-400 text-center text-body-small text-text-subtlest">
              Nothing overdue, due soon or blocked right now.
            </li>
          )}
          {notifications.map((n) => {
            const isUnread = !read.has(n.id);
            return (
              <li key={n.id} className="border-b border-border last:border-0">
                <button
                  type="button"
                  onClick={() => onClick(n)}
                  className={cn(
                    "flex w-full flex-col gap-025 px-150 py-150 text-left transition-colors hover:bg-background-brand-subtlest/50",
                    isUnread && "bg-surface-sunken/40",
                  )}
                >
                  <div className="flex items-center gap-100">
                    {isUnread && (
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-background-brand-bold" />
                    )}
                    <span className="text-body-small font-semibold text-text">{n.title}</span>
                    <Lozenge
                      tone={
                        n.level === "breach"
                          ? "danger"
                          : n.level === "warn"
                            ? "warning"
                            : "selected"
                      }
                      className="ml-auto"
                    >
                      {n.level}
                    </Lozenge>
                  </div>
                  <div className="text-body-small text-text-subtle">{n.body}</div>
                </button>
              </li>
            );
          })}
        </ul>
        {more > 0 && (
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              void navigate({ to: "/" });
            }}
            className="w-full border-t border-border px-150 py-100 text-left text-body-small font-medium text-text-brand hover:bg-surface-sunken"
          >
            +{more} more overdue or due soon — open My workspace
          </button>
        )}
      </PopoverContent>
    </Popover>
  );
}
