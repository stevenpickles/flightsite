/**
 * The browser Notification API's permission model, as one small typed surface
 * (SPEC §48, roadmap slice 040).
 *
 * **Nothing here is called on page load.** `docs/SECURITY.md` §5 is explicit:
 * *"Permission is requested only after the user opts in (setup wizard or
 * settings), never unprompted"*. {@link readPermissionState} only *reads* the
 * standing answer — it never prompts — and {@link requestNotificationPermission}
 * has exactly two callers, both of them a click the user made about
 * notifications: the setup wizard's Finish button when the notification
 * preference is on, and the Notifications settings section's own button.
 *
 * **Why requesting must happen synchronously inside the click.** Firefox and
 * Safari require *transient user activation* for `requestPermission()`, and
 * that activation is consumed and expires within seconds. So both callers
 * fire this from the event handler itself rather than from a `.then()` after
 * an awaited network round trip — which is also why an incoming alert can
 * never trigger the prompt: a WebSocket frame carries no user activation, and
 * a permission prompt the user did not ask for is exactly what §5 forbids.
 *
 * **Insecure contexts are a first-class state, not an error.** FlightSite is
 * normally reached over plain HTTP on a LAN address (`docs/SECURITY.md` §1–§2:
 * a trusted home network, no TLS assumed), and every current browser withholds
 * the Notification API outside a secure context — HTTPS, or a `localhost`
 * origin. That is the single most likely reason a real install cannot notify,
 * so it gets its own state and its own explanation in the UI rather than being
 * flattened into a bare "unsupported".
 */

/**
 * What the browser will currently let FlightSite do.
 *
 * The three `NotificationPermission` values, plus the two ways the API can be
 * absent entirely. Only `"granted"` delivers; every other value degrades to
 * showing the user why, and is counted for diagnostics
 * ({@link import("@/features/notifications/store/useNotificationStore").useNotificationStore}).
 */
export type NotificationPermissionState =
  "unsupported" | "insecure-context" | "default" | "granted" | "denied";

/** True when notifications can actually be delivered right now. */
export function canNotify(state: NotificationPermissionState): boolean {
  return state === "granted";
}

/** True when asking the browser could still change the answer. A `"denied"`
 * answer is the user's standing decision and browsers resolve a re-request
 * immediately without prompting, so the UI offers guidance there instead of a
 * button that appears to do nothing. */
export function canRequest(state: NotificationPermissionState): boolean {
  return state === "default";
}

/**
 * The `Notification` constructor, or `null` where the API is unavailable.
 *
 * Resolved at every call rather than captured at module load: the constructor
 * is a global the tests replace per case (`vi.stubGlobal`), and caching it
 * would freeze whichever value happened to exist when this module was first
 * imported.
 */
function notificationApi(): typeof Notification | null {
  const candidate = (globalThis as { Notification?: unknown }).Notification;
  return typeof candidate === "function"
    ? (candidate as typeof Notification)
    : null;
}

/** Whether the page is running somewhere the browser deliberately withholds
 * powerful APIs. Only an explicit `false` counts — an environment that does
 * not implement `isSecureContext` at all tells us nothing, and guessing
 * "insecure" from its absence would mislabel every such case. */
function isInsecureContext(): boolean {
  const value = (globalThis as { isSecureContext?: unknown }).isSecureContext;
  return value === false;
}

/** Narrows whatever `Notification.permission` returned to the three values
 * the spec defines, treating anything else as "not asked yet". */
function normalize(value: unknown): NotificationPermissionState {
  return value === "granted" || value === "denied" ? value : "default";
}

/**
 * The current permission, read without prompting.
 *
 * Safe to call from a render, an effect, or on load — it touches only
 * `Notification.permission`, which is a plain property read.
 */
export function readPermissionState(): NotificationPermissionState {
  const api = notificationApi();
  if (api === null) {
    return isInsecureContext() ? "insecure-context" : "unsupported";
  }
  return normalize(api.permission);
}

/**
 * Asks the browser for permission, returning the resulting state.
 *
 * Call **only** from a user gesture about notifications (see the module
 * docstring). A browser that has no API, or that refuses the request, yields
 * the state as it stands rather than throwing: a failed request is a thing to
 * display, not a thing to crash the settings page.
 *
 * Handles both shapes of `requestPermission` — the promise-returning form
 * every current browser implements, and the legacy callback form older Safari
 * only supports — because the callback form returns `undefined` and awaiting
 * it would resolve instantly with the wrong answer.
 */
export async function requestNotificationPermission(): Promise<NotificationPermissionState> {
  const api = notificationApi();
  if (api === null) {
    return readPermissionState();
  }
  try {
    const outcome = await new Promise<unknown>((resolve, reject) => {
      let returned: unknown;
      try {
        returned = (
          api.requestPermission as (
            callback?: (permission: NotificationPermission) => void,
          ) => Promise<NotificationPermission> | undefined
        )(resolve as (permission: NotificationPermission) => void);
      } catch (error) {
        reject(error instanceof Error ? error : new Error(String(error)));
        return;
      }
      if (returned instanceof Promise) {
        returned.then(resolve, reject);
      }
    });
    return normalize(outcome);
  } catch {
    // A `SecurityError` (insecure origin) or a browser that rejects the
    // request leaves the standing answer untouched — report that rather
    // than inventing a denial the user never made.
    return readPermissionState();
  }
}
