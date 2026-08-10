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
        <div className="max-h-[70vh] overflow-y-auto pr-100">
          <Accordion type="multiple" className="space-y-050">
            {EVENT_CATEGORIES.map((cat) => (
              <AccordionItem key={cat} value={cat} className="rounded-medium border border-border px-150">
                <AccordionTrigger className="text-body font-semibold text-text">
                  {cat}
                  <span className="ml-100 text-body-small font-normal text-text-subtlest">
                    {EVENT_CATALOG.filter((e) => e.category === cat).length} events
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-150">
                    {EVENT_CATALOG.filter((e) => e.category === cat).map((e) => (
                      <div key={e.key}>
                        <div className="font-mono text-body-small font-semibold text-text-brand">
                          {e.key}
                        </div>
                        <p className="mb-050 text-body-small text-text-subtle">{e.description}</p>
                        <pre className="overflow-x-auto rounded-large bg-background-neutral p-100 font-mono text-body-small leading-snug text-text-code-default">
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
