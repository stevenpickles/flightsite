import { lazy, Suspense } from "react";
import { createBrowserRouter } from "react-router-dom";

import { NotFoundPage } from "@/components/NotFoundPage";
import { RouteErrorPage } from "@/components/RouteErrorPage";
import { AppShell } from "@/components/shell/AppShell";
import { RootLayout } from "@/components/shell/RootLayout";
import { SetupWizardPage } from "@/features/setup/SetupWizardPage";
import { ActivityPage } from "@/pages/ActivityPage";
import { AircraftDetailPage } from "@/pages/AircraftDetailPage";
import { AircraftPage } from "@/pages/AircraftPage";
import { AlertsPage } from "@/pages/AlertsPage";
import { HealthPage } from "@/pages/HealthPage";
import { LiveMapPage } from "@/pages/LiveMapPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SightingDetailPage } from "@/pages/SightingDetailPage";
import { SightingsPage } from "@/pages/SightingsPage";

/**
 * The Analytics and Receiver pages both pull in ECharts (roadmap slices 032
 * and 034), which the Live Map — the app's index route, and the one every
 * session loads first — has no use for. Route-level `lazy` keeps that chunk
 * out of the initial bundle entirely; it only downloads when a user actually
 * navigates to one of these two.
 */
/* eslint-disable react-refresh/only-export-components -- this route config
   module's only real export is `router`; the lazy-loaded component bindings
   have to live beside the route tree that references them. */
const AnalyticsPage = lazy(() =>
  import("@/pages/AnalyticsPage").then((module) => ({
    default: module.AnalyticsPage,
  })),
);
const ReceiverPage = lazy(() =>
  import("@/pages/ReceiverPage").then((module) => ({
    default: module.ReceiverPage,
  })),
);
/**
 * Same reasoning, and the same "reached from Receiver/Health, not an
 * eighth sidebar section" precedent (roadmap slice 077): `FeedersPage`
 * pulls in ECharts for its metric charts, so it is kept out of the
 * initial bundle the same way.
 */
const FeedersPage = lazy(() =>
  import("@/pages/FeedersPage").then((module) => ({
    default: module.FeedersPage,
  })),
);
/* eslint-enable react-refresh/only-export-components */

export const router = createBrowserRouter([
  {
    // Pathless: owns the first-run redirect and map-config sync, and
    // renders both the chrome'd app routes and the chrome-free setup
    // wizard as children (see `RootLayout`). `errorElement` here is the
    // chrome-free backstop (R0-01/R1-06/R3-04): it only fires for an error
    // this route tree's own element threw (`RootLayout`) or one that
    // reached this far because nothing closer caught it — in particular a
    // throw from `AppShell` itself, before its `<Outlet />` ever renders,
    // which is the one failure the in-chrome boundary below cannot catch
    // since it depends on `AppShell` having mounted.
    element: <RootLayout />,
    errorElement: <RouteErrorPage standalone />,
    children: [
      {
        path: "/",
        element: <AppShell />,
        children: [
          {
            // Pathless: every page inside the shell shares this one
            // `errorElement` (R0-01/R1-06/R2-16/R3-04). Nesting it here,
            // one level *under* `AppShell` rather than on the `/` route
            // itself, is what keeps the sidebar mounted and usable on a
            // render-time throw — React Router replaces the element of
            // whichever route actually owns the boundary, and `AppShell`
            // owns the `/` route, not this one.
            errorElement: <RouteErrorPage />,
            children: [
              { index: true, element: <LiveMapPage /> },
              { path: "aircraft", element: <AircraftPage /> },
              { path: "aircraft/:icao", element: <AircraftDetailPage /> },
              { path: "sightings", element: <SightingsPage /> },
              { path: "sightings/:id", element: <SightingDetailPage /> },
              {
                path: "analytics",
                element: (
                  <Suspense
                    fallback={
                      <p
                        role="status"
                        className="p-8 text-sm text-muted-foreground"
                      >
                        Loading analytics…
                      </p>
                    }
                  >
                    <AnalyticsPage />
                  </Suspense>
                ),
              },
              {
                path: "receiver",
                element: (
                  <Suspense
                    fallback={
                      <p
                        role="status"
                        className="p-8 text-sm text-muted-foreground"
                      >
                        Loading receiver…
                      </p>
                    }
                  >
                    <ReceiverPage />
                  </Suspense>
                ),
              },
              // A sub-route of Receiver, not its own top-level path (roadmap
              // slice 077) — but it is a `NAV_ITEMS` sidebar entry since
              // roadmap slice 082 (issue #225), alongside `/activity` and
              // `/health` below, in addition to the Receiver and Health
              // pages' own in-page links from before then.
              {
                path: "receiver/feeders",
                element: (
                  <Suspense
                    fallback={
                      <p
                        role="status"
                        className="p-8 text-sm text-muted-foreground"
                      >
                        Loading feeders…
                      </p>
                    }
                  >
                    <FeedersPage />
                  </Suspense>
                ),
              },
              { path: "alerts", element: <AlertsPage /> },
              { path: "settings", element: <SettingsPage /> },
              // A `NAV_ITEMS` sidebar entry since roadmap slice 082 (issue
              // #225) — before that it was reachable only from the Live Map
              // panel's "View all" link, the way `sightings/:id` is reached
              // from the log; that link still works, it is just no longer
              // the only way in.
              { path: "activity", element: <ActivityPage /> },
              // Same history for the health area (roadmap slice 042, SPEC
              // §67's "reachable without SSH"): a `NAV_ITEMS` entry since
              // slice 082, on top of the Receiver and Settings pages' own
              // links.
              { path: "health", element: <HealthPage /> },
              // Catch-all (R0-02/R2-16): any path under the shell that
              // matches none of the above. Last child so it never shadows
              // a real route.
              { path: "*", element: <NotFoundPage /> },
            ],
          },
        ],
      },
      // Outside AppShell's sidebar chrome: a full-screen wizard layout
      // (roadmap slice 018).
      { path: "/setup", element: <SetupWizardPage /> },
    ],
  },
]);
