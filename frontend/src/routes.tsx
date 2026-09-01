import { lazy, Suspense } from "react";
import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "@/components/shell/AppShell";
import { RootLayout } from "@/components/shell/RootLayout";
import { SetupWizardPage } from "@/features/setup/SetupWizardPage";
import { ActivityPage } from "@/pages/ActivityPage";
import { AircraftDetailPage } from "@/pages/AircraftDetailPage";
import { AircraftPage } from "@/pages/AircraftPage";
import { AlertsPage } from "@/pages/AlertsPage";
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
/* eslint-enable react-refresh/only-export-components */

export const router = createBrowserRouter([
  {
    // Pathless: owns the first-run redirect and map-config sync, and
    // renders both the chrome'd app routes and the chrome-free setup
    // wizard as children (see `RootLayout`).
    element: <RootLayout />,
    children: [
      {
        path: "/",
        element: <AppShell />,
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
                  <p className="p-8 text-sm text-muted-foreground">
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
                  <p className="p-8 text-sm text-muted-foreground">
                    Loading receiver…
                  </p>
                }
              >
                <ReceiverPage />
              </Suspense>
            ),
          },
          { path: "alerts", element: <AlertsPage /> },
          { path: "settings", element: <SettingsPage /> },
          // Inside the shell but deliberately not in `NAV_ITEMS`: SPEC §10
          // fixes the sidebar at seven sections, so the activity feed's
          // fuller view is reached from the Live Map panel's "View all"
          // link, the way `sightings/:id` is reached from the log.
          { path: "activity", element: <ActivityPage /> },
        ],
      },
      // Outside AppShell's sidebar chrome: a full-screen wizard layout
      // (roadmap slice 018).
      { path: "/setup", element: <SetupWizardPage /> },
    ],
  },
]);
