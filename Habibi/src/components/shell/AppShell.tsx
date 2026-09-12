import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { Toaster } from "@/components/ui/sonner";
import { SidebarUiProvider } from "./sidebar-ui";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <SidebarUiProvider>
      <div className="flex h-screen w-full overflow-hidden bg-surface">
        {/* Keyboard users land on the page's content, not on the sidebar's
            thirty links, on every navigation. */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:left-100 focus:top-100 focus:z-50 focus:rounded-medium focus:bg-surface focus:px-150 focus:py-075 focus:text-body-small focus:shadow-overlay"
        >
          Skip to content
        </a>
        <Sidebar />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <TopBar />
          <main id="main-content" className="min-h-0 flex-1 overflow-hidden">
            {children}
          </main>
        </div>
        <Toaster position="bottom-right" />
      </div>
    </SidebarUiProvider>
  );
}
