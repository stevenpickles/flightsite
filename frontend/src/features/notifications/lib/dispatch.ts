/**
 * Delivery: one alert activity event in, at most one browser notification out
 * (SPEC §48, roadmap slice 040).
 *
 * Called from `features/live/useLiveConnection.ts` for every `activity`
 * frame, beside the store write that feeds the activity panel — the socket is
 * where live alerts actually arrive, and putting delivery anywhere downstream
 * would mean re-deriving "is this new?" from a store that resets on
 * connection loss.
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
 * **What goes back.** A notification that was actually shown is reported to
 * `POST /api/internal/alerts/matches/{id}/notified` (issue #104), which is the
 * only write path for `alert_matches.notified` and therefore the only reason
 * the Alerts page's "Notified" column can say anything but `false`. It happens
 * here rather than on the server because *here* is where the fact exists: the
 * backend broadcasting an event knows a socket took some bytes, while this
 * module knows whether a `Notification` was constructed. It is fire-and-forget
 * — see `reportNotified` below.
 *
 * Since ADR-0015 the socket is owned by the app shell, so this runs for a tab
 * parked on any FlightSite route — Analytics, Settings, the map — which is
 * the case SPEC §48 describes: a tab left open and then backgrounded. Only
 * the setup wizard, which renders outside the shell, delivers nothing.
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
import { markAlertMatchNotified } from "@/lib/api/alertMatches";
import { navigateTo } from "@/lib/navigation";

/** The Live Map's route (`src/routes.tsx`, the shell's index route). */
const LIVE_MAP_PATH = "/";

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
 * Three steps: focus brings the tab forward from the background case the
 * notification exists for; a route change brings it to the Live Map if it
 * was parked anywhere else (`lib/navigation` — the shell skips it when the
 * tab is already there), since ADR-0015 lets an alert arrive on any route
 * and a selection is only visible on the map; and selecting the ICAO opens
 * `AircraftDetailPanel` on it — the same pair `LiveMapJumpLink` uses. The
 * selection is made after the navigation so that it lands in a store the
 * map is about to read rather than one `AircraftLayer` is unmounting.
 */
function focusAircraft(icao: string | null): void {
  try {
    globalThis.window?.focus();
  } catch {
    // A browser that refuses to focus (a policy some engines apply outside a
    // user gesture) must not stop the selection below from happening.
  }
  navigateTo(LIVE_MAP_PATH);
  if (icao !== null) {
    useLiveAircraftStore.getState().selectAircraft(icao);
  }
}

/**
 * Tells the backend this match was actually shown —
 * `POST /api/internal/alerts/matches/{id}/notified` (issue #104).
 *
 * **Fire and forget, and after the fact.** The notification is already on the
 * user's screen by the time this runs; nothing about it depends on the
 * request, so this neither awaits nor throws. A failed marker leaves the
 * Alerts page's "Notified" column reading `false` for one row, which is a
 * strictly smaller problem than a rejected promise on the socket's frame
 * handler.
 *
 * `matchId` is `null` for an event from a backend older than the field, and
 * for anything that lost the key on the way here. There is then nothing to
 * report and nothing to log — a `null` is an absent identifier, not an error.
 *
 * The call is made *once* per delivery, which is once per event: the dedupe
 * claim above it has already run, so a repeated frame does not repost. Two
 * tabs still both post for the same match, and the endpoint is idempotent
 * precisely because they do.
 */
function reportNotified(matchId: number | null): void {
  if (matchId === null) {
    return;
  }
  void markAlertMatchNotified(matchId).catch((error: unknown) => {
    console.warn(
      "Could not mark alert match %d as notified: %s",
      matchId,
      error instanceof Error ? error.message : String(error),
    );
  });
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
    // Only here: the `Notification` constructor returned, so a notification
    // genuinely exists. Every earlier return — muted, blocked, duplicate —
    // is a path on which nothing was shown, and `notified` would be a lie.
    reportNotified(content.matchId);
    return "delivered";
  } catch (error) {
    store.recordError(
      error instanceof Error ? error.message : "Notification failed",
    );
    return "failed";
  }
}
