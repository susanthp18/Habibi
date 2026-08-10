import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { Toaster } from "@/components/ui/sonner";
import { SidebarUiProvider } from "./sidebar-ui";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <SidebarUiProvider>
      <div className="flex h-screen w-full overflow-hidden bg-surface">
        <Sidebar />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <TopBar />
          <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
        </div>
        <Toaster position="bottom-right" />
      </div>
    </SidebarUiProvider>
  );
}
