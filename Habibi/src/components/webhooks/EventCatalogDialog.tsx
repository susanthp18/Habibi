import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { EVENT_CATALOG, EVENT_CATEGORIES } from "@/data/webhooks-seed";

export function EventCatalogDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Event catalog</DialogTitle>
        </DialogHeader>
        <div className="max-h-[70vh] overflow-y-auto pr-2">
          <Accordion type="multiple" className="space-y-1">
            {EVENT_CATEGORIES.map((cat) => (
              <AccordionItem key={cat} value={cat} className="rounded-md border border-[var(--border-token)] px-3">
                <AccordionTrigger className="text-[13px] font-semibold text-brand-navy">
                  {cat}
                  <span className="ml-2 text-[11px] font-normal text-text-muted">
                    {EVENT_CATALOG.filter((e) => e.category === cat).length} events
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-3">
                    {EVENT_CATALOG.filter((e) => e.category === cat).map((e) => (
                      <div key={e.key}>
                        <div className="font-mono text-[12px] font-semibold text-brand-primary-dark">
                          {e.key}
                        </div>
                        <p className="mb-1 text-[12px] text-text-secondary">{e.description}</p>
                        <pre className="overflow-x-auto rounded bg-slate-950 p-2 font-mono text-[11px] leading-snug text-emerald-300">
{JSON.stringify(e.sample, null, 2)}
                        </pre>
                      </div>
                    ))}
                  </div>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>
      </DialogContent>
    </Dialog>
  );
}
