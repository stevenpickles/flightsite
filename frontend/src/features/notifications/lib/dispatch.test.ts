/**
 * The slice-040 acceptance criteria, at the dispatch seam: "exactly one
 * notification per rule per sighting; the upgrade path produces the allowed
 * extra", "clicking selects the aircraft", and "denied permission degrades
 * cleanly".
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetNotificationDedupe } from "@/features/notifications/lib/dedupe";
import { dispatchAlertNotification } from "@/features/notifications/lib/dispatch";
import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import {
  activityEvent,
  alertTriggeredEvent,
  emergencySquawkEvent,
} from "@/test/activityApiMock";
import { defaultReceiverInfo } from "@/test/aircraftApiMock";
import {
  installNotificationMock,
  lastNotification,
} from "@/test/notificationMock";

const ALL_ON = {
  enabled: true,
  info: true,
  interesting: true,
  high: true,
  critical: true,
};

function enableAll(): void {
  useNotificationStore.getState().setPreferences(ALL_ON);
}

/** The internal API a delivered notification reports itself to (issue #104).
 * Stubbed for every test in the file, not only the ones that assert on it:
 * without it a delivery would reach the real `fetch` and try the network. */
let fetchMock: ReturnType<typeof vi.fn>;

function notifiedPosts(): string[] {
  return fetchMock.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method === "POST")
    .map(([path]) => String(path));
}

beforeEach(() => {
  resetNotificationDedupe();
  useNotificationStore.getState().reset();
  useLiveAircraftStore.getState().reset();
  fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetNotificationDedupe();
  useNotificationStore.getState().reset();
  useLiveAircraftStore.getState().reset();
});

describe("dispatchAlertNotification", () => {
  it("shows one notification for an alert the user asked for", () => {
    installNotificationMock({ permission: "granted" });
    enableAll();

    expect(dispatchAlertNotification(alertTriggeredEvent())).toBe("delivered");

    const shown = lastNotification();
    expect(shown?.title).toBe("RCH485 · Rule: Military aircraft");
    expect(shown?.options.body).toContain("12.4 nm");
    expect(shown?.options.tag).toBe("flightsite-alert-5100");
    expect(useNotificationStore.getState().delivered).toBe(1);
  });

  it("shows exactly one notification when the same event arrives twice", () => {
    // A reconnect overlapping a frame in flight, or a Live Map remount.
    installNotificationMock({ permission: "granted" });
    enableAll();
    const event = alertTriggeredEvent();

    expect(dispatchAlertNotification(event)).toBe("delivered");
    expect(dispatchAlertNotification(event)).toBe("duplicate");

    expect(useNotificationStore.getState().delivered).toBe(1);
  });

  it("survives a Live Map remount without re-notifying", () => {
    installNotificationMock({ permission: "granted" });
    enableAll();
    const event = alertTriggeredEvent();
    dispatchAlertNotification(event);

    // What `useLiveConnection` does on unmount; the dedupe record must
    // outlive it, which is why it does not live in the activity store.
    useLiveAircraftStore.getState().reset();

    expect(dispatchAlertNotification(event)).toBe("duplicate");
  });

  it("notifies again for the severity upgrade SPEC §48 allows", () => {
    // Slice 038 records a higher-severity match as its own row — a different
    // rule (or a second built-in key) against the same sighting — so it
    // reaches the client as a distinct event id.
    installNotificationMock({ permission: "granted" });
    enableAll();

    expect(
      dispatchAlertNotification(
        alertTriggeredEvent({
          id: 5100,
          severity: "interesting",
          payload: { reason: "Rule: Watchlist match" },
        }),
      ),
    ).toBe("delivered");
    expect(
      dispatchAlertNotification(
        emergencySquawkEvent({ id: 5101, sighting_id: 88213 }),
      ),
    ).toBe("delivered");

    expect(useNotificationStore.getState().delivered).toBe(2);
    expect(lastNotification()?.title).toBe("RYR8213 · Emergency squawk 7700");
  });

  it("ignores every activity event that is not an alert", () => {
    installNotificationMock({ permission: "granted" });
    enableAll();

    expect(dispatchAlertNotification(activityEvent())).toBe("not-an-alert");
    expect(useNotificationStore.getState().delivered).toBe(0);
  });

  it("shows nothing while the master switch is off", () => {
    installNotificationMock({ permission: "granted" });

    expect(dispatchAlertNotification(alertTriggeredEvent())).toBe("disabled");
    expect(lastNotification()).toBeUndefined();
  });

  it("respects the per-severity choice", () => {
    installNotificationMock({ permission: "granted" });
    useNotificationStore.getState().setPreferences({ ...ALL_ON, high: false });

    expect(dispatchAlertNotification(alertTriggeredEvent())).toBe("muted");
    expect(dispatchAlertNotification(emergencySquawkEvent())).toBe("delivered");
  });

  it("does not consume an event's dedupe claim while it is muted", () => {
    // Turning a severity back on must not silently swallow the next repeat.
    installNotificationMock({ permission: "granted" });
    useNotificationStore.getState().setPreferences({ ...ALL_ON, high: false });
    const event = alertTriggeredEvent();
    dispatchAlertNotification(event);

    enableAll();

    expect(dispatchAlertNotification(event)).toBe("delivered");
  });

  it("degrades cleanly and countably when permission is denied", () => {
    installNotificationMock({ permission: "denied" });
    enableAll();

    expect(dispatchAlertNotification(alertTriggeredEvent())).toBe("blocked");

    const state = useNotificationStore.getState();
    expect(state.permission).toBe("denied");
    expect(state.suppressed).toBe(1);
    expect(state.delivered).toBe(0);
    expect(lastNotification()).toBeUndefined();
  });

  it("never prompts for permission from an incoming alert", () => {
    // `docs/SECURITY.md` §5: requested only after the user opts in, never
    // unprompted — and a socket frame carries no user gesture to ask from.
    const api = installNotificationMock({ permission: "default" });
    enableAll();

    expect(dispatchAlertNotification(alertTriggeredEvent())).toBe("blocked");
    expect(api.requestPermission).not.toHaveBeenCalled();
  });

  it("notices a permission revoked in the browser since the last read", () => {
    const api = installNotificationMock({ permission: "granted" });
    enableAll();
    api.permission = "denied";

    expect(dispatchAlertNotification(alertTriggeredEvent())).toBe("blocked");
  });

  it("degrades cleanly where the browser has no Notification API at all", () => {
    // jsdom's default, and a real plain-HTTP LAN install's.
    vi.stubGlobal("Notification", undefined);
    enableAll();

    expect(dispatchAlertNotification(alertTriggeredEvent())).toBe("blocked");
    expect(useNotificationStore.getState().suppressed).toBe(1);
  });

  it("records a construction failure rather than throwing at the socket", () => {
    const api = installNotificationMock({ permission: "granted" });
    api.constructorError = new Error("Notifications are not supported here");
    enableAll();

    expect(dispatchAlertNotification(alertTriggeredEvent())).toBe("failed");
    expect(useNotificationStore.getState().lastError).toBe(
      "Notifications are not supported here",
    );
  });

  it("formats for a metric receiver", () => {
    installNotificationMock({ permission: "granted" });
    enableAll();
    useLiveAircraftStore.getState().applySnapshot({
      aircraft: [],
      receiver: { ...defaultReceiverInfo(), units: "metric" },
    });

    dispatchAlertNotification(alertTriggeredEvent());

    expect(lastNotification()?.options.body).toContain("23.0 km");
  });

  it("selects the aircraft when the notification is clicked", () => {
    installNotificationMock({ permission: "granted" });
    enableAll();
    const focus = vi.fn();
    vi.spyOn(window, "focus").mockImplementation(focus);

    dispatchAlertNotification(alertTriggeredEvent({ icao: "ae1463" }));
    const shown = lastNotification();
    shown?.onclick?.();

    expect(useLiveAircraftStore.getState().selectedIcao).toBe("ae1463");
    expect(focus).toHaveBeenCalled();
    expect(shown?.closed).toBe(true);
  });

  it("still focuses for an alert with no ICAO to select", () => {
    installNotificationMock({ permission: "granted" });
    enableAll();
    const focus = vi.fn();
    vi.spyOn(window, "focus").mockImplementation(focus);

    dispatchAlertNotification(alertTriggeredEvent({ icao: null }));
    lastNotification()?.onclick?.();

    expect(useLiveAircraftStore.getState().selectedIcao).toBeNull();
    expect(focus).toHaveBeenCalled();
  });
});

/**
 * Issue #104: `alert_matches.notified` had no write path, so the Alerts page's
 * "Notified" marker could only ever say `false`. The fact it names — *a
 * browser notification was actually shown* — exists only here, which is why
 * the client asserts it and the server never does.
 */
describe("reporting a delivered notification", () => {
  it("marks the match notified once the notification exists", () => {
    installNotificationMock({ permission: "granted" });
    enableAll();

    expect(dispatchAlertNotification(alertTriggeredEvent())).toBe("delivered");

    expect(notifiedPosts()).toEqual([
      "/api/internal/alerts/matches/9100/notified",
    ]);
  });

  it("marks the emergency counterpart by its own match id", () => {
    installNotificationMock({ permission: "granted" });
    enableAll();

    dispatchAlertNotification(emergencySquawkEvent());

    expect(notifiedPosts()).toEqual([
      "/api/internal/alerts/matches/9200/notified",
    ]);
  });

  it("marks nothing when permission is denied", () => {
    // Nothing was shown, so `notified` would be a lie — and this is the case
    // the marker exists to distinguish from a delivered one.
    installNotificationMock({ permission: "denied" });
    enableAll();

    expect(dispatchAlertNotification(alertTriggeredEvent())).toBe("blocked");

    expect(notifiedPosts()).toEqual([]);
  });

  it("marks nothing while the severity is muted", () => {
    installNotificationMock({ permission: "granted" });
    useNotificationStore.getState().setPreferences({ ...ALL_ON, high: false });

    expect(dispatchAlertNotification(alertTriggeredEvent())).toBe("muted");

    expect(notifiedPosts()).toEqual([]);
  });

  it("marks nothing for an event that is not an alert", () => {
    installNotificationMock({ permission: "granted" });
    enableAll();

    dispatchAlertNotification(activityEvent());

    expect(notifiedPosts()).toEqual([]);
  });

  it("does not repost when the same event arrives twice", () => {
    // The dedupe claim runs before delivery, so a redelivered frame never
    // reaches the report at all. Two *tabs* still both post, which is why the
    // endpoint is idempotent rather than this being the only guard.
    installNotificationMock({ permission: "granted" });
    enableAll();
    const event = alertTriggeredEvent();

    dispatchAlertNotification(event);
    dispatchAlertNotification(event);

    expect(notifiedPosts()).toHaveLength(1);
  });

  it("marks nothing when a construction failure means nothing was shown", () => {
    const api = installNotificationMock({ permission: "granted" });
    api.constructorError = new Error("Notifications are not supported here");
    enableAll();

    expect(dispatchAlertNotification(alertTriggeredEvent())).toBe("failed");

    expect(notifiedPosts()).toEqual([]);
  });

  it("still delivers when the event carries no match id", () => {
    // An event from a backend older than the field. There is nothing to
    // report and nothing to complain about — the notification is unaffected.
    installNotificationMock({ permission: "granted" });
    enableAll();

    expect(
      dispatchAlertNotification(
        alertTriggeredEvent({ payload: { match_id: null } }),
      ),
    ).toBe("delivered");

    expect(notifiedPosts()).toEqual([]);
    expect(lastNotification()).toBeDefined();
  });

  it("does not throw, or undo the notification, when the report fails", async () => {
    // Fire and forget: the notification is already on screen, so a failed
    // marker must not surface as a rejection on the socket's frame handler.
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    fetchMock.mockRejectedValue(new Error("offline"));
    installNotificationMock({ permission: "granted" });
    enableAll();

    expect(dispatchAlertNotification(alertTriggeredEvent())).toBe("delivered");
    await vi.waitFor(() => {
      expect(warn).toHaveBeenCalled();
    });

    expect(lastNotification()).toBeDefined();
    expect(useNotificationStore.getState().delivered).toBe(1);
    // Not a *notification* error: the user saw the notification. Only the
    // bookkeeping about it failed.
    expect(useNotificationStore.getState().lastError).toBeNull();
    warn.mockRestore();
  });

  it("swallows a rejected status the same way", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "no alert match with id 9100" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    );
    installNotificationMock({ permission: "granted" });
    enableAll();

    expect(dispatchAlertNotification(alertTriggeredEvent())).toBe("delivered");
    await vi.waitFor(() => {
      expect(warn).toHaveBeenCalled();
    });

    expect(useNotificationStore.getState().delivered).toBe(1);
    warn.mockRestore();
  });
});
