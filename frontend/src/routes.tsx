import { lazy, Suspense } from "react";
import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "@/components/shell/AppShell";
import { RootLayout } from "@/components/shell/RootLayout";
import { SetupWizardPage } from "@/features/setup/SetupWizardPage";
import { AircraftDetailPage } from "@/pages/AircraftDetailPage";
import { AircraftPage } from "@/pages/AircraftPage";
import { AlertsPage } from "@/pages/AlertsPage";
import { LiveMapPage } from "@/pages/LiveMapPage";
import { ReceiverPage } from "@/pages/ReceiverPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SightingDetailPage } from "@/pages/SightingDetailPage";
import { SightingsPage } from "@/pages/SightingsPage";

/**
 * The Analytics page pulls in ECharts (roadmap slice 032), which the Live
 * Map — the app's index route, and the one every session loads first — has
 * no use for. Route-level `lazy` keeps that chunk out of the initial bundle
 * entirely; it only downloads when a user actually navigates here.
 */
/* eslint-disable react-refresh/only-export-components -- this route config
   module's only real export is `router`; the lazy-loaded component binding
   has to live beside the route tree that references it. */
const AnalyticsPage = lazy(() =>
  import("@/pages/AnalyticsPage").then((module) => ({
    default: module.AnalyticsPage,
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
          { path: "receiver", element: <ReceiverPage /> },
          { path: "alerts", element: <AlertsPage /> },
          { path: "settings", element: <SettingsPage /> },
        ],
      },
      // Outside AppShell's sidebar chrome: a full-screen wizard layout
      // (roadmap slice 018).
      { path: "/setup", element: <SetupWizardPage /> },
    ],
  },
]);
