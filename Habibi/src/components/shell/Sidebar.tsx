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

const groups: NavGroup[] = [
  {
    label: "Live Operations",
    items: [
      { label: "My Workspace", icon: Home, to: "/" },
      { label: "Conversation Inbox", icon: LayoutGrid, to: "/inbox" },
      { label: "Handoff Hub", icon: Headphones, to: "/handoff" },
      { label: "Floor Command", icon: Activity, to: "/floor" },
    ],
  },
  {
    label: "CRM & Resolution",
    items: [
      { label: "Executive Dashboard", icon: BarChart3, to: "/dashboard" },
      { label: "Customer 360", icon: Users, to: "/customers" },
      { label: "Promise-to-Pay", icon: HandCoins, to: "/promises" },
      { label: "Disputes Queue", icon: AlertOctagon, to: "/disputes" },
      { label: "Document Desk", icon: FileText, to: "/documents" },
      { label: "Callbacks", icon: CalendarClock, to: "/callbacks" },
      { label: "Upsell & Leads", icon: Sparkles, to: "/upsell" },
    ],
  },
  {
    label: "Compliance & QA",
    items: [
      { label: "Audit Trail", icon: ClipboardList, to: "/audit" },
      { label: "Compliance Risk", icon: ShieldAlert, to: "/compliance" },
      { label: "Consent / DND", icon: UserCheck, to: "/consent" },
      { label: "Redaction & Export", icon: FileLock2, to: "/redaction" },
      { label: "QA Scorecards", icon: ClipboardCheck, to: "/qa" },
      { label: "Bot Analytics", icon: Activity, to: "/bot-analytics" },
    ],
  },
  {
    label: "Bot Configuration",
    items: [
      { label: "Knowledge Base", icon: BookOpen, to: "/knowledge-base" },
      { label: "Prompt Studio", icon: Bot, to: "/prompt-studio" },
      { label: "Call Sandbox", icon: Beaker, to: "/sandbox" },
      { label: "Routing / Logic", icon: GitBranch, to: "/routing" },
      { label: "Integrations", icon: Plug, to: "/integrations" },
      { label: "Webhooks", icon: Webhook, to: "/webhooks" },
      { label: "Billing & Usage", icon: Receipt, to: "/billing" },
      { label: "Roles & Access", icon: ShieldCheck, soon: true },
    ],
  },
];

export function Sidebar() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { collapsed, toggle } = useSidebarUi();

  return (
    <aside
      className={cn(
        "hidden h-screen min-h-0 shrink-0 flex-col border-r border-[var(--border-token)] bg-surface-card transition-[width] duration-200 ease-out lg:flex",
        collapsed ? "w-16" : "w-[240px]",
      )}
    >
      <div
        className={cn(
          "flex h-14 shrink-0 items-center border-b border-[var(--border-token)]",
          collapsed ? "justify-center px-1.5" : "gap-2 px-3",
        )}
      >
        <BigBoundMark size={collapsed ? 28 : 32} />
        {!collapsed && (
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-[13px] font-semibold tracking-tight text-brand-navy">
              {BRAND.name}
            </div>
            <div className="truncate text-[11px] text-text-secondary">{BRAND.tenantLine}</div>
          </div>
        )}
        {!collapsed && (
          <button
            type="button"
            onClick={toggle}
            className="grid h-8 w-8 place-items-center rounded-md text-text-secondary hover:bg-surface-sunken hover:text-brand-primary"
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
          >
            <ChevronsLeft className="h-4 w-4" />
          </button>
        )}
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
        {groups.map((group) => (
          <div key={group.label} className={cn("mb-3", collapsed && "mb-2")}>
            {!collapsed && (
              <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-[0.4px] text-text-muted">
                {group.label}
              </div>
            )}
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = Boolean(item.to && pathname === item.to);
                const Icon = item.icon;
                const base = cn(
                  "flex items-center rounded-md text-[13px] transition-colors",
                  collapsed ? "justify-center px-0 py-2.5" : "gap-2.5 px-3 py-2",
                  active
                    ? "bg-brand-tint font-semibold text-brand-primary-dark"
                    : "text-text-primary hover:bg-surface-sunken",
                  item.soon && "cursor-not-allowed opacity-60 hover:bg-transparent",
                );
                const body = (
                  <>
                    <Icon className={cn("h-4 w-4 shrink-0", active && "text-brand-primary")} />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                    {!collapsed && item.soon && (
                      <span className="ml-auto rounded-md bg-surface-sunken px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-text-muted">
                        Soon
                      </span>
                    )}
                  </>
                );
                return (
                  <li key={item.label}>
                    {item.to && !item.soon ? (
                      <Link to={item.to} className={base} title={item.label} aria-label={item.label}>
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
      </nav>

      {collapsed ? (
        <div className="shrink-0 border-t border-[var(--border-token)] p-2">
          <button
            type="button"
            onClick={toggle}
            className="grid h-9 w-full place-items-center rounded-md text-text-secondary hover:bg-surface-sunken hover:text-brand-primary"
            aria-label="Expand sidebar"
            title="Expand sidebar"
          >
            <ChevronsRight className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <div className="shrink-0 border-t border-[var(--border-token)] px-4 py-3 text-[11px] text-text-muted">
          {BRAND.shortName} · v0.1
        </div>
      )}
    </aside>
  );
}
