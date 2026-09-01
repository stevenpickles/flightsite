/**
 * The permission half of the notification feature, as a hook (roadmap slice
 * 040).
 *
 * Read-and-refresh on mount, and a `request` the caller wires to a button.
 * The hook never requests on its own — `lib/permission.ts` documents why the
 * ask belongs to a click, and `docs/SECURITY.md` §5 requires it.
 *
 * The refresh on mount and on `visibilitychange` exists because the browser's
 * own site-settings UI is outside FlightSite entirely: a user who unblocks
 * notifications in the address-bar menu and switches back to the tab should
 * see Settings agree with the browser, without a reload.
 */

import { useCallback, useEffect, useState } from "react";

import {
  requestNotificationPermission,
  type NotificationPermissionState,
} from "@/features/notifications/lib/permission";
import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";

export interface NotificationPermissionControls {
  permission: NotificationPermissionState;
  /** True while the browser's prompt is open. */
  isRequesting: boolean;
  /** Asks the browser. Safe to call when a request is already in flight (it
   * is ignored), and safe to call where the API does not exist (it resolves
   * to the standing state). */
  request: () => Promise<NotificationPermissionState>;
}

export function useNotificationPermission(): NotificationPermissionControls {
  const permission = useNotificationStore((state) => state.permission);
  const [isRequesting, setIsRequesting] = useState(false);

  useEffect(() => {
    const refresh = () => {
      useNotificationStore.getState().refreshPermission();
    };
    refresh();
    document.addEventListener("visibilitychange", refresh);
    return () => {
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);

  const request = useCallback(async () => {
    const store = useNotificationStore.getState();
    if (isRequesting) {
      return store.permission;
    }
    setIsRequesting(true);
    try {
      const result = await requestNotificationPermission();
      useNotificationStore.getState().setPermission(result);
      return result;
    } finally {
      setIsRequesting(false);
    }
  }, [isRequesting]);

  return { permission, isRequesting, request };
}
