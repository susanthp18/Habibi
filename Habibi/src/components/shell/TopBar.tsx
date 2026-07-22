import { Bell, HelpCircle, Search } from "lucide-react";
import { toast } from "sonner";

import { useMe } from "@/api/me";

export function TopBar() {
  const { data: me } = useMe();
  const initials = me
    ? me.name
        .split(" ")
        .map((part) => part[0])
        .slice(0, 2)
        .join("")
        .toUpperCase()
    : "…";

  return (
    <header className="z-20 flex h-14 shrink-0 items-center gap-3 border-b border-[var(--border-token)] bg-surface-card px-4">
      <button
        type="button"
        onClick={() => toast("Command palette coming soon", { description: "⌘K jump-to customer, call, dispute…" })}
        className="flex h-9 flex-1 max-w-md items-center gap-2 rounded-md border border-[var(--border-token)] bg-surface-sunken px-3 text-left text-[13px] text-text-secondary transition-colors hover:bg-white"
      >
        <Search className="h-4 w-4" />
        <span>Search customers, calls, disputes…</span>
        <span className="ml-auto rounded border border-[var(--border-token)] bg-white px-1.5 py-0.5 text-[10px] font-semibold text-text-muted">
          ⌘K
        </span>
      </button>

      <div className="ml-auto flex items-center gap-1">
        <button
          type="button"
          onClick={() => toast("3 new notifications")}
          className="relative grid h-9 w-9 place-items-center rounded-md text-text-secondary transition-colors hover:bg-surface-sunken"
          aria-label="Notifications"
        >
          <Bell className="h-4.5 w-4.5" />
          <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-danger" />
        </button>
        <button
          type="button"
          onClick={() => toast("Help center")}
          className="grid h-9 w-9 place-items-center rounded-md text-text-secondary transition-colors hover:bg-surface-sunken"
          aria-label="Help"
        >
          <HelpCircle className="h-4.5 w-4.5" />
        </button>
        <div className="ml-2 flex items-center gap-2 rounded-full border border-[var(--border-token)] bg-surface-sunken py-1 pl-1 pr-3">
          <div className="grid h-7 w-7 place-items-center rounded-full bg-brand-primary text-[12px] font-semibold text-white">
            {initials}
          </div>
          <div className="leading-tight">
            <div className="text-[12px] font-semibold text-text-primary">{me?.name ?? "…"}</div>
            <div className="text-[10px] text-text-secondary">{me?.team ?? "Loading"}</div>
          </div>
        </div>
      </div>
    </header>
  );
}
