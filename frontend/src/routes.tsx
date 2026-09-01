import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "@/components/shell/AppShell";
import { RootLayout } from "@/components/shell/RootLayout";
import { SetupWizardPage } from "@/features/setup/SetupWizardPage";
import { AircraftPage } from "@/pages/AircraftPage";
import { AlertsPage } from "@/pages/AlertsPage";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { LiveMapPage } from "@/pages/LiveMapPage";
import { ReceiverPage } from "@/pages/ReceiverPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SightingsPage } from "@/pages/SightingsPage";

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
          { path: "sightings", element: <SightingsPage /> },
          { path: "analytics", element: <AnalyticsPage /> },
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
