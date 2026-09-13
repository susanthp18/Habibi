/** Holds -- GET/POST /treatment/holds and the place/release dialogs. */
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Plus, ShieldOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Lozenge } from "@/components/ui/lozenge";
import { SectionMessage } from "@/components/ui/section-message";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  humanise,
  HOLD_KINDS,
  HOLD_SOURCES,
  useCreateTreatmentHold,
  useReleaseTreatmentHold,
  useTreatmentHolds,
  type HoldKind,
  type HoldSource,
  type TreatmentHold,
} from "@/api/treatment";

// ---------------------------------------------------------------------------
// Shared state scaffolding
//
// Loading, empty and error are rendered by one component so no section can
// quietly skip one. The error branch renders INSTEAD of the data — a failed
// live call must never fall through to a half-populated table, because a
// plausible-looking number with no backend behind it is worse than a gap.
// ---------------------------------------------------------------------------
import { HOLD_TONE, Panel, StateGate } from "./chrome";
import { fmtDateTime } from "@/lib/format";

export function HoldsTab() {
  const [activeOnly, setActiveOnly] = useState(true);
  const [placeOpen, setPlaceOpen] = useState(false);
  const [releasing, setReleasing] = useState<TreatmentHold | null>(null);
  const holds = useTreatmentHolds({ activeOnly });

  return (
    <div className="flex flex-col gap-200">
      <Panel
        title="Collections holds"
        description="The veto the treatment engine reads. A hold stops outreach before any action is scored."
        actions={
          <div className="flex shrink-0 items-center gap-150">
            <div className="flex items-center gap-100">
              <Label
                id="holds-active-only-label"
                htmlFor="holds-active-only"
                className="text-body-small text-text-subtle"
              >
                Active only
              </Label>
              <Switch
                id="holds-active-only"
                aria-labelledby="holds-active-only-label"
                checked={activeOnly}
                onCheckedChange={setActiveOnly}
              />
            </div>
            <Button size="sm" variant="primary" onClick={() => setPlaceOpen(true)}>
              <Plus className="mr-075 h-3.5 w-3.5" /> Place a hold
            </Button>
          </div>
        }
      >
        <StateGate
          query={holds}
          loadingLabel="Loading holds"
          isEmpty={(d) => d.length === 0}
          emptyTitle={activeOnly ? "No active holds" : "No holds on record"}
          emptyBody={
            activeOnly
              ? "Nothing is vetoing outreach right now. Turn off “active only” to see released holds."
              : "No hold has ever been placed for this tenant."
          }
          emptyIcon={ShieldOff}
        >
          {(rows) => (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Borrower</TableHead>
                  <TableHead>Kind</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Placed</TableHead>
                  <TableHead>SLA due</TableHead>
                  <TableHead>Expires</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((h) => (
                  <TableRow key={h.id}>
                    <TableCell>
                      <span className="text-body text-text">{h.customerName ?? h.customerId}</span>
                      <span className="block text-body-tiny tabular-nums text-text-subtlest">
                        {h.accountId ?? h.customerId}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Lozenge tone={HOLD_TONE[h.kind] ?? "neutral"}>{humanise(h.kind)}</Lozenge>
                    </TableCell>
                    <TableCell className="max-w-xs">
                      <span className="block truncate text-body-small text-text-subtle">
                        {h.reason ?? "—"}
                      </span>
                    </TableCell>
                    <TableCell className="text-body-small text-text-subtle">
                      {humanise(h.source)}
                      {h.placedBy ? (
                        <span className="block text-body-tiny text-text-subtlest">
                          {h.placedBy}
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums text-text-subtle">
                      {fmtDateTime(h.startsAt)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums text-text-subtle">
                      {fmtDateTime(h.slaDueAt)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums text-text-subtle">
                      {h.expiresAt ? fmtDateTime(h.expiresAt) : "no expiry"}
                    </TableCell>
                    <TableCell>
                      {h.active ? (
                        <Lozenge tone="success">Active</Lozenge>
                      ) : (
                        <Lozenge tone="neutral">Released</Lozenge>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {h.active ? (
                        <Button size="sm" variant="outline" onClick={() => setReleasing(h)}>
                          Release
                        </Button>
                      ) : (
                        <span className="text-body-small text-text-subtlest">
                          {fmtDateTime(h.releasedAt)}
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </StateGate>
      </Panel>

      <PlaceHoldDialog open={placeOpen} onOpenChange={setPlaceOpen} />
      <ReleaseHoldDialog hold={releasing} onOpenChange={(v) => !v && setReleasing(null)} />
    </div>
  );
}

export function PlaceHoldDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const create = useCreateTreatmentHold();
  const [customerId, setCustomerId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [kind, setKind] = useState<HoldKind>("hardship");
  const [source, setSource] = useState<HoldSource>("manual");
  const [reason, setReason] = useState("");
  const [expiresAt, setExpiresAt] = useState("");

  const reset = () => {
    setCustomerId("");
    setAccountId("");
    setKind("hardship");
    setSource("manual");
    setReason("");
    setExpiresAt("");
  };

  const canSubmit = customerId.trim().length > 0 && !create.isPending;

  const submit = () => {
    if (!canSubmit) return;
    create.mutate(
      {
        customerId: customerId.trim(),
        accountId: accountId.trim() || null,
        kind,
        source,
        reason: reason.trim() || null,
        // <input type="date"> gives a bare date; the column is a timestamptz.
        expiresAt: expiresAt ? new Date(`${expiresAt}T00:00:00`).toISOString() : null,
      },
      {
        onSuccess: (hold) => {
          toast.success(`${humanise(hold.kind)} hold in place`, {
            description: `${hold.customerName ?? hold.customerId} — outreach is vetoed until it is released.`,
          });
          reset();
          onOpenChange(false);
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : "Could not place the hold"),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Place a hold</DialogTitle>
          <DialogDescription>
            Stops collections outreach for this borrower. Re-placing an active hold of the same kind
            returns the existing one rather than creating a second.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-150">
          <div className="flex flex-col gap-050">
            <Label htmlFor="hold-customer">Borrower id</Label>
            <Input
              id="hold-customer"
              value={customerId}
              placeholder="priya-sharma"
              onChange={(e) => setCustomerId(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-050">
            <Label htmlFor="hold-account">Account id (optional)</Label>
            <Input
              id="hold-account"
              value={accountId}
              placeholder="AC-90881 — leave blank to hold every account"
              onChange={(e) => setAccountId(e.target.value)}
            />
          </div>

          <div className="grid grid-cols-2 gap-150">
            <div className="flex flex-col gap-050">
              <Label htmlFor="hold-kind">Kind</Label>
              <Select value={kind} onValueChange={(v) => setKind(v as HoldKind)}>
                <SelectTrigger id="hold-kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {HOLD_KINDS.map((k) => (
                    <SelectItem key={k} value={k}>
                      {humanise(k)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-050">
              <Label htmlFor="hold-source">Source</Label>
              <Select value={source} onValueChange={(v) => setSource(v as HoldSource)}>
                <SelectTrigger id="hold-source">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {HOLD_SOURCES.map((s) => (
                    <SelectItem key={s} value={s}>
                      {humanise(s)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-col gap-050">
            <Label htmlFor="hold-expires">Expires (optional)</Label>
            <Input
              id="hold-expires"
              type="date"
              value={expiresAt}
              onChange={(e) => setExpiresAt(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-050">
            <Label htmlFor="hold-reason">Reason</Label>
            <Textarea
              id="hold-reason"
              value={reason}
              rows={3}
              placeholder="What the borrower said, or which desk asked for this."
              onChange={(e) => setReason(e.target.value)}
            />
          </div>

          {kind === "legal" || kind === "dispute" ? (
            <SectionMessage
              variant="information"
              icon={ShieldOff}
              title={
                kind === "legal"
                  ? "A legal hold still permits a statutory notice"
                  : "A dispute hold still permits a specialist call about the dispute"
              }
            >
              Every other kind stops outreach entirely.
            </SectionMessage>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!canSubmit} onClick={submit}>
            {create.isPending ? "Placing…" : "Place hold"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ReleaseHoldDialog({
  hold,
  onOpenChange,
}: {
  hold: TreatmentHold | null;
  onOpenChange: (v: boolean) => void;
}) {
  const release = useReleaseTreatmentHold();
  const [reason, setReason] = useState("");
  const label = useMemo(
    () => (hold ? `${humanise(hold.kind)} hold on ${hold.customerName ?? hold.customerId}` : ""),
    [hold],
  );

  const submit = () => {
    if (!hold) return;
    release.mutate(
      { holdId: hold.id, reason: reason.trim() || null },
      {
        onSuccess: () => {
          toast.success("Hold released", {
            description: `${label} — the engine may schedule outreach again.`,
          });
          setReason("");
          onOpenChange(false);
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : "Could not release the hold"),
      },
    );
  };

  return (
    <Dialog open={hold !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Release this hold</DialogTitle>
          <DialogDescription>
            {label ? `${label}. ` : ""}Outreach becomes possible again as soon as this is lifted.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-050">
          <Label htmlFor="release-reason">Reason (optional)</Label>
          <Textarea
            id="release-reason"
            value={reason}
            rows={3}
            placeholder="Why the hold no longer applies."
            onChange={(e) => setReason(e.target.value)}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="danger" disabled={release.isPending} onClick={submit}>
            {release.isPending ? "Releasing…" : "Release hold"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
