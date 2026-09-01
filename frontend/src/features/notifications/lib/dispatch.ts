/**
 * Delivery: one alert activity event in, at most one browser notification out
 * (SPEC §48, roadmap slice 040).
 *
 * Called from `features/map/aircraft/useLiveConnection.ts` for every `activity`
 * frame, beside the store write that feeds the activity panel — the socket is
 * where live alerts actually arrive, and putting delivery anywhere downstream
 * would mean re-deriving "is this new?" from a store that resets on teardown.
 *
 * **Why this never prompts.** A WebSocket frame carries no user activation, so
 * calling `requestPermission()` from here would be refused by Firefox and
 * Safari outright — and would be precisely the unprompted request
 * `docs/SECURITY.md` §5 forbids. An alert that arrives without permission is
 * counted as suppressed and shown as such in Settings; the ask stays with the
 * two clicks that own it (the wizard's Finish, and the settings button).
 *
 * **Background and minimized tabs.** Nothing here consults
 * `document.hidden`. SPEC §48 requires notifications to work *"including
 * background/minimized tabs"* and asks for no suppression when the tab is
 * focused, so a match is delivered whichever state the tab is in — the
 * behaviour is then one rule rather than two, and the demo acceptance test can
 * observe it in a visible tab.
 *
 * The single caveat, inherited rather than introduced: the live socket is
 * owned by the Live Map (`useActivityFeedStore`'s docstring explains why it is
 * not hoisted), so notifications flow while FlightSite's map is open — which
 * is the case SPEC §48 describes, a tab left open and then backgrounded — and
 * not while the only open tab sits on, say, Analytics.
 */

import { composeAlertNotification } from "@/features/notifications/lib/compose";
import { claimNotification } from "@/features/notifications/lib/dedupe";
import { canNotify } from "@/features/notifications/lib/permission";
import {
  useNotificationStore,
  wantsSeverity,
} from "@/features/notifications/store/useNotificationStore";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import type { ActivityEvent } from "@/lib/api/activity";

/**
 * Why an event did or did not become a notification.
 *
 * Returned rather than logged so the tests can assert the *reason*, and so the
 * three "the user would have wanted this" outcomes (`blocked`, `failed`) stay
 * distinguishable from the two where they would not (`disabled`, `muted`).
 */
export type DispatchOutcome =
  | "not-an-alert"
  | "disabled"
  | "muted"
  | "duplicate"
  | "blocked"
  | "failed"
  | "delivered";

/** Resolved at call time so `vi.stubGlobal` works and so an environment
 * without the API (jsdom, an insecure origin) is a `null` rather than a
 * `ReferenceError` on the socket's frame handler. */
function notificationApi(): typeof Notification | null {
  const candidate = (globalThis as { Notification?: unknown }).Notification;
  return typeof candidate === "function"
    ? (candidate as typeof Notification)
    : null;
}

/**
 * SPEC §48's *"clicking should open/select the aircraft in FlightSite where
 * practical"*.
 *
 * Two steps, and no router navigation: focus brings the tab forward from the
 * background case the notification exists for, and selecting the ICAO opens
 * `AircraftDetailPanel` on it — the same pair `LiveMapJumpLink` uses. A route
 * change is not among them because the socket that delivered this alert is
 * owned by the Live Map, so the tab being clicked back to is already on it.
 */
function focusAircraft(icao: string | null): void {
  try {
    globalThis.window?.focus();
  } catch {
    // A browser that refuses to focus (a policy some engines apply outside a
    // user gesture) must not stop the selection below from happening.
  }
  if (icao !== null) {
    useLiveAircraftStore.getState().selectAircraft(icao);
  }
}

/**
 * Delivers one activity event as a notification if it should be, and reports
 * what happened.
 *
 * The gates run cheapest-first and, deliberately, **dedupe last among the
 * checks that consume it**: an event the user has muted or has no permission
 * for does not claim its id, so nothing is silently swallowed by a preference
 * that changes a moment later.
 */
export function dispatchAlertNotification(
  event: ActivityEvent,
): DispatchOutcome {
  const store = useNotificationStore.getState();
  const units = useLiveAircraftStore.getState().receiver?.units ?? "aviation";

  const content = composeAlertNotification(event, units);
  if (content === null) {
    return "not-an-alert";
  }
  if (!store.preferences.enabled) {
    return "disabled";
  }
  if (!wantsSeverity(store.preferences, content.severity)) {
    return "muted";
  }

  // Read fresh rather than trusting the mirrored value: the user can grant or
  // revoke permission in the browser's own UI at any moment, and a stale
  // "granted" would mean constructing a notification that throws.
  const permission = store.refreshPermission();
  if (!canNotify(permission)) {
    store.recordSuppressed();
    return "blocked";
  }

  const api = notificationApi();
  if (api === null) {
    store.recordSuppressed();
    return "blocked";
  }

  if (!claimNotification(event.id)) {
    return "duplicate";
  }

  try {
    const notification = new api(content.title, {
      body: content.body,
      tag: content.tag,
    });
    notification.onclick = () => {
      focusAircraft(content.icao);
      notification.close();
    };
    store.recordDelivered();
    return "delivered";
  } catch (error) {
    store.recordError(
      error instanceof Error ? error.message : "Notification failed",
    );
    return "failed";
  }
}
