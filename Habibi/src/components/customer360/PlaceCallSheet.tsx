import { useRef } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { usePlaceCall } from "@/api/outbound";
import { useContactPolicy } from "@/api/contact-policy";
import { mutationErrorMessage } from "@/lib/mutation-errors";
import { idempotencyKey } from "@/lib/utils";
import type { Customer } from "@/api/types/customer360";

export function PlaceCallSheet({
  customer,
  open,
  onOpenChange,
}: {
  customer: Customer;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const placeCall = usePlaceCall();
  const dialKey = useRef(idempotencyKey(`crm-dial-${customer.id}`));
  const policy = useContactPolicy(open ? customer.id : undefined, {
    channel: "voice",
    purpose: "outreach",
  });
  const allowed = policy.data?.allowed !== false;
  const reason = policy.data?.reason;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Place call</SheetTitle>
          <SheetDescription>
            Through the dial owner. A 409 is the contact gate working, not a failed click.
          </SheetDescription>
        </SheetHeader>
        <div className="mt-200 space-y-150 text-body-small">
          <div>
            <div className="font-semibold text-text">{customer.name}</div>
            <div className="tabular-nums text-text-subtle">{customer.contact.phonePrimary}</div>
          </div>
          {policy.isPending ? (
            <p className="text-text-subtle">Checking contact policy…</p>
          ) : allowed ? (
            <p className="text-text-subtle">Contact policy allows a voice outreach right now.</p>
          ) : (
            <p className="text-text-danger">
              Contact policy refuses this call{reason ? ` (${reason})` : ""}.
            </p>
          )}
        </div>
        <SheetFooter className="mt-300">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={placeCall.isPending || !customer.contact.phonePrimary}
            onClick={() =>
              placeCall.mutate(
                {
                  customerId: customer.id,
                  accountId: customer.accountId || undefined,
                  phone: customer.contact.phonePrimary,
                  idempotencyKey: dialKey.current,
                },
                {
                  onSuccess: () => {
                    dialKey.current = idempotencyKey(`crm-dial-${customer.id}`);
                    toast.success("Call placed");
                    onOpenChange(false);
                  },
                  onError: (err) => toast.error(mutationErrorMessage(err)),
                },
              )
            }
          >
            Place call
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
