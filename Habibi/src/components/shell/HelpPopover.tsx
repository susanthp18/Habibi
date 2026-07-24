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
    blurb: "Tune prompts, knowledge, and routing that drive the voice agent.",
    links: [
      { label: "Prompt Studio", to: "/prompt-studio" },
      { label: "Knowledge Base", to: "/knowledge-base" },
      { label: "Call Sandbox", to: "/sandbox" },
    ],
  },
];

export function HelpPopover() {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="grid h-9 w-9 place-items-center rounded-md text-text-secondary transition-colors hover:bg-surface-sunken"
          aria-label="Help"
        >
          <HelpCircle className="h-4.5 w-4.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[340px] space-y-3 p-3">
        <div>
          <div className="text-[13px] font-semibold text-brand-navy">Help center</div>
          <div className="text-[11px] text-text-muted">Shortcuts and where to go for common tasks.</div>
        </div>

        <div className="rounded-md border border-[var(--border-token)] bg-surface-sunken px-2.5 py-2">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold text-text-primary">
            <Keyboard className="h-3.5 w-3.5" />
            Keyboard
          </div>
          <ul className="space-y-1 text-[11px] text-text-secondary">
            <li>
              <kbd className="rounded border border-[var(--border-token)] bg-white px-1 py-0.5 font-mono text-[10px]">
                ⌘K
              </kbd>{" "}
              /{" "}
              <kbd className="rounded border border-[var(--border-token)] bg-white px-1 py-0.5 font-mono text-[10px]">
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
            <div className="text-[12px] font-semibold text-text-primary">{s.title}</div>
            <p className="mt-0.5 text-[11px] text-text-secondary">{s.blurb}</p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {s.links.map((l) => (
                <Link
                  key={l.to}
                  to={l.to}
                  className="rounded-md border border-[var(--border-token)] bg-white px-2 py-0.5 text-[11px] font-medium text-brand-primary hover:bg-brand-tint"
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
