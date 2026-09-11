export function NotAuthoredNotice({ what }: { what: string }) {
  return (
    <div className="rounded-medium border border-dashed border-border p-200 text-body-small text-text-subtle">
      This version has no Agent Card, so {what} cannot be edited here. Clone a card from the fleet
      index, or publish once to stamp the first-party defaults onto this bot.
    </div>
  );
}
