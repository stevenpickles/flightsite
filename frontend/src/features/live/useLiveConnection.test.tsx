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
import {
  LIVE_FALLBACK_POLL_MS,
  useLiveConnection,
} from "@/features/live/useLiveConnection";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { resetNotificationDedupe } from "@/features/notifications/lib/dedupe";
import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";
import { CURRENT_AIRCRAFT_PATH, type ReceiverInfo } from "@/lib/api/live";
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
  // A delivered notification reports itself to the internal API (issue #104).
  // Stubbed so this suite exercises the socket path without reaching the
  // network; `features/notifications/lib/dispatch.test.ts` owns the assertions
  // about what is posted.
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response(null, { status: 204 }))),
  );
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
  it("keeps the picture and marks it stale when the connection is lost", () => {
    // Issue R1-03: the picture used to be cleared here, so every panel
    // downstream asserted an empty sky for the 1-30 s a reconnect takes.
    // An outage is not a fact about the sky; it is a fact about the feed,
    // and `stale` plus `lastUpdate` is how the panels say so.
    connectedPicture();
    expect(Object.keys(useLiveAircraftStore.getState().aircraft)).toHaveLength(
      1,
    );

    act(() => {
      getLastWebSocket().emitClose();
    });

    const state = useLiveAircraftStore.getState();
    expect(Object.keys(state.aircraft)).toEqual(["ae1463"]);
    expect(state.stale).toBe(true);
    expect(state.lastUpdate).not.toBeNull();
    // The activity tail still goes: activity frames have no replay, so one
    // kept across the gap would read as a continuous list with a hole.
    expect(useActivityFeedStore.getState().events).toEqual([]);
    // Reported as an outage, not as a fresh start: the chip has to be able to
    // tell "we have lost the feed" from "we have not connected yet".
    expect(state.connection).toBe("reconnecting");
    expect(state.connectionAttempt).toBe(1);
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

describe("REST fallback while the socket is down (R1-03, R1-04)", () => {
  /** A `GET /api/v1/aircraft/current` stub answering the §2.4 envelope. */
  function stubCurrentAircraft(icaos: string[]) {
    const fetchMock = vi.fn((input: unknown) => {
      if (String(input) === CURRENT_AIRCRAFT_PATH) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: icaos.map((icao) => makeAircraft({ icao })),
              total: icaos.length,
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
        );
      }
      return Promise.resolve(new Response(null, { status: 204 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  /** Lets the poll's own promise chain settle under fake timers. */
  async function settle() {
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  function currentAircraftCalls(fetchMock: ReturnType<typeof vi.fn>): number {
    return fetchMock.mock.calls.filter(
      (call) => String(call[0]) === CURRENT_AIRCRAFT_PATH,
    ).length;
  }

  function emitSnapshot(icao: string | null): void {
    getLastWebSocket().emitFrame({
      type: "snapshot",
      seq: 1,
      data: {
        aircraft: icao === null ? [] : [makeAircraft({ icao })],
        receiver: null,
      },
    });
  }

  it("issues no poll at all while the socket is healthy", async () => {
    const fetchMock = stubCurrentAircraft(["aaaaaa"]);
    vi.useFakeTimers();
    try {
      renderHook(() => {
        useLiveConnection();
      });
      act(() => {
        emitSnapshot("ae1463");
      });
      act(() => {
        vi.advanceTimersByTime(LIVE_FALLBACK_POLL_MS * 4);
      });
      await settle();

      expect(currentAircraftCalls(fetchMock)).toBe(0);
      expect(useLiveAircraftStore.getState().stale).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("refreshes the picture over REST the moment the socket drops", async () => {
    const fetchMock = stubCurrentAircraft(["bbbbbb"]);
    vi.useFakeTimers();
    try {
      renderHook(() => {
        useLiveConnection();
      });
      act(() => {
        emitSnapshot("ae1463");
      });
      act(() => {
        getLastWebSocket().emitClose();
      });
      // Stale for exactly as long as it takes the fallback to answer — and
      // the aircraft are still there throughout, which is the whole point.
      expect(useLiveAircraftStore.getState().stale).toBe(true);
      expect(
        Object.keys(useLiveAircraftStore.getState().aircraft),
      ).toHaveLength(1);
      await settle();

      const state = useLiveAircraftStore.getState();
      expect(currentAircraftCalls(fetchMock)).toBe(1);
      expect(Object.keys(state.aircraft)).toEqual(["bbbbbb"]);
      // A poll that answered is as current as a frame that arrived.
      expect(state.stale).toBe(false);
      expect(state.connection).toBe("reconnecting");
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps polling on the interval, and stops once the socket returns", async () => {
    const fetchMock = stubCurrentAircraft(["bbbbbb"]);
    vi.useFakeTimers();
    try {
      renderHook(() => {
        useLiveConnection();
      });
      act(() => {
        emitSnapshot(null);
      });
      act(() => {
        getLastWebSocket().emitClose();
      });
      await settle();
      expect(currentAircraftCalls(fetchMock)).toBe(1);

      act(() => {
        vi.advanceTimersByTime(LIVE_FALLBACK_POLL_MS);
      });
      await settle();
      expect(currentAircraftCalls(fetchMock)).toBe(2);

      act(() => {
        vi.advanceTimersByTime(1_000);
      });
      act(() => {
        emitSnapshot("ae1463");
      });
      const afterReconnect = currentAircraftCalls(fetchMock);
      act(() => {
        vi.advanceTimersByTime(LIVE_FALLBACK_POLL_MS * 3);
      });
      await settle();

      expect(currentAircraftCalls(fetchMock)).toBe(afterReconnect);
      expect(useLiveAircraftStore.getState().connection).toBe("live");
    } finally {
      vi.useRealTimers();
    }
  });

  it("gives a blocked WebSocket upgrade a picture anyway", async () => {
    // Issue R1-04's scenario: the upgrade never completes, so the socket
    // never leaves `connecting`. Before the fallback the map stayed empty
    // and the chip said "Connecting" indefinitely — indistinguishable from
    // an empty sky. The first poll is scheduled rather than immediate here,
    // so an ordinary page load does not race its own socket to the data.
    const fetchMock = stubCurrentAircraft(["cccccc", "dddddd"]);
    vi.useFakeTimers();
    try {
      renderHook(() => {
        useLiveConnection();
      });
      expect(currentAircraftCalls(fetchMock)).toBe(0);

      act(() => {
        getLastWebSocket().emitClose();
      });
      act(() => {
        vi.advanceTimersByTime(LIVE_FALLBACK_POLL_MS);
      });
      await settle();

      const state = useLiveAircraftStore.getState();
      expect(Object.keys(state.aircraft).sort()).toEqual(["cccccc", "dddddd"]);
      expect(state.connection).toBe("connecting");
      expect(state.connectionAttempt).toBeGreaterThanOrEqual(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("leaves the picture stale, not empty, when the fallback fails too", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(null, { status: 503 }))),
    );
    vi.useFakeTimers();
    try {
      renderHook(() => {
        useLiveConnection();
      });
      act(() => {
        emitSnapshot("ae1463");
      });
      act(() => {
        getLastWebSocket().emitClose();
      });
      await settle();

      const state = useLiveAircraftStore.getState();
      expect(Object.keys(state.aircraft)).toEqual(["ae1463"]);
      expect(state.stale).toBe(true);
      expect(state.lastUpdate).not.toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops polling when the shell unmounts", async () => {
    const fetchMock = stubCurrentAircraft(["bbbbbb"]);
    vi.useFakeTimers();
    try {
      const { unmount } = renderHook(() => {
        useLiveConnection();
      });
      act(() => {
        getLastWebSocket().emitClose();
      });
      unmount();
      const afterUnmount = currentAircraftCalls(fetchMock);
      act(() => {
        vi.advanceTimersByTime(LIVE_FALLBACK_POLL_MS * 3);
      });
      await settle();

      expect(currentAircraftCalls(fetchMock)).toBe(afterUnmount);
    } finally {
      vi.useRealTimers();
    }
  });
});
