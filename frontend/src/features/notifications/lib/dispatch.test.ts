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

beforeEach(() => {
  resetNotificationDedupe();
  useNotificationStore.getState().reset();
  useLiveAircraftStore.getState().reset();
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
