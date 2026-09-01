import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { AppShell } from "@/components/shell/AppShell";
import { RootLayout } from "@/components/shell/RootLayout";
import { SetupWizardPage } from "@/features/setup/SetupWizardPage";
import { ActivityPage } from "@/pages/ActivityPage";
import { AircraftDetailPage } from "@/pages/AircraftDetailPage";
import { AircraftPage } from "@/pages/AircraftPage";
import { AlertsPage } from "@/pages/AlertsPage";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { HealthPage } from "@/pages/HealthPage";
import { LiveMapPage } from "@/pages/LiveMapPage";
import { ReceiverPage } from "@/pages/ReceiverPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SightingDetailPage } from "@/pages/SightingDetailPage";
import { SightingsPage } from "@/pages/SightingsPage";

/** Renders the full route tree (same shape as src/routes.tsx) starting at
 * `initialPath`, for tests that exercise navigation and the shell together. */
export function renderApp(initialPath = "/") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  const router = createMemoryRouter(
    [
      {
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
              { path: "analytics", element: <AnalyticsPage /> },
              { path: "receiver", element: <ReceiverPage /> },
              { path: "alerts", element: <AlertsPage /> },
              { path: "settings", element: <SettingsPage /> },
              { path: "activity", element: <ActivityPage /> },
              { path: "health", element: <HealthPage /> },
            ],
          },
          { path: "/setup", element: <SetupWizardPage /> },
        ],
      },
    ],
    { initialEntries: [initialPath] },
  );

  return {
    ...render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    ),
    /** The memory router driving this render — for tests that need to read
     * or drive the current location directly (e.g. asserting URL-persisted
     * state, roadmap slice 029) rather than only through rendered output. */
    router,
  };
}

export function renderWithProviders(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}
