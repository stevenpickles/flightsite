import { Link, useLocation } from "react-router-dom";

import { NAV_ITEMS } from "@/components/shell/nav-items";

/**
 * Catch-all (`{ path: "*" }`, R0-02/R2-16) for a path that matches no route
 * at all — a mistyped URL or a stale bookmark. Rendered inside `AppShell`
 * (nested under the same wrapping route as {@link RouteErrorPage}), so the
 * sidebar stays usable; this is deliberately a plain "not found", not an
 * error, since nothing actually threw.
 *
 * Lists the seven primary sections directly rather than only pointing at
 * the sidebar, matching the two in-app 404s this mirrors
 * (`AircraftDetailPage`'s invalid-ICAO state, `SightingDetailPage`'s
 * missing-id state) which name the specific thing that wasn't found.
 */
export function NotFoundPage() {
  const { pathname } = useLocation();

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="text-lg font-semibold">Page not found</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        There's no page at <span className="font-mono">{pathname}</span>.
      </p>
      <nav aria-label="FlightSite sections" className="mt-6">
        <p className="text-sm font-medium text-foreground">
          Go to one of FlightSite's sections instead:
        </p>
        <ul className="mt-3 flex flex-col gap-2">
          {NAV_ITEMS.map((item) => (
            <li key={item.to}>
              <Link
                to={item.to}
                className="text-sm text-accent underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                {item.label}
              </Link>
              <span className="ml-2 text-sm text-muted-foreground">
                {item.description}
              </span>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
