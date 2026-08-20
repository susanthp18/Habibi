import { HelpCircle, Keyboard } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

const SECTIONS: {
  title: string;
  blurb: string;
  links: { label: string; to: string }[];
}[] = [
  {
    title: "My queue",
    blurb: "Open assigned disputes, callbacks, docs, and broken PTPs from the Workspace table.",
    links: [
      { label: "My Workspace", to: "/" },
      { label: "Disputes", to: "/disputes" },
      { label: "Callbacks", to: "/callbacks" },
    ],
  },
  {
    title: "Callbacks & DND",
    blurb: "Honour scheduled callbacks and respect preferred contact windows.",
    links: [
      { label: "Callback Manager", to: "/callbacks" },
      { label: "Consent / DND", to: "/consent" },
    ],
  },
  {
    title: "Compliance",
    blurb: "Review disclosure misses, redaction exports, and QA scorecards.",
    links: [
      { label: "Compliance Risk", to: "/compliance" },
      { label: "Audit Trail", to: "/audit" },
      { label: "QA Scorecards", to: "/qa" },
    ],
  },
  {
    title: "Bot config",
    blurb: "Tune agent cards, skills, knowledge, and routing that drive the voice agent.",
    links: [
      { label: "Agent studio", to: "/agent-studio" },
      { label: "Skills library", to: "/agent-studio/skills" },
      { label: "Knowledge Base", to: "/knowledge-base" },
      { label: "Call Sandbox", to: "/sandbox" },
      { label: "Integrations", to: "/integrations" },
    ],
  },
];

export function HelpPopover() {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="grid h-9 w-9 place-items-center rounded-medium text-text-subtle transition-colors hover:bg-surface-sunken"
          aria-label="Help"
        >
          <HelpCircle className="h-4.5 w-4.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[21.25rem] space-y-150 p-150">
        <div>
          <div className="text-body font-semibold text-text">Help center</div>
          <div className="text-body-small text-text-subtlest">Shortcuts and where to go for common tasks.</div>
        </div>

        <div className="rounded-medium border border-border bg-surface-sunken px-150 py-100">
          <div className="mb-050 flex items-center gap-075 text-body-small font-semibold text-text">
            <Keyboard className="h-3.5 w-3.5" />
            Keyboard
          </div>
          <ul className="space-y-050 text-body-small text-text-subtle">
            <li>
              <kbd className="rounded border border-border bg-surface px-050 py-025 font-mono text-body-small">
                ⌘K
              </kbd>{" "}
              /{" "}
              <kbd className="rounded border border-border bg-surface px-050 py-025 font-mono text-body-small">
                Ctrl+K
              </kbd>{" "}
              — jump to page, customer, or queue item
            </li>
            <li>Availability toggle — set Available / On break / Wrap-up (persists)</li>
            <li>Open on a queue row — opens the domain sheet for that item</li>
          </ul>
        </div>

        {SECTIONS.map((s) => (
          <div key={s.title}>
            <div className="text-body-small font-semibold text-text">{s.title}</div>
            <p className="mt-025 text-body-small text-text-subtle">{s.blurb}</p>
            <div className="mt-075 flex flex-wrap gap-075">
              {s.links.map((l) => (
                <Link
                  key={l.to}
                  to={l.to}
                  className="rounded-medium border border-border bg-surface px-100 py-025 text-body-small font-medium text-text-brand hover:bg-background-brand-subtlest"
                >
                  {l.label}
                </Link>
              ))}
            </div>
          </div>
        ))}
      </PopoverContent>
    </Popover>
  );
}
