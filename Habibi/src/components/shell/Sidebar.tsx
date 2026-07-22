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
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

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

  return (
    <aside className="hidden h-screen min-h-0 w-[240px] shrink-0 flex-col border-r border-[var(--border-token)] bg-surface-card lg:flex">
      <div className="flex h-14 shrink-0 items-center gap-2 border-b border-[var(--border-token)] px-4">
        <div className="grid h-8 w-8 place-items-center rounded-md bg-brand-primary text-white font-bold">
          C
        </div>
        <div className="leading-tight">
          <div className="text-[13px] font-semibold text-brand-navy">Collections AI</div>
          <div className="text-[11px] text-text-secondary">HDFC · Retail Loans</div>
        </div>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
        {groups.map((group) => (
          <div key={group.label} className="mb-4">
            <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-[0.4px] text-text-muted">
              {group.label}
            </div>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = item.to && pathname === item.to;
                const Icon = item.icon;
                const base = cn(
                  "group flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] transition-colors",
                  active
                    ? "bg-brand-tint text-brand-primary-dark font-semibold"
                    : "text-text-primary hover:bg-surface-sunken",
                  item.soon && "cursor-not-allowed opacity-60 hover:bg-transparent",
                );
                const content = (
                  <>
                    <Icon className={cn("h-4 w-4 shrink-0", active && "text-brand-primary")} />
                    <span className="truncate">{item.label}</span>
                    {item.soon && (
                      <span className="ml-auto rounded-full bg-surface-sunken px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-text-muted">
                        Soon
                      </span>
                    )}
                  </>
                );
                return (
                  <li key={item.label}>
                    {item.to && !item.soon ? (
                      <Link to={item.to} className={base}>
                        {content}
                      </Link>
                    ) : (
                      <div className={base} aria-disabled>
                        {content}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="shrink-0 border-t border-[var(--border-token)] px-4 py-3 text-[11px] text-text-muted">
        v0.1 · PoC build
      </div>
    </aside>
  );
}
