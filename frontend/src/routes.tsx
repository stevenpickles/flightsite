import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "@/components/shell/AppShell";
import { AircraftPage } from "@/pages/AircraftPage";
import { AlertsPage } from "@/pages/AlertsPage";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { LiveMapPage } from "@/pages/LiveMapPage";
import { ReceiverPage } from "@/pages/ReceiverPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SightingsPage } from "@/pages/SightingsPage";

export const router = createBrowserRouter([
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
]);
