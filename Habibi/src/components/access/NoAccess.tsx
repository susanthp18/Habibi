import { useState } from "react";
import { LogOut, ShieldOff } from "lucide-react";
import { toast } from "sonner";
import { forbiddenPermission, isUnauthorized } from "@/api/config";
import { useCreateAccessRequest } from "@/api/access-requests";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { signOut } from "@/lib/sso";

function permissionWords(permission: string | null): string | null {
  if (!permission) return null;
  return permission.replace(/^perm-/, "").replace(/-/g, " ");
}

export function NoAccess({ label, error }: { label: string; error?: unknown }) {
  const create = useCreateAccessRequest();
  const [reason, setReason] = useState("");
  const [sent, setSent] = useState(false);
  const permission = forbiddenPermission(error);
  const refusedSignIn = isUnauthorized(error);
  const pagePath = typeof window !== "undefined" ? window.location.pathname : "/";
  const needed = permissionWords(permission);

  const submit = () => {
    const trimmed = reason.trim();
    if (trimmed.length < 8) {
      toast.error("Say why you need this page (at least a sentence).");
      return;
    }
    void create
      .mutateAsync({ pagePath, reason: trimmed, permission })
      .then(() => {
        setSent(true);
        toast.success("Request sent. An admin will review it in Settings.");
      })
      .catch((err: Error) => {
        const message = err.message;
        if (message.includes("already_pending")) {
          setSent(true);
          toast.success("A request for this page is already waiting for an admin.");
          return;
        }
        toast.error(message);
      });
  };

  return (
    <div className="mx-auto max-w-lg space-y-200 rounded-medium border border-border bg-surface p-250">
      <div className="flex items-start gap-100">
        <ShieldOff className="mt-025 h-5 w-5 shrink-0 text-text-subtle" />
        <div>
          <div className="heading-small font-semibold">You don’t have access yet</div>
          <p className="mt-050 text-body-small text-text-subtle">
            {refusedSignIn
              ? "This session was not accepted. Sign out and sign in with Microsoft again."
              : needed
                ? `This page needs ${needed}. You can ask an admin to grant a role that includes it.`
                : `You’re signed in, but you don’t have a role that can open ${label}. Send a request with a reason so an admin can grant access.`}
          </p>
        </div>
      </div>
      {refusedSignIn ? (
        <Button type="button" variant="ghost" onClick={() => void signOut()}>
          <LogOut className="h-4 w-4" />
          Sign out
        </Button>
      ) : sent ? (
        <>
          <p className="text-body-small text-text-subtle">
            Request received. You’ll be able to open this page after an admin approves it — sign out
            and back in, or refresh, once they do.
          </p>
          <Button type="button" variant="ghost" onClick={() => void signOut()}>
            <LogOut className="h-4 w-4" />
            Sign out
          </Button>
        </>
      ) : (
        <form
          className="space-y-150"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <label className="block">
            <span className="mb-050 block text-body-small text-text-subtle">
              Why do you need access?
            </span>
            <Textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              maxLength={500}
              placeholder="A sentence an admin can act on — which work this unblocks."
            />
          </label>
          <div className="flex flex-wrap items-center gap-100">
            <Button type="submit" variant="primary" loading={create.isPending}>
              Request access
            </Button>
            <Button type="button" variant="ghost" onClick={() => void signOut()}>
              <LogOut className="h-4 w-4" />
              Sign out
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
