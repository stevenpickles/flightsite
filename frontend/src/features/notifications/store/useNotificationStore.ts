/**
 * What FlightSite knows about browser notification delivery this session
 * (roadmap slice 040).
 *
 * Three things live here, and they are together because every one of them is
 * read by the dispatcher on a WebSocket frame — outside React, through
 * `getState()`, exactly like `useLiveAircraftStore` and
 * `useActivityFeedStore`, so an alert arriving never causes a render of its
 * own:
 *
 * 1. **`permission`** — the browser's standing answer, refreshed from the API
 *    rather than assumed. Nothing in this module ever prompts;
 *    `lib/permission.ts` documents why the prompt belongs to a click.
 * 2. **`preferences`** — the user's per-severity choices, mirrored from the
 *    server config document (SPEC §46/§48). `RootLayout` syncs them on every
 *    config load, the same way it syncs the map's receiver location.
 * 3. **Delivery counters** — what was shown, and what was wanted but could not
 *    be. `docs/SECURITY.md` §5 requires that *"denied/blocked degrades
 *    cleanly and is surfaced in diagnostics"*, and `docs/PRODUCT.md` §4.11
 *    lists notification permission status among the health area's items;
 *    slice 042 reads this store for both rather than re-deriving them.
 *
 * `preferences` starts at "everything off" rather than at the server's
 * defaults. Until the config document has actually loaded, FlightSite does not
 * know what the user asked for, and SPEC §45's *"do not silently enable every
 * possible notification"* makes silence the only safe answer to that.
 */

import { create } from "zustand";

import {
  readPermissionState,
  type NotificationPermissionState,
} from "@/features/notifications/lib/permission";
import type { NotificationConfig } from "@/lib/api/config";
import type { AlertSeverity } from "@/lib/api/sightings";

/** Nothing enabled — the state before the config document has loaded. */
export const NO_NOTIFICATIONS: NotificationConfig = {
  enabled: false,
  info: false,
  interesting: false,
  high: false,
  critical: false,
};

export interface NotificationState {
  /** The browser's standing answer, as last read. */
  permission: NotificationPermissionState;
  /** The user's choices, mirrored from `config.notifications`. */
  preferences: NotificationConfig;
  /** Notifications actually shown this session. */
  delivered: number;
  /**
   * Alerts the user had enabled that could not be shown, because permission
   * was missing, blocked, or the browser refused the construction. The number
   * a denied-permission install needs to see to understand what it is missing.
   */
  suppressed: number;
  /** The last delivery failure's message, for the same reason. */
  lastError: string | null;

  /** Re-reads `Notification.permission` (never prompts) and stores it. */
  refreshPermission: () => NotificationPermissionState;
  /** Records an answer the user just gave the browser's prompt. */
  setPermission: (permission: NotificationPermissionState) => void;
  /** Mirrors the server's notification settings. */
  setPreferences: (preferences: NotificationConfig) => void;
  recordDelivered: () => void;
  recordSuppressed: () => void;
  recordError: (message: string) => void;
  reset: () => void;
}

function initialState(): Pick<
  NotificationState,
  "permission" | "preferences" | "delivered" | "suppressed" | "lastError"
> {
  return {
    // A plain property read of `Notification.permission`, which is why it is
    // safe at module scope: it neither prompts nor can it.
    permission: readPermissionState(),
    preferences: NO_NOTIFICATIONS,
    delivered: 0,
    suppressed: 0,
    lastError: null,
  };
}

export const useNotificationStore = create<NotificationState>((set) => ({
  ...initialState(),

  refreshPermission: () => {
    const permission = readPermissionState();
    set({ permission });
    return permission;
  },

  setPermission: (permission) => {
    set({ permission });
  },

  setPreferences: (preferences) => {
    set({ preferences });
  },

  recordDelivered: () => {
    set((state) => ({ delivered: state.delivered + 1 }));
  },

  recordSuppressed: () => {
    set((state) => ({ suppressed: state.suppressed + 1 }));
  },

  recordError: (message) => {
    set((state) => ({
      suppressed: state.suppressed + 1,
      lastError: message,
    }));
  },

  reset: () => {
    set(initialState());
  },
}));

/** Whether the user asked to be notified about this severity. The master
 * switch gates all four, so a user who turns notifications off keeps their
 * per-severity choices for when they turn them back on. */
export function wantsSeverity(
  preferences: NotificationConfig,
  severity: AlertSeverity,
): boolean {
  if (!preferences.enabled) {
    return false;
  }
  // Indexed rather than switched so a severity this build has never heard of
  // (`docs/API.md` §6 allows the backend to add one) is silently *not*
  // notified, instead of throwing on the socket's frame handler.
  const value = (preferences as unknown as Record<string, unknown>)[severity];
  return value === true;
}
