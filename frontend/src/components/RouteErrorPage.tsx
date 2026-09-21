import { useEffect } from "react";
import {
  isRouteErrorResponse,
  Link,
  useLocation,
  useNavigate,
  useRouteError,
} from "react-router-dom";

import { NAV_ITEMS } from "@/components/shell/nav-items";
import { Button } from "@/components/ui/button";

/** Longest-prefix-first: a detail route (`/aircraft/:icao`) and its list
 * route (`/aircraft`) share a label, and `/activity`/`/health` are real
 * pages that just aren't one of the seven `NAV_ITEMS` (see
 * `nav-items.ts`'s own note on why). Checked in order, so `/aircraft/:icao`
 * matches `/aircraft` correctly without a dedicated entry. */
const SECTION_LABELS: ReadonlyArray<{ prefix: string; label: string }> = [
  ...NAV_ITEMS.filter((item) => item.to !== "/").map((item) => ({
    prefix: item.to,
    label: item.label,
  })),
  { prefix: "/activity", label: "Activity" },
  { prefix: "/health", label: "Health" },
];

/** The page name a reader would recognise for a failed route, for the
 * boundary's heading (R0-01/R1-06/R3-04: "names the page that failed").
 * Falls back to the raw path for anything outside the known sections
 * (there shouldn't be one, short of a route added without an entry here). */
function describeFailedPage(pathname: string): string {
  if (pathname === "/") {
    return "Live Map";
  }
  const match = SECTION_LABELS.find((entry) =>
    pathname.startsWith(entry.prefix),
  );
  return match?.label ?? pathname;
}

interface RouteErrorPageProps {
  /**
   * True only for the outermost, chrome-free boundary (the root layout's
   * `errorElement` in `routes.tsx`) — used when the shell itself failed to
   * mount, so there is no sidebar/`<main>` to render inside and this has to
   * supply its own full-page frame. The in-chrome boundary (nested under
   * `AppShell`, the default) renders directly into the existing `<main>`.
   */
  standalone?: boolean;
}

/**
 * Route-level error fallback (R0-01, R1-06, R2-16, R3-04): used as both the
 * `errorElement` nested under `AppShell` (sidebar stays usable) and, with
 * `standalone`, the root layout's backstop for an error the shell boundary
 * itself couldn't catch (e.g. a throw in `AppShell` before its `<Outlet />`
 * renders). Names the page that failed, offers a reset ("Try again") and a
 * way back to the Live Map, and always logs to console — a thrown render
 * error must never look like nothing happened.
 */
export function RouteErrorPage({ standalone = false }: RouteErrorPageProps) {
  const error = useRouteError();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const pageLabel = describeFailedPage(pathname);

  useEffect(() => {
    console.error(
      `FlightSite: "${pageLabel}" (${pathname}) failed to render`,
      error,
    );
  }, [error, pageLabel, pathname]);

  const detail = isRouteErrorResponse(error)
    ? [error.status, error.statusText].filter(Boolean).join(" ")
    : error instanceof Error
      ? error.message
      : undefined;

  const content = (
    <div role="alert" className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="text-lg font-semibold">{pageLabel} ran into a problem</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Something went wrong while rendering this page. The rest of FlightSite
        should still work — try again, or head back to the Live Map.
      </p>
      {detail !== undefined && detail.length > 0 && (
        <p className="mt-3 rounded-md bg-muted px-3 py-2 font-mono text-xs text-muted-foreground">
          {detail}
        </p>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button type="button" onClick={() => navigate(0)}>
          Try again
        </Button>
        <Button type="button" variant="outline" asChild>
          <Link to="/">Go to Live Map</Link>
        </Button>
      </div>
    </div>
  );

  if (!standalone) {
    return content;
  }

  return (
    <div className="flex min-h-dvh w-full items-center justify-center bg-background text-foreground">
      {content}
    </div>
  );
}
