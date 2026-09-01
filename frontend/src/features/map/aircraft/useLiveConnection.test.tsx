/**
 * The socket-to-notification path, end to end through the real protocol
 * client: an `activity` frame arrives and becomes exactly one browser
 * notification (roadmap slice 040), while the activity store gets the same
 * event for the panel.
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useActivityFeedStore } from "@/features/activity/store/useActivityFeedStore";
import { useLiveConnection } from "@/features/map/aircraft/useLiveConnection";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { resetNotificationDedupe } from "@/features/notifications/lib/dedupe";
import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";
import { alertTriggeredEvent } from "@/test/activityApiMock";
import {
  FakeNotification,
  installNotificationMock,
} from "@/test/notificationMock";
import { getLastWebSocket } from "@/test/webSocketMock";

const ALL_ON = {
  enabled: true,
  info: true,
  interesting: true,
  high: true,
  critical: true,
};

function connectAndDeliver(...events: unknown[]): void {
  const ws = getLastWebSocket();
  act(() => {
    ws.emitFrame({
      type: "snapshot",
      seq: 1,
      data: { aircraft: [], receiver: null },
    });
    events.forEach((data, index) => {
      ws.emitFrame({ type: "activity", seq: index + 2, data });
    });
  });
}

beforeEach(() => {
  resetNotificationDedupe();
  useActivityFeedStore.getState().reset();
  useLiveAircraftStore.getState().reset();
  useNotificationStore.getState().reset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetNotificationDedupe();
  useActivityFeedStore.getState().reset();
  useLiveAircraftStore.getState().reset();
  useNotificationStore.getState().reset();
});

describe("useLiveConnection", () => {
  it("turns an alert frame into one notification and one feed entry", () => {
    installNotificationMock({ permission: "granted" });
    useNotificationStore.getState().setPreferences(ALL_ON);
    renderHook(() => {
      useLiveConnection();
    });

    connectAndDeliver(alertTriggeredEvent());

    expect(FakeNotification.instances).toHaveLength(1);
    expect(FakeNotification.instances[0]?.title).toBe(
      "RCH485 · Rule: Military aircraft",
    );
    expect(useActivityFeedStore.getState().events).toHaveLength(1);
  });

  it("shows one notification per match, and one more for the allowed upgrade", () => {
    installNotificationMock({ permission: "granted" });
    useNotificationStore.getState().setPreferences(ALL_ON);
    renderHook(() => {
      useLiveConnection();
    });

    connectAndDeliver(
      alertTriggeredEvent({ id: 1 }),
      // The same match redelivered — a duplicate frame must not double up.
      alertTriggeredEvent({ id: 1 }),
      // A second, higher-severity match against the same sighting: its own
      // row on the backend, its own event id, and SPEC §48's allowed extra.
      alertTriggeredEvent({
        id: 2,
        severity: "critical",
        payload: { reason: "Rule: Emergency" },
      }),
    );

    expect(FakeNotification.instances).toHaveLength(2);
    expect(useNotificationStore.getState().delivered).toBe(2);
  });

  it("does not notify for non-alert activity", () => {
    installNotificationMock({ permission: "granted" });
    useNotificationStore.getState().setPreferences(ALL_ON);
    renderHook(() => {
      useLiveConnection();
    });

    connectAndDeliver({
      id: 9,
      type: "range_record",
      severity: "interesting",
      at: "2026-08-31T15:00:00.000Z",
      icao: null,
      sighting_id: null,
      payload: { range_nm: 412.75 },
    });

    expect(FakeNotification.instances).toHaveLength(0);
    expect(useActivityFeedStore.getState().events).toHaveLength(1);
  });

  it("delivers nothing, and breaks nothing, when the user has not opted in", () => {
    // The store's default: no config loaded, so nothing is enabled.
    installNotificationMock({ permission: "granted" });
    renderHook(() => {
      useLiveConnection();
    });

    connectAndDeliver(alertTriggeredEvent());

    expect(FakeNotification.instances).toHaveLength(0);
    expect(useActivityFeedStore.getState().events).toHaveLength(1);
  });
});
