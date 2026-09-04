import { Outlet } from "react-router-dom";

import { Sidebar } from "@/components/shell/Sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useLiveConnection } from "@/features/live/useLiveConnection";

/**
 * The app chrome — skip link, sidebar, main region — and, since ADR-0015, the
 * owner of the live WebSocket.
 *
 * The connection is mounted here rather than inside the Live Map (issue #105)
 * so that alert notifications and the live activity tail reach a tab sitting
 * on *any* FlightSite route, which is what SPEC §48 asks for. One socket per
 * tab: this component is mounted once, for the life of the session, and a
 * route change never touches it.
 *
 * Here rather than in `RootLayout` because the setup wizard renders outside
 * this shell (see `src/routes.tsx`). A session parked in the wizard therefore
 * holds no socket, which is the honest place for the line — nothing is worth
 * streaming to a receiver that has not been configured yet.
 */
export function AppShell() {
  useLiveConnection();

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
