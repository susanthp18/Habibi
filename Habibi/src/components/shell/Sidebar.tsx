import { Link, useRouterState } from "@tanstack/react-router";
import {
  Home,
  Headphones,
  LayoutGrid,
  BarChart3,
  Users,
  HandCoins,
  AlertOctagon,
  FileText,
  CalendarClock,
  Sparkles,
  ShieldCheck,
  ClipboardList,
  UserCheck,
  FileLock2,
  ClipboardCheck,
  Activity,
  BookOpen,
  Bot,
  Beaker,
  GitBranch,
  Plug,
  Webhook,
  Receipt,
  ShieldAlert,
  ChevronsLeft,
  ChevronsRight,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { BigBoundMark } from "@/components/brand/BigBoundMark";
import { BRAND } from "@/lib/brand";
import { useSidebarUi } from "./sidebar-ui";

type NavItem = {
  label: string;
  icon: LucideIcon;
  to?: string;
  soon?: boolean;
};

type NavGroup = { label: string; items: NavItem[] };

// Design.md: sentence case everywhere, no exceptions — only proper nouns/acronyms (QA, CRM, DND)
// keep their capitalization.
const groups: NavGroup[] = [
  {
    label: "Live operations",
    items: [
      { label: "My workspace", icon: Home, to: "/" },
      { label: "Conversation inbox", icon: LayoutGrid, to: "/inbox" },
      { label: "Handoff hub", icon: Headphones, to: "/handoff" },
      { label: "Floor command", icon: Activity, to: "/floor" },
    ],
  },
  {
    label: "CRM & resolution",
    items: [
      { label: "Executive dashboard", icon: BarChart3, to: "/dashboard" },
      { label: "Customer 360", icon: Users, to: "/customers" },
      { label: "Promise to pay", icon: HandCoins, to: "/promises" },
      { label: "Disputes queue", icon: AlertOctagon, to: "/disputes" },
      { label: "Document desk", icon: FileText, to: "/documents" },
      { label: "Callbacks", icon: CalendarClock, to: "/callbacks" },
      { label: "Upsell & leads", icon: Sparkles, to: "/upsell" },
    ],
  },
  {
    label: "Compliance & QA",
    items: [
      { label: "Audit trail", icon: ClipboardList, to: "/audit" },
      { label: "Compliance risk", icon: ShieldAlert, to: "/compliance" },
      { label: "Consent / DND", icon: UserCheck, to: "/consent" },
      { label: "Redaction & export", icon: FileLock2, to: "/redaction" },
      { label: "QA scorecards", icon: ClipboardCheck, to: "/qa" },
      { label: "Bot analytics", icon: Activity, to: "/bot-analytics" },
    ],
  },
  {
    label: "Bot configuration",
    items: [
      { label: "Knowledge base", icon: BookOpen, to: "/knowledge-base" },
      { label: "Prompt studio", icon: Bot, to: "/prompt-studio" },
      { label: "Call sandbox", icon: Beaker, to: "/sandbox" },
      { label: "Routing / logic", icon: GitBranch, to: "/routing" },
      { label: "Integrations", icon: Plug, to: "/integrations" },
      { label: "Webhooks", icon: Webhook, to: "/webhooks" },
      { label: "Billing & usage", icon: Receipt, to: "/billing" },
      { label: "Roles & access", icon: ShieldCheck, soon: true },
    ],
  },
];

/** Shared nav-group rendering — reused by the desktop Sidebar and the mobile drawer (MobileNav). */
export function NavLinks({
  collapsed = false,
  pathname,
  onNavigate,
}: {
  collapsed?: boolean;
  pathname: string;
  onNavigate?: () => void;
}) {
  return (
    <>
      {groups.map((group) => (
        <div key={group.label} className={cn("mb-150", collapsed && "mb-100")}>
          {!collapsed && (
            <div className="px-150 pb-050 text-body-small font-medium text-text-subtle">
              {group.label}
            </div>
          )}
          <ul className="space-y-025">
            {group.items.map((item) => {
              const active = Boolean(item.to && pathname === item.to);
              const Icon = item.icon;
              // Full selected triad (background + text + border rail) per Design.md — never
              // just a tint or just a border on its own.
              const base = cn(
                "focus-ring flex items-center rounded-medium border-l-2 border-l-transparent text-body transition-colors duration-token-short",
                collapsed ? "justify-center px-0 py-150" : "gap-150 px-150 py-100",
                active
                  ? "bg-background-selected border-l-border-selected font-medium text-text-selected"
                  : "text-text hover:bg-background-neutral-subtle-hovered",
                item.soon && "cursor-not-allowed opacity-60 hover:bg-transparent",
              );
              const body = (
                <>
                  <Icon className={cn("h-4 w-4 shrink-0", active && "text-icon-selected")} />
                  {!collapsed && <span className="truncate">{item.label}</span>}
                  {!collapsed && item.soon && (
                    <span className="ml-auto rounded-small bg-background-neutral-subtle px-075 py-025 text-body-small text-text-subtlest">
                      Soon
                    </span>
                  )}
                </>
              );
              return (
                <li key={item.label}>
                  {item.to && !item.soon ? (
                    <Link
                      to={item.to}
                      className={base}
                      title={item.label}
                      aria-label={item.label}
                      onClick={onNavigate}
                    >
                      {body}
                    </Link>
                  ) : (
                    <div className={base} aria-disabled title={item.label} aria-label={item.label}>
                      {body}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </>
  );
}

export function Sidebar() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { collapsed, toggle } = useSidebarUi();

  return (
    <aside
      className={cn(
        "hidden h-screen min-h-0 shrink-0 flex-col border-r border-border bg-surface transition-[width] duration-token-medium ease-token-out-practical lg:flex",
        collapsed ? "w-800" : "w-[15rem]",
      )}
    >
      <div
        className={cn(
          "flex h-14 shrink-0 items-center border-b border-border",
          collapsed ? "justify-center px-075" : "gap-100 px-150",
        )}
      >
        <BigBoundMark size={collapsed ? 28 : 32} />
        {!collapsed && (
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-body-small font-medium text-text">
              {BRAND.name}
            </div>
            <div className="truncate text-body-small text-text-subtle">{BRAND.tenantLine}</div>
          </div>
        )}
        {!collapsed && (
          <button
            type="button"
            onClick={toggle}
            className="focus-ring grid h-400 w-400 place-items-center rounded-medium text-text-subtle hover:bg-background-neutral-subtle-hovered hover:text-text-brand"
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
          >
            <ChevronsLeft className="h-4 w-4" />
          </button>
        )}
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-100 py-150">
        <NavLinks collapsed={collapsed} pathname={pathname} />
      </nav>

      {collapsed ? (
        <div className="shrink-0 border-t border-border p-100">
          <button
            type="button"
            onClick={toggle}
            className="focus-ring grid h-9 w-full place-items-center rounded-medium text-text-subtle hover:bg-background-neutral-subtle-hovered hover:text-text-brand"
            aria-label="Expand sidebar"
            title="Expand sidebar"
          >
            <ChevronsRight className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <div className="shrink-0 border-t border-border px-200 py-150 text-body-small text-text-subtlest">
          {BRAND.shortName} · v0.1
        </div>
      )}
    </aside>
  );
}
