import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useContactPolicy } from "@/api/contact-policy";
import { useSendCustomerOutreach, type OutreachChannel } from "@/api/customers";
import { mutationErrorMessage } from "@/lib/mutation-errors";
import { idempotencyKey } from "@/lib/utils";
import type { Customer } from "@/api/types/customer360";

export function OutreachSheet({
  customer,
  open,
  onOpenChange,
}: {
  customer: Customer;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [channel, setChannel] = useState<OutreachChannel>("whatsapp");
  const [text, setText] = useState("");
  const send = useSendCustomerOutreach();
  const policy = useContactPolicy(open ? customer.id : undefined, {
    channel,
    purpose: "outreach",
  });
  const allowed = policy.data?.allowed !== false;
  const reason = policy.data?.reason;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Send message</SheetTitle>
          <SheetDescription>
            Creates a thread if this borrower does not have one, then uses the inbox send path.
          </SheetDescription>
        </SheetHeader>
        <div className="mt-200 space-y-150">
          <div className="space-y-050">
            <Label>Channel</Label>
            <Select value={channel} onValueChange={(v) => setChannel(v as OutreachChannel)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="whatsapp">WhatsApp</SelectItem>
                <SelectItem value="sms">SMS</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-050">
            <Label htmlFor="outreach-text">Message</Label>
            <Textarea
              id="outreach-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={5}
            />
          </div>
          {policy.isPending ? (
            <p className="text-body-small text-text-subtle">Checking contact policy…</p>
          ) : allowed ? (
            <p className="text-body-small text-text-subtle">
              Contact policy allows this channel now.
            </p>
          ) : (
            <p className="text-body-small text-text-danger">
              Contact policy refuses this send{reason ? ` (${reason})` : ""}.
            </p>
          )}
        </div>
        <SheetFooter className="mt-300">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={send.isPending || !text.trim()}
            onClick={() =>
              send.mutate(
                {
                  customerId: customer.id,
                  channel,
                  text: text.trim(),
                  idempotencyKey: idempotencyKey(`outreach-${customer.id}`),
                },
                {
                  onSuccess: () => {
                    toast.success("Message sent");
                    setText("");
                    onOpenChange(false);
                  },
                  onError: (err) => toast.error(mutationErrorMessage(err)),
                },
              )
            }
          >
            Send
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
