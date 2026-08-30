import { Menu } from "lucide-react";
import { useRouterState } from "@tanstack/react-router";
import { useState } from "react";

import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { EqualizerMark } from "@/components/brand/EqualizerMark";
import { BRAND } from "@/lib/brand";
import { NavLinks } from "@/components/shell/Sidebar";

/*
 * Design.md Responsive rules explicitly forbid hiding navigation on small screens — the desktop
 * Sidebar disappears below `lg` with no fallback, so this drawer (built on the existing Sheet
 * primitive) is the required replacement, not an optional nicety.
 */
export function MobileNav() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [open, setOpen] = useState(false);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <button
          type="button"
          className="focus-ring grid h-9 w-9 shrink-0 place-items-center rounded-medium text-text-subtle hover:bg-background-neutral-subtle-hovered lg:hidden"
          aria-label="Open navigation menu"
        >
          <Menu className="h-4 w-4" />
        </button>
      </SheetTrigger>
      <SheetContent side="left" className="w-[17.5rem] bg-surface p-0">
        <SheetHeader className="flex-row items-center gap-150 px-150 pt-150">
          <EqualizerMark size={28} />
          <div className="min-w-0 flex-1 text-left">
            <SheetTitle className="truncate text-body-small font-medium leading-tight text-text">
              {BRAND.name}
            </SheetTitle>
            <p className="truncate text-body-tiny leading-tight text-text-subtlest">
              {BRAND.tenantLine}
            </p>
          </div>
        </SheetHeader>
        <nav className="min-h-0 flex-1 overflow-y-auto px-150 pb-150 pt-100">
          <NavLinks pathname={pathname} onNavigate={() => setOpen(false)} />
        </nav>
      </SheetContent>
    </Sheet>
  );
}
