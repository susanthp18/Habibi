import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
} from "react";
import { StudioHeader } from "@/components/prompt-studio/StudioHeader";
import {
  FileText,
  Sparkles,
  Volume2,
  ShieldAlert,
  Workflow,
  Wrench,
  Lock,
  PhoneOutgoing,
  FlaskConical,
  GitBranch,
  Layers,
  Plug,
  Rocket,
  Cable,
  ScrollText,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type Tab =
  | "prompt"
  | "flow"
  | "graph"
  | "persona"
  | "voice"
  | "guardrails"
  | "tools"
  | "skills"
  | "connectors"
  | "policy"
  | "outbound"
  | "bindings"
  | "evals"
  | "ship"
  | "changelog";
/**
 * Tabs that own their own height and scroll internally, rather than growing a
 * page that scrolls.
 *
 * The distinction is real, not cosmetic. Flow is a canvas and Voice is a
 * browser-plus-inspector: both have a natural size of "the pane", and both
 * contain their own scrollable regions. Letting the page scroll underneath
 * them means two scrollbars competing for the same wheel gesture. The rest are
 * forms — they have a natural height, and the page should scroll them.
 */
export const FILL_TABS = new Set<Tab>(["flow", "voice"]);

const TABS: Array<{ key: Tab; label: string; icon: typeof FileText }> = [
  { key: "prompt", label: "System Prompt", icon: FileText },
  { key: "flow", label: "Flow", icon: Workflow },
  { key: "graph", label: "Agent graph", icon: GitBranch },
  { key: "persona", label: "Persona", icon: Sparkles },
  { key: "voice", label: "Voice (TTS)", icon: Volume2 },
  { key: "guardrails", label: "Guardrails", icon: ShieldAlert },
  { key: "tools", label: "Tools", icon: Wrench },
  { key: "skills", label: "Skills", icon: Layers },
  { key: "connectors", label: "Connectors", icon: Plug },
  { key: "policy", label: "Policy", icon: Lock },
  // Between Policy and Evals: after the constraints that bound outbound,
  // before the gate that proves it.
  { key: "outbound", label: "Outbound", icon: PhoneOutgoing },
  // After Voice, conceptually — but placed here so the tab strip keeps the
  // authoring tabs together and the operational ones after them. This is what
  // decides which engine the Voice tab's choice actually runs on.
  { key: "bindings", label: "Bindings", icon: Cable },
  { key: "evals", label: "Evals", icon: FlaskConical },
  { key: "ship", label: "Ship", icon: Rocket },
  // Last, because it is the record of everything the tabs before it did.
  // Named "Change log", not "History" — the header's History sheet lists
  // prompt versions, which is a different artefact with a different audience.
  { key: "changelog", label: "Change log", icon: ScrollText },
];

/** The studio's frame: app shell, header, and the scrollable tab strip. */
export function PromptStudioShell({
  header,
  banners,
  tab,
  setTab,
  children,
}: {
  header: ComponentProps<typeof StudioHeader>;
  banners?: ReactNode;
  tab: Tab;
  setTab: (tab: Tab) => void;
  children: ReactNode;
}) {
  const tabStripRef = useRef<HTMLDivElement>(null);
  // A scrollable strip can leave the selected tab off-screen — after a publish
  // lands on Ship, or when the tab is restored on a narrow window. Bring it
  // back into view rather than leaving the user looking at a strip with no
  // visible selection.
  // Which edges of the tab strip still have tabs hidden behind them. The strip
  // scrolls, but a bare scrollbar under a tab row reads as breakage rather than
  // as an affordance — and at 1024px it was the only clue that Evals and Ship
  // existed at all. A fade on the side that has more is the honest signal.
  const [tabEdges, setTabEdges] = useState({ atStart: true, atEnd: true });
  const syncTabEdges = useCallback(() => {
    const el = tabStripRef.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    setTabEdges({
      atStart: el.scrollLeft <= 1,
      // 1px of slack: sub-pixel layout widths leave scrollLeft a hair short of
      // max even when it is visually at the end, which would pin the fade on.
      atEnd: el.scrollLeft >= max - 1,
    });
  }, []);

  useEffect(() => {
    tabStripRef.current
      ?.querySelector<HTMLElement>(`[data-tab="${tab}"]`)
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
    syncTabEdges();
  }, [tab, syncTabEdges]);

  useEffect(() => {
    const el = tabStripRef.current;
    if (!el) return;
    syncTabEdges();
    const ro = new ResizeObserver(syncTabEdges);
    ro.observe(el);
    return () => ro.disconnect();
  }, [syncTabEdges]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <StudioHeader {...header} />

      {banners}

      {/* The twelve tabs need 1006px and the strip had `overflow-x: visible`
            and no scrolling, so below roughly 1030px the last of them simply
            hung outside the container with nothing to reach them by: on a
            1024px laptop, or this app in a split window, Evals and Ship were
            unclickable — including the only route to canary and publish
            settings. Scrolling the strip is the fix; `shrink-0` stops the
            labels compressing into ellipses instead. */}
      <div className="relative shrink-0 border-b border-border bg-surface">
        <div
          ref={tabStripRef}
          onScroll={syncTabEdges}
          className="scrollbar-none overflow-x-auto px-250"
        >
          <div className="flex w-max gap-050">
            {TABS.map((t) => {
              const Icon = t.icon;
              return (
                <button
                  key={t.key}
                  data-tab={t.key}
                  onClick={() => setTab(t.key)}
                  className={cn(
                    "inline-flex shrink-0 items-center gap-075 border-b-2 px-150 py-100 text-body-small",
                    tab === t.key
                      ? "border-border-brand font-semibold text-text-brand"
                      : "border-transparent text-text-subtle hover:text-text",
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {t.label}
                </button>
              );
            })}
          </div>
        </div>
        {/* Each fade appears only while that side actually has tabs behind
              it, so it reads as "there is more this way" rather than as a
              permanent decoration that means nothing. */}
        {!tabEdges.atStart && (
          <div className="pointer-events-none absolute inset-y-0 left-0 w-8 bg-gradient-to-r from-surface to-transparent" />
        )}
        {!tabEdges.atEnd && (
          <div className="pointer-events-none absolute inset-y-0 right-0 w-8 bg-gradient-to-l from-surface to-transparent" />
        )}
      </div>

      {children}
    </div>
  );
}
