import { ChevronsLeft, ChevronsRight, Search } from "lucide-react";

import { useMe } from "@/api/me";
import { CommandPalette, useCommandPalette } from "@/components/shell/CommandPalette";
import { NotificationsPopover } from "@/components/shell/NotificationsPopover";
import { HelpPopover } from "@/components/shell/HelpPopover";
import { useSidebarUi } from "@/components/shell/sidebar-ui";

export function TopBar() {
  const { data: me } = useMe();
  const { open, setOpen } = useCommandPalette();
  const { collapsed, toggle } = useSidebarUi();
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
        onClick={toggle}
        className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-text-secondary hover:bg-surface-sunken hover:text-brand-primary"
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
      </button>

      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex h-9 max-w-md flex-1 items-center gap-2 rounded-md border border-[var(--border-token)] bg-surface-sunken px-3 text-left text-[13px] text-text-secondary transition-colors hover:bg-white"
      >
        <Search className="h-4 w-4" />
        <span>Search customers, calls, disputes…</span>
        <span className="ml-auto rounded border border-[var(--border-token)] bg-white px-1.5 py-0.5 text-[10px] font-semibold text-text-muted">
          ⌘K
        </span>
      </button>

      <div className="ml-auto flex items-center gap-1">
        <NotificationsPopover />
        <HelpPopover />
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

      <CommandPalette open={open} onOpenChange={setOpen} />
    </header>
  );
}
