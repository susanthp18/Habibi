import {
  Check,
  ChevronDown,
  ChevronsLeft,
  ChevronsRight,
  LogOut,
  Moon,
  Search,
  Settings,
  Sun,
} from "lucide-react";
import { useNavigate } from "@tanstack/react-router";

import { EqualizerMark } from "@/components/brand/EqualizerMark";
import { BigtappMark } from "@/components/brand/BigtappMark";
import { HomeLink } from "@/components/brand/HomeLink";
import { BRAND } from "@/lib/brand";
import { entraConfigured, entraDisplayName, signOut } from "@/lib/sso";
import { useMe } from "@/api/me";
import { CommandPalette, useCommandPalette } from "@/components/shell/CommandPalette";
import { NotificationsPopover } from "@/components/shell/NotificationsPopover";
import { HelpPopover } from "@/components/shell/HelpPopover";
import { MobileNav } from "@/components/shell/MobileNav";
import { useSidebarUi } from "@/components/shell/sidebar-ui";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { setTheme, useTheme } from "@/lib/theme";

function initialsOf(name: string) {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase() || "?"
  );
}

function AccountMenu() {
  const theme = useTheme();
  const { data: me } = useMe();
  const navigate = useNavigate();
  const operatorName = me?.name || entraDisplayName();
  const initials = initialsOf(operatorName);
  const meta = [me?.team, me?.status].filter(Boolean).join(" · ");

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Account menu"
          className="group focus-ring flex h-9 max-w-[14rem] items-center gap-100 rounded-medium px-100 text-text transition-[background-color,transform] duration-token-short hover:bg-background-neutral-subtle-hovered active:scale-[0.98]"
        >
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-background-brand-bold text-body-micro font-semibold text-text-inverse">
            {initials}
          </span>
          {operatorName ? (
            <span className="hidden min-w-0 truncate text-body-small font-medium sm:inline">
              {operatorName}
            </span>
          ) : null}
          <ChevronDown className="h-4 w-4 shrink-0 text-text-subtle transition-transform duration-token-medium group-data-[state=open]:rotate-180" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={8} className="w-72 p-100">
        <div className="flex items-center gap-150 px-100 py-100">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-background-brand-bold text-body-small font-semibold text-text-inverse">
            {initials}
          </span>
          <div className="min-w-0">
            <div className="truncate text-body font-medium text-text">
              {operatorName || "Operator"}
            </div>
            {meta ? (
              <div className="truncate text-body-small capitalize text-text-subtle">{meta}</div>
            ) : null}
          </div>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void navigate({ to: "/settings" })}>
          <Settings className="h-4 w-4" />
          Settings
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-body-small font-medium text-text-subtle">
          Appearance
        </DropdownMenuLabel>
        <DropdownMenuItem
          onSelect={(event) => {
            event.preventDefault();
            setTheme("light");
          }}
        >
          <Sun className="h-4 w-4" />
          Light
          {theme === "light" ? <Check className="ml-auto h-4 w-4" /> : null}
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={(event) => {
            event.preventDefault();
            setTheme("dark");
          }}
        >
          <Moon className="h-4 w-4" />
          Dark
          {theme === "dark" ? <Check className="ml-auto h-4 w-4" /> : null}
        </DropdownMenuItem>
        {entraConfigured() ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() => void signOut()}
              className="text-text-danger focus:text-text-danger-bolder"
            >
              <LogOut className="h-4 w-4" />
              Sign out
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function TopBar() {
  const { open, setOpen } = useCommandPalette();
  const { collapsed, toggle } = useSidebarUi();

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
        <EqualizerMark size={26} />
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

      <div className="ml-auto flex items-center gap-100">
        <div className="flex items-center gap-150 pr-050">
          <BigtappMark size={32} />
          <HomeLink className="hidden text-body font-medium text-text hover:underline sm:inline">
            Home
          </HomeLink>
        </div>
        <NotificationsPopover />
        <HelpPopover />
        <AccountMenu />
      </div>

      <CommandPalette open={open} onOpenChange={setOpen} />
    </header>
  );
}
