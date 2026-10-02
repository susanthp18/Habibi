import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import {
  Activity,
  AlertOctagon,
  BarChart3,
  Beaker,
  BookOpen,
  Bot,
  CalendarClock,
  ClipboardCheck,
  ClipboardList,
  FileLock2,
  FileText,
  GitBranch,
  HandCoins,
  Headphones,
  Home,
  LayoutGrid,
  Receipt,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  UserCheck,
  Users,
  Webhook,
  Moon,
  type LucideIcon,
  Rocket,
} from "lucide-react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { useCustomerSearch } from "@/api/customers";
import { useWorkItems } from "@/api/workspace";
import { can, useMe } from "@/api/me";
import { useStudioAgents } from "@/api/voice-studio";
import { navigateWorkItem } from "@/lib/workspace-nav";
import { useDebounced } from "@/lib/use-debounced";
import { toggleTheme } from "@/lib/theme";

const PAGES: {
  label: string;
  to: string;
  icon: LucideIcon;
  keywords?: string;
}[] = [
  { label: "My Workspace", to: "/", icon: Home, keywords: "home queue" },
  { label: "Conversation Inbox", to: "/inbox", icon: LayoutGrid },
  { label: "Handoff Hub", to: "/handoff", icon: Headphones },
  { label: "Floor Command", to: "/floor", icon: Activity },
  { label: "Executive Dashboard", to: "/dashboard", icon: BarChart3 },
  { label: "Customer 360", to: "/customers", icon: Users },
  { label: "Promise-to-Pay", to: "/promises", icon: HandCoins, keywords: "ptp" },
  { label: "Disputes Queue", to: "/disputes", icon: AlertOctagon },
  { label: "Document Desk", to: "/documents", icon: FileText },
  { label: "Callbacks", to: "/callbacks", icon: CalendarClock },
  { label: "Upsell & Leads", to: "/upsell", icon: Sparkles },
  { label: "Audit Trail", to: "/audit", icon: ClipboardList },
  { label: "Compliance Risk", to: "/compliance", icon: ShieldAlert },
  { label: "Consent / DND", to: "/consent", icon: UserCheck },
  { label: "Redaction & Export", to: "/redaction", icon: FileLock2 },
  { label: "QA Scorecards", to: "/qa", icon: ClipboardCheck },
  { label: "Bot Analytics", to: "/bot-analytics", icon: Activity },
  { label: "Voice agents", to: "/studio", icon: Bot, keywords: "voice studio workflow agent" },
  { label: "Knowledge base", to: "/studio/files", icon: BookOpen, keywords: "kb documents files" },
  { label: "Guardrails", to: "/studio/guardrails", icon: ShieldAlert },
  { label: "Checks", to: "/studio/checks", icon: Beaker, keywords: "eval test" },
  {
    label: "Agent routing",
    to: "/studio/routing",
    icon: GitBranch,
    keywords: "inbound whatsapp objective",
  },
  {
    label: "Releases",
    to: "/studio/releases",
    icon: Rocket,
    keywords: "publish rollback changelog version",
  },
  {
    label: "Pending approvals",
    to: "/floor",
    icon: ClipboardCheck,
    keywords: "approve hitl clerk",
  },
  { label: "Webhooks", to: "/webhooks", icon: Webhook },
  { label: "Billing & Usage", to: "/billing", icon: Receipt },
  { label: "Roles & access", to: "/roles", icon: ShieldCheck },
  { label: "Settings", to: "/settings", icon: Settings, keywords: "theme invite appearance" },
];

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function CommandPalette({ open, onOpenChange }: Props) {
  const navigate = useNavigate();
  const { data: me } = useMe();
  const [search, setSearch] = useState("");
  // Customers and queue items are matched on the server across everything,
  // not within a first page, once the operator pauses typing.
  const q = useDebounced(search);
  const customers = useCustomerSearch(q, open);
  const queue = useWorkItems({ scope: "me", q, limit: 30 }, { enabled: open });
  const customerHits = customers.data ?? [];
  const queueHits = queue.data ?? [];
  // Typed but not yet asked, or asked and not yet answered.
  const searching = search.trim() !== q.trim() || customers.isFetching || queue.isFetching;
  const pages = useMemo(
    () => (can(me, "perm-admin-write") ? PAGES : PAGES.filter((page) => page.to !== "/roles")),
    [me],
  );

  const { data: agents = [] } = useStudioAgents({ enabled: open && can(me, "perm-bot-read") });

  const go = (to: string) => {
    onOpenChange(false);
    void (navigate as (opts: { to: string }) => unknown)({ to });
  };

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput
        value={search}
        onValueChange={setSearch}
        placeholder="Jump to page, customer, or queue item…"
      />
      <CommandList>
        {/* cmdk counts only what it matched itself, not the server's hits. */}
        {!searching && !customerHits.length && !queueHits.length && (
          <CommandEmpty>No matches.</CommandEmpty>
        )}
        <CommandGroup heading="Appearance">
          <CommandItem
            value="toggle night mode dark theme light"
            onSelect={() => {
              toggleTheme();
              onOpenChange(false);
            }}
          >
            <Moon className="h-4 w-4 text-text-brand" />
            <span>Toggle night mode</span>
          </CommandItem>
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Pages">
          {pages.map((p) => {
            const Icon = p.icon;
            return (
              <CommandItem
                key={`${p.to}-${p.label}`}
                value={`${p.label} ${p.keywords ?? ""} ${p.to}`}
                onSelect={() => go(p.to)}
              >
                <Icon className="h-4 w-4 text-text-brand" />
                <span>{p.label}</span>
              </CommandItem>
            );
          })}
        </CommandGroup>
        {agents.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Voice agents">
              {agents.map((a) => (
                <CommandItem
                  key={`agent-${a.id}`}
                  value={`voice agent ${a.name} ${a.id}`}
                  onSelect={() => {
                    onOpenChange(false);
                    void navigate({
                      to: "/studio/workflow/$workflowId",
                      params: { workflowId: String(a.id) },
                    });
                  }}
                >
                  <Bot className="h-4 w-4 text-text-brand" />
                  <span className="truncate">{a.name}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
        <CommandSeparator />
        {/* Queue items and customers were matched on the server, across every
            account of a customer; cmdk's filter sees only the text shown and
            would drop a match on a secondary account. Force them visible. */}
        <CommandGroup heading="My queue" forceMount>
          <SearchStatus
            query={queue}
            hits={queueHits.length}
            searching={searching}
            what={q.trim() ? "matching queue items" : "assigned items"}
          />
          {queueHits.map((w) => (
            <CommandItem
              forceMount
              key={`${w.entityType}-${w.id}`}
              value={`${w.customer} ${w.accountId} ${w.id} ${w.type} ${w.detail}`}
              onSelect={() => {
                onOpenChange(false);
                navigateWorkItem(navigate, w);
              }}
            >
              <span className="font-mono text-body-small text-text-subtlest">{w.id}</span>
              <span className="truncate">
                {w.customer} · {w.type}
              </span>
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Customers" forceMount>
          <SearchStatus
            query={customers}
            hits={customerHits.length}
            searching={searching}
            what="matching customers"
          />
          {customerHits.map((c) => (
            <CommandItem
              forceMount
              key={c.id}
              value={`${c.name} ${c.accountId} ${c.id}`}
              onSelect={() => {
                onOpenChange(false);
                void navigate({ to: "/customers/$customerId", params: { customerId: c.id } });
              }}
            >
              <Users className="h-4 w-4 text-text-brand" />
              <span className="truncate">
                {c.name} · {c.accountId}
              </span>
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}

/** A server-search group's state: failed (select to retry), searching, or empty. */
function SearchStatus({
  query,
  hits,
  searching,
  what,
}: {
  query: { isError: boolean; refetch: () => unknown };
  hits: number;
  searching: boolean;
  what: string;
}) {
  if (query.isError) {
    return (
      <CommandItem forceMount value={`retry ${what}`} onSelect={() => void query.refetch()}>
        Couldn’t search {what.replace(/^matching /, "")} — select to retry
      </CommandItem>
    );
  }
  if (hits > 0) return null;
  return (
    <CommandItem forceMount disabled value={`status ${what}`}>
      {searching ? "Searching…" : `No ${what}`}
    </CommandItem>
  );
}

/** Global ⌘K / Ctrl+K listener + controlled dialog. */
export function useCommandPalette() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return { open, setOpen };
}
