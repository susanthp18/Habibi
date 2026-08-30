import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
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
  BrainCircuit,
  Beaker,
  GitBranch,
  Plug,
  Webhook,
  Receipt,
  ShieldAlert,
  ChevronsRight,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { EqualizerMark } from "@/components/brand/EqualizerMark";
import { BRAND } from "@/lib/brand";
import { useSidebarUi } from "./sidebar-ui";

type NavItem = {
  key: string;
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
      { key: "workspace", label: "My workspace", icon: Home, to: "/" },
      { key: "inbox", label: "Conversation inbox", icon: LayoutGrid, to: "/inbox" },
      { key: "handoff", label: "Handoff hub", icon: Headphones, to: "/handoff" },
      { key: "floor", label: "Floor command", icon: Activity, to: "/floor" },
    ],
  },
  {
    label: "CRM & resolution",
    items: [
      { key: "dashboard", label: "Executive dashboard", icon: BarChart3, to: "/dashboard" },
      { key: "customers", label: "Customer 360", icon: Users, to: "/customers" },
      { key: "promises", label: "Promise to pay", icon: HandCoins, to: "/promises" },
      { key: "disputes", label: "Disputes queue", icon: AlertOctagon, to: "/disputes" },
      { key: "documents", label: "Document desk", icon: FileText, to: "/documents" },
      { key: "callbacks", label: "Callbacks", icon: CalendarClock, to: "/callbacks" },
      { key: "upsell", label: "Upsell & leads", icon: Sparkles, to: "/upsell" },
      { key: "treatment", label: "Decision intelligence", icon: BrainCircuit, to: "/treatment" },
    ],
  },
  {
    label: "Compliance & QA",
    items: [
      { key: "audit", label: "Audit trail", icon: ClipboardList, to: "/audit" },
      { key: "compliance", label: "Compliance risk", icon: ShieldAlert, to: "/compliance" },
      { key: "consent", label: "Consent / DND", icon: UserCheck, to: "/consent" },
      { key: "redaction", label: "Redaction & export", icon: FileLock2, to: "/redaction" },
      { key: "qa", label: "QA scorecards", icon: ClipboardCheck, to: "/qa" },
      { key: "bot-analytics", label: "Bot analytics", icon: Activity, to: "/bot-analytics" },
    ],
  },
  {
    label: "Bot configuration",
    items: [
      { key: "knowledge-base", label: "Knowledge base", icon: BookOpen, to: "/knowledge-base" },
      { key: "prompt-studio", label: "Agent studio", icon: Bot, to: "/agent-studio" },
      { key: "sandbox", label: "Call sandbox", icon: Beaker, to: "/sandbox" },
      { key: "routing", label: "Routing / logic", icon: GitBranch, to: "/routing" },
      { key: "integrations", label: "Integrations", icon: Plug, to: "/integrations" },
      { key: "webhooks", label: "Webhooks", icon: Webhook, to: "/webhooks" },
      { key: "billing", label: "Billing & usage", icon: Receipt, to: "/billing" },
      { key: "roles", label: "Roles & access", icon: ShieldCheck, to: "/roles" },
    ],
  },
];

function itemKey(item: NavItem) {
  return item.key;
}

/** Shared nav-group rendering — reused by the desktop Sidebar and the mobile drawer (MobileNav). */
export function NavLinks({
  collapsed = false,
  pathname,
  onNavigate,
  query = "",
}: {
  collapsed?: boolean;
  pathname: string;
  onNavigate?: () => void;
  query?: string;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [box, setBox] = useState<{ top: number; height: number } | null>(null);
  const navRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Record<string, HTMLElement | null>>({});

  const activeKey = useMemo(() => {
    for (const group of groups) {
      for (const item of group.items) {
        if (item.to && pathname === item.to) return item.key;
      }
    }
    return null;
  }, [pathname]);

  const filteredGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return groups;
    return groups
      .map((group) => ({
        ...group,
        items: group.items.filter((item) => item.label.toLowerCase().includes(q)),
      }))
      .filter((group) => group.items.length > 0);
  }, [query]);

  const highlightKey = hovered ?? activeKey;

  useLayoutEffect(() => {
    const container = navRef.current;
    const target = highlightKey ? itemRefs.current[highlightKey] : null;
    if (!container || !target) {
      setBox(null);
      return;
    }
    const containerRect = container.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    setBox({
      top: targetRect.top - containerRect.top,
      height: targetRect.height,
    });
  }, [highlightKey, filteredGroups, collapsed]);

  const bindItemRef = useCallback((key: string, el: HTMLElement | null) => {
    itemRefs.current[key] = el;
  }, []);

  return (
    <div
      ref={navRef}
      onMouseLeave={() => setHovered(null)}
      className={cn("relative flex flex-col", collapsed ? "gap-050" : "gap-150")}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-0 rounded-[7px] bg-background-neutral-subtle-hovered"
        style={{
          top: box?.top ?? 0,
          height: box?.height ?? 0,
          opacity: box ? 1 : 0,
          transition:
            "top 220ms cubic-bezier(0.23,1,0.32,1), height 220ms cubic-bezier(0.23,1,0.32,1), opacity 150ms ease",
        }}
      />
      {filteredGroups.map((group) => (
        <div key={group.label}>
          {!collapsed && (
            <div className="px-150 pb-050 pt-025 text-body-micro font-medium uppercase tracking-[0.08em] text-text-subtlest">
              {group.label}
            </div>
          )}
          <div className="flex flex-col gap-px">
            {group.items.map((item) => {
              const isActive = Boolean(item.to && pathname === item.to);
              const Icon = item.icon;
              const key = itemKey(item);
              const className = cn(
                "group relative z-10 flex w-full items-center rounded-[7px] text-left transition-[color,transform] duration-150 active:scale-[0.96]",
                collapsed ? "justify-center px-0 py-150" : "gap-150 px-150 py-100",
                item.soon && "cursor-not-allowed opacity-60",
              );

              const body = (
                <>
                  <span className={cn("shrink-0", isActive ? "text-text" : "text-text-subtlest")}>
                    <Icon className="h-[13px] w-[13px]" strokeWidth={1.8} />
                  </span>
                  {!collapsed && (
                    <span
                      className={cn(
                        "min-w-0 flex-1 truncate text-body-small transition-colors duration-150",
                        isActive ? "font-medium text-text" : "text-text-subtle",
                      )}
                    >
                      {item.label}
                    </span>
                  )}
                  {!collapsed && item.soon && (
                    <span className="rounded-small bg-background-neutral-subtle px-075 py-025 text-body-micro font-semibold text-text-subtlest shadow-raised">
                      Soon
                    </span>
                  )}
                </>
              );

              const interaction = {
                onMouseEnter: () => setHovered(key),
                onFocus: () => setHovered(key),
                onBlur: () => setHovered(null),
              };

              if (item.to && !item.soon) {
                return (
                  <div
                    key={key}
                    ref={(el) => bindItemRef(key, el)}
                    onMouseEnter={interaction.onMouseEnter}
                  >
                    <Link
                      to={item.to}
                      title={item.label}
                      aria-label={item.label}
                      aria-current={isActive ? "page" : undefined}
                      className={className}
                      onClick={onNavigate}
                      onFocus={interaction.onFocus}
                      onBlur={interaction.onBlur}
                    >
                      {body}
                    </Link>
                  </div>
                );
              }

              return (
                <div
                  key={key}
                  ref={(el) => bindItemRef(key, el)}
                  className={className}
                  aria-disabled
                  title={item.label}
                  aria-label={item.label}
                  {...interaction}
                >
                  {body}
                </div>
              );
            })}
          </div>
        </div>
      ))}
      {filteredGroups.length === 0 && !collapsed && (
        <div className="px-150 py-100 text-body-small text-text-subtlest">No matching pages</div>
      )}
    </div>
  );
}

function WorkspaceRow({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  if (collapsed) {
    return (
      <button
        type="button"
        onClick={onToggle}
        className="focus-ring mb-100 grid w-full place-items-center rounded-medium p-050 transition-[background-color,transform] duration-100 hover:bg-background-neutral-subtle-hovered active:scale-[0.96]"
        aria-label="Expand sidebar"
        title="Expand sidebar"
      >
        <EqualizerMark size={28} />
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={onToggle}
      className="focus-ring mb-100 flex w-full items-center gap-150 rounded-medium p-050 text-left transition-[background-color,transform] duration-100 hover:bg-background-neutral-subtle-hovered active:scale-[0.96]"
      aria-label="Collapse sidebar"
      title="Collapse sidebar"
    >
      <EqualizerMark size={32} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-body-small font-medium leading-tight text-text">
          {BRAND.name}
        </span>
        <span className="block truncate text-body-tiny leading-tight text-text-subtlest">
          {BRAND.tenantLine}
        </span>
      </span>
      <svg
        width="12"
        height="12"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="shrink-0 text-text-subtlest"
      >
        <path d="M7 15l5 5 5-5M7 9l5-5 5 5" />
      </svg>
    </button>
  );
}

function QuickSearch({
  query,
  onQueryChange,
  inputRef,
}: {
  query: string;
  onQueryChange: (value: string) => void;
  inputRef: RefObject<HTMLInputElement | null>;
}) {
  return (
    <label className="mb-050 flex h-8 items-center gap-150 rounded-medium bg-surface-sunken px-150 shadow-raised">
      <svg
        width="12"
        height="12"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        className="shrink-0 text-text-subtlest"
      >
        <circle cx="11" cy="11" r="7" />
        <path d="M21 21l-4.3-4.3" />
      </svg>
      <input
        ref={inputRef}
        value={query}
        onChange={(event) => onQueryChange(event.target.value)}
        placeholder="Quick search"
        className="min-w-0 flex-1 bg-transparent text-body-small text-text outline-none placeholder:text-text-subtlest"
      />
      <kbd className="flex h-[18px] w-[18px] items-center justify-center rounded-[5px] bg-surface text-body-micro text-text-subtlest shadow-raised">
        /
      </kbd>
    </label>
  );
}

export function Sidebar() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { collapsed, toggle } = useSidebarUi();
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (collapsed) setQuery("");
  }, [collapsed]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
      if (collapsed) return;
      event.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [collapsed]);

  return (
    <aside
      className={cn(
        "hidden h-screen min-h-0 shrink-0 flex-col border-r border-border bg-surface transition-[width] duration-token-medium ease-token-out-practical lg:flex",
        collapsed ? "w-800" : "w-60",
      )}
    >
      <div className={cn("flex min-h-0 flex-1 flex-col", collapsed ? "p-100" : "p-150")}>
        <WorkspaceRow collapsed={collapsed} onToggle={toggle} />

        {!collapsed && (
          <div className="mb-100">
            <QuickSearch query={query} onQueryChange={setQuery} inputRef={searchRef} />
          </div>
        )}

        <nav className="min-h-0 flex-1 overflow-y-auto">
          <NavLinks collapsed={collapsed} pathname={pathname} query={query} />
        </nav>

        {collapsed ? (
          <button
            type="button"
            onClick={toggle}
            className="focus-ring mt-100 grid h-9 w-full place-items-center rounded-medium text-text-subtlest transition-[background-color,transform] duration-100 hover:bg-background-neutral-subtle-hovered hover:text-text active:scale-[0.96]"
            aria-label="Expand sidebar"
            title="Expand sidebar"
          >
            <ChevronsRight className="h-4 w-4" />
          </button>
        ) : (
          <div className="mt-100 px-150 pt-100 text-body-tiny text-text-subtlest">
            {BRAND.shortName} · v0.1
          </div>
        )}
      </div>
    </aside>
  );
}
