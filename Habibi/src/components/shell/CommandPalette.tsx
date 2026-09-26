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
  Plug,
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
import { useCustomers } from "@/api/customers";
import { useWorkItems } from "@/api/workspace";
import { can, useMe } from "@/api/me";
import { useStudioAgents } from "@/api/voice-studio";
import { navigateWorkItem } from "@/lib/workspace-nav";
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
  { label: "Routing / Logic", to: "/routing", icon: GitBranch },
  {
    label: "Integrations",
    to: "/integrations",
    icon: Plug,
    keywords: "mcp connector vault gateway paylink",
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
  const { data: customers = [] } = useCustomers();
  const { data: workItems = [] } = useWorkItems("me");
  const pages = useMemo(
    () => (can(me, "perm-admin-write") ? PAGES : PAGES.filter((page) => page.to !== "/roles")),
    [me],
  );

  const { data: agents = [] } = useStudioAgents({ enabled: open && can(me, "perm-bot-read") });
  const customerHits = useMemo(() => customers.slice(0, 40), [customers]);
  const queueHits = useMemo(() => workItems.slice(0, 30), [workItems]);

  const go = (to: string) => {
    onOpenChange(false);
    void (navigate as (opts: { to: string }) => unknown)({ to });
  };

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder="Jump to page, customer, or queue item…" />
      <CommandList>
        <CommandEmpty>No matches.</CommandEmpty>
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
        <CommandGroup heading="My queue">
          {queueHits.length === 0 && (
            <CommandItem disabled value="empty-queue">
              No assigned items
            </CommandItem>
          )}
          {queueHits.map((w) => (
            <CommandItem
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
        <CommandGroup heading="Customers">
          {customerHits.map((c) => (
            <CommandItem
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
