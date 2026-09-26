import { LogIn, LogOut } from "lucide-react";

import { Button } from "@/components/ui/button";
import { signInWithMicrosoft, signOut } from "@/lib/sso";

/**
 * The Microsoft session is present but the silent token frame did not return.
 * This is not a missing role. One action renews it and returns to this page.
 */
export function SessionRenewal() {
  return (
    <div className="mx-auto max-w-lg space-y-200 rounded-medium border border-border bg-surface p-250">
      <div>
        <div className="heading-small font-semibold">Sign in again to continue</div>
        <p className="mt-050 text-body-small text-text-subtle">
          PayInt could not refresh your Microsoft session, so this page is waiting. Your role has
          not changed. Continue with Microsoft and you will come back here.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-100">
        <Button type="button" variant="primary" onClick={() => void signInWithMicrosoft()}>
          <LogIn className="h-4 w-4" />
          Continue with Microsoft
        </Button>
        <Button type="button" variant="ghost" onClick={() => void signOut()}>
          <LogOut className="h-4 w-4" />
          Sign out
        </Button>
      </div>
    </div>
  );
}
