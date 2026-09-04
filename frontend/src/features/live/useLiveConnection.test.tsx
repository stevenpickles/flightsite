/**
 * The socket-to-notification path, end to end through the real protocol
 * client: an `activity_batch` frame arrives and each alert event in it becomes
 * exactly one browser notification (roadmap slice 040), while the activity
 * store gets the whole batch in one update for the panel.
 *
 * Plus what the hook resets and when (ADR-0015): losing the connection drops
 * the socket-owned state and nothing else. That the *shell* is what mounts
 * this, and that a route change never remounts it, is asserted from the route
 * tree in `components/shell/AppShell.test.tsx`.
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useActivityFeedStore } from "@/features/activity/store/useActivityFeedStore";
import { useLiveConnection } from "@/features/live/useLiveConnection";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { resetNotificationDedupe } from "@/features/notifications/lib/dedupe";
import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";
import type { ReceiverInfo } from "@/lib/api/live";
import { alertTriggeredEvent } from "@/test/activityApiMock";
import { makeAircraft } from "@/test/liveAircraftFixtures";
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

const RECEIVER: ReceiverInfo = {
  site_name: "Home Roof",
  latitude: 47.6,
  longitude: -122.3,
  antenna_height_ft: null,
  timezone: "UTC",
  units: "aviation",
  display_radius_nm: 250,
  alert_radius_nm: null,
  demo_mode: false,
  t0: null,
};

/** Mounts the hook and drives it to a healthy connection carrying one
 * aircraft, one receiver block and one activity event, with that aircraft
 * selected — every category of state ADR-0015 assigns an owner. */
function connectedPicture(): { unmount: () => void } {
  const { unmount } = renderHook(() => {
    useLiveConnection();
  });
  const ws = getLastWebSocket();
  act(() => {
    ws.emitFrame({
      type: "snapshot",
      seq: 1,
      data: {
        aircraft: [makeAircraft({ icao: "ae1463" })],
        receiver: RECEIVER,
      },
    });
    ws.emitFrame({
      type: "activity_batch",
      seq: 2,
      data: [alertTriggeredEvent()],
    });
  });
  act(() => {
    useLiveAircraftStore.getState().selectAircraft("ae1463");
  });
  return { unmount };
}

describe("useLiveConnection teardown (ADR-0015)", () => {
  it("drops the picture and the activity tail when the connection is lost", () => {
    connectedPicture();
    expect(Object.keys(useLiveAircraftStore.getState().aircraft)).toHaveLength(
      1,
    );

    act(() => {
      getLastWebSocket().emitClose();
    });

    const state = useLiveAircraftStore.getState();
    expect(state.aircraft).toEqual({});
    expect(state.departing).toEqual({});
    expect(useActivityFeedStore.getState().events).toEqual([]);
    // Reported as an outage, not as a fresh start: the chip has to be able to
    // tell "we have lost the feed" from "we have not connected yet".
    expect(state.connection).toBe("reconnecting");
  });

  it("keeps the selection, its track and the receiver block across the outage", () => {
    // The three things the socket does not own. A two-second reconnect must
    // not close the detail panel the user is reading, and `dispatch.ts` reads
    // `receiver.units` to compose a notification body on every route.
    connectedPicture();

    act(() => {
      getLastWebSocket().emitClose();
    });

    const state = useLiveAircraftStore.getState();
    expect(state.selectedIcao).toBe("ae1463");
    expect(state.track?.icao).toBe("ae1463");
    expect(state.receiver).toEqual(RECEIVER);
  });

  it("rebuilds the picture wholesale from the reconnect's snapshot", () => {
    // Through the real reconnect, not a stand-in for it: the client reopens on
    // a backoff timer (≤ 500 ms for the first attempt) and the new connection
    // restarts at `seq` 1 with a snapshot of its own, which is the only resync
    // the protocol has (`docs/API.md` §4.5).
    vi.useFakeTimers();
    try {
      connectedPicture();
      const dropped = getLastWebSocket();

      act(() => {
        dropped.emitClose();
      });
      act(() => {
        vi.advanceTimersByTime(1_000);
      });

      const reconnected = getLastWebSocket();
      expect(reconnected).not.toBe(dropped);
      act(() => {
        reconnected.emitFrame({
          type: "snapshot",
          seq: 1,
          data: {
            aircraft: [makeAircraft({ icao: "abcdef" })],
            receiver: null,
          },
        });
      });

      const state = useLiveAircraftStore.getState();
      expect(Object.keys(state.aircraft)).toEqual(["abcdef"]);
      expect(state.connection).toBe("live");
      // Still selected, and still holding the receiver block the first
      // connection delivered.
      expect(state.selectedIcao).toBe("ae1463");
      expect(state.receiver).toEqual(RECEIVER);
    } finally {
      vi.useRealTimers();
    }
  });

  it("clears everything, selection included, when the shell itself goes away", () => {
    const { unmount } = connectedPicture();
    const socket = getLastWebSocket();

    unmount();

    expect(socket.closed).toBe(true);
    expect(useLiveAircraftStore.getState().selectedIcao).toBeNull();
    expect(useActivityFeedStore.getState().events).toEqual([]);
  });
});
