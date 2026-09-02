/**
 * The socket-to-notification path, end to end through the real protocol
 * client: an `activity_batch` frame arrives and each alert event in it becomes
 * exactly one browser notification (roadmap slice 040), while the activity
 * store gets the whole batch in one update for the panel.
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

/** Each event as its own single-event batch frame — successive detector
 * passes, which is what a settled receiver actually produces. */
function connectAndDeliver(...events: unknown[]): void {
  connectAndDeliverBatches(...events.map((event) => [event]));
}

/** One frame per argument, each carrying a whole pass. */
function connectAndDeliverBatches(...batches: unknown[][]): void {
  const ws = getLastWebSocket();
  act(() => {
    ws.emitFrame({
      type: "snapshot",
      seq: 1,
      data: { aircraft: [], receiver: null },
    });
    batches.forEach((data, index) => {
      ws.emitFrame({ type: "activity_batch", seq: index + 2, data });
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

  it("notifies per event in one batch, and feeds the store once", () => {
    // One pass carrying several alerts is the case slice 057 created: the
    // store takes the batch as a single update, while notifications stay one
    // per event because a notification is a per-event user-visible thing.
    installNotificationMock({ permission: "granted" });
    useNotificationStore.getState().setPreferences(ALL_ON);
    renderHook(() => {
      useLiveConnection();
    });

    connectAndDeliverBatches([
      alertTriggeredEvent({ id: 1 }),
      alertTriggeredEvent({
        id: 2,
        severity: "critical",
        payload: { reason: "Rule: Emergency" },
      }),
    ]);

    expect(FakeNotification.instances).toHaveLength(2);
    // Newest first: the batch arrives oldest first and is reversed on ingest.
    expect(
      useActivityFeedStore.getState().events.map((event) => event.id),
    ).toEqual([2, 1]);
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
