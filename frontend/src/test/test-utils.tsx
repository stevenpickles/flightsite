import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { AppShell } from "@/components/shell/AppShell";
import { AircraftPage } from "@/pages/AircraftPage";
import { AlertsPage } from "@/pages/AlertsPage";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { LiveMapPage } from "@/pages/LiveMapPage";
import { ReceiverPage } from "@/pages/ReceiverPage";
import { SettingsPage } from "@/pages/SettingsPage";
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
        path: "/",
        element: <AppShell />,
        children: [
          { index: true, element: <LiveMapPage /> },
          { path: "aircraft", element: <AircraftPage /> },
          { path: "sightings", element: <SightingsPage /> },
          { path: "analytics", element: <AnalyticsPage /> },
          { path: "receiver", element: <ReceiverPage /> },
          { path: "alerts", element: <AlertsPage /> },
          { path: "settings", element: <SettingsPage /> },
        ],
      },
    ],
    { initialEntries: [initialPath] },
  );

  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

export function renderWithProviders(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}
