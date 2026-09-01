import { useEffect } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { applyServerConfigToNotificationStore } from "@/features/notifications/lib/configSync";
import { applyServerConfigToMapStore } from "@/features/setup/lib/mapConfigSync";
import { useConfigQuery } from "@/lib/api/config";

const SETUP_PATH = "/setup";

/**
 * Pathless root route (see `src/routes.tsx`): owns the cross-cutting
 * behaviors that must run regardless of which page is active, and renders
 * nothing but `<Outlet />` so none of them ever blocks the page underneath
 * from rendering while the config query is in flight.
 *
 * - First-run redirect: once `GET /api/internal/config` reports
 *   `first_run: true`, every route is sent to the setup wizard (slice 018,
 *   roadmap AC "wizard never reappears after completion"). A config-fetch
 *   failure is treated the same as "not first-run" rather than blocking
 *   the app — see `useConfigQuery`'s `retry: false`.
 * - Map sync: whenever the config carries a configured receiver location,
 *   it's applied to `useMapConfigStore` so the Live Map centers on the
 *   real site instead of the slice-013 dev placeholder — see
 *   `applyServerConfigToMapStore`.
 * - Notification sync: the same config load feeds the user's per-severity
 *   notification preferences (SPEC §46/§48) to `useNotificationStore`, where
 *   the slice-040 dispatcher reads them without a React subscription. A
 *   mirror only — this never asks the browser for permission, which
 *   `docs/SECURITY.md` §5 allows solely in response to a user's own click.
 */
export function RootLayout() {
  const { data } = useConfigQuery();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    if (data?.first_run && location.pathname !== SETUP_PATH) {
      navigate(SETUP_PATH, { replace: true });
    }
  }, [data?.first_run, location.pathname, navigate]);

  useEffect(() => {
    if (data) {
      applyServerConfigToMapStore(data.config);
      applyServerConfigToNotificationStore(data.config);
    }
  }, [data]);

  return <Outlet />;
}
