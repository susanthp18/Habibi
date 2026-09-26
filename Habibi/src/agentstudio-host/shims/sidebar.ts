/**
 * `@/components/ui/sidebar` for the ported screens. The vendor app had its own
 * sidebar; inside Habibi there is one sidebar, the shell's, so the flow
 * editor's "toggle sidebar" button collapses that one for canvas room.
 */
import { useSidebarUi } from "@/components/shell/sidebar-ui";

export function useSidebar() {
  const { collapsed, setCollapsed, toggle } = useSidebarUi();
  return {
    state: collapsed ? ("collapsed" as const) : ("expanded" as const),
    open: !collapsed,
    setOpen: (open: boolean) => setCollapsed(!open),
    openMobile: false,
    setOpenMobile: (_open: boolean) => undefined,
    isMobile: false,
    toggleSidebar: toggle,
  };
}
