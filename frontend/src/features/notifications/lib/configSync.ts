/**
 * Mirrors the server's notification settings into
 * {@link useNotificationStore}, so the dispatcher can read the user's choices
 * on a WebSocket frame without a React subscription.
 *
 * Called from `RootLayout` on every config load — the same seam, for the same
 * reason, as `features/setup/lib/mapConfigSync.ts`'s
 * `applyServerConfigToMapStore`: the config document is fetched once and
 * cached by TanStack Query, and the stores that need a slice of it are fed
 * from that one load rather than each opening a query of their own.
 *
 * This is a mirror, never a source. `config.notifications` (SPEC §46/§48) is
 * written by the setup wizard and the Settings page and stored in
 * `config.yaml`; nothing here writes back.
 */

import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";
import type { FlightSiteConfig } from "@/lib/api/config";

export function applyServerConfigToNotificationStore(
  config: FlightSiteConfig,
): void {
  useNotificationStore.getState().setPreferences(config.notifications);
}
