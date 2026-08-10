import { ChevronsLeft, ChevronsRight, Search } from "lucide-react";

import { useMe } from "@/api/me";
import { BigBoundMark } from "@/components/brand/BigBoundMark";
import { BRAND } from "@/lib/brand";
import { CommandPalette, useCommandPalette } from "@/components/shell/CommandPalette";
import { NotificationsPopover } from "@/components/shell/NotificationsPopover";
import { HelpPopover } from "@/components/shell/HelpPopover";
import { MobileNav } from "@/components/shell/MobileNav";
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
    <header className="z-20 flex h-14 shrink-0 items-center gap-150 border-b border-border bg-surface px-200">
      <MobileNav />

      <button
        type="button"
        onClick={toggle}
        className="focus-ring hidden h-9 w-9 shrink-0 place-items-center rounded-medium text-text-subtle hover:bg-background-neutral-subtle-hovered hover:text-text-brand lg:grid"
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
      </button>

      {/* The sidebar is lg-only, so below that breakpoint this is the only branding
          on screen. Hidden at lg+ to avoid two marks in the same viewport. */}
      <div className="flex shrink-0 items-center gap-100 lg:hidden">
        <BigBoundMark size={26} />
        <span className="text-body-small font-medium text-text">{BRAND.shortName}</span>
      </div>

      <button
        type="button"
        onClick={() => setOpen(true)}
        className="focus-ring flex h-9 max-w-md flex-1 items-center gap-100 rounded-medium border border-border bg-surface-sunken px-150 text-left text-body-small text-text-subtle transition-colors hover:bg-surface"
      >
        <Search className="h-4 w-4" />
        <span>Search customers, calls, disputes…</span>
        <span className="ml-auto rounded-small border border-border bg-surface px-075 py-025 text-body-small font-medium text-text-subtlest">
          ⌘K
        </span>
      </button>

      <div className="ml-auto flex items-center gap-050">
        <NotificationsPopover />
        <HelpPopover />
        <div className="ml-100 flex items-center gap-100 rounded-full border border-border bg-surface-sunken py-050 pl-050 pr-150">
          <div className="grid h-7 w-7 place-items-center rounded-full bg-background-brand-bold text-body-small font-medium text-text-inverse">
            {initials}
          </div>
          <div className="leading-tight">
            <div className="text-body-small font-medium text-text">{me?.name ?? "…"}</div>
            <div className="text-body-small text-text-subtle">{me?.team ?? "Loading"}</div>
          </div>
        </div>
      </div>

      <CommandPalette open={open} onOpenChange={setOpen} />
    </header>
  );
}
