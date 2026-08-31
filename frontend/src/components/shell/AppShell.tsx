import { Outlet } from "react-router-dom";

import { Sidebar } from "@/components/shell/Sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";

export function AppShell() {
  return (
    <TooltipProvider delayDuration={200}>
      <a
        href="#main-content"
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:left-2 focus-visible:top-2 focus-visible:z-50 focus-visible:rounded-md focus-visible:bg-accent focus-visible:px-3 focus-visible:py-2 focus-visible:text-accent-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        Skip to main content
      </a>
      <div className="flex h-dvh w-full overflow-hidden bg-background text-foreground">
        <aside aria-label="Sidebar" className="h-full shrink-0">
          <Sidebar />
        </aside>
        <main id="main-content" className="h-full flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </TooltipProvider>
  );
}
