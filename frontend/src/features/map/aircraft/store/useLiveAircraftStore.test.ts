import { beforeEach, describe, expect, it } from "vitest";

import {
  REMOVAL_FADE_MS,
  useLiveAircraftStore,
} from "@/features/map/aircraft/store/useLiveAircraftStore";
import { TRACK_MAX_POINTS } from "@/features/map/aircraft/track";
import { makeAircraft } from "@/test/liveAircraftFixtures";

const T0 = 1_800_000_000_000;

function store() {
  return useLiveAircraftStore.getState();
}

beforeEach(() => {
  store().reset();
});

describe("applySnapshot", () => {
  it("replaces the whole picture", () => {
    store().applySnapshot(
      { aircraft: [makeAircraft({ icao: "aaaaaa" })], receiver: null },
      T0,
    );
    store().applySnapshot(
      { aircraft: [makeAircraft({ icao: "bbbbbb" })], receiver: null },
      T0 + 1000,
    );

    // §4.2: a snapshot is the client's entire picture, not a merge.
    expect(Object.keys(store().aircraft)).toEqual(["bbbbbb"]);
  });

  it("dates each record with the local clock, not the receiver's", () => {
    store().applySnapshot({ aircraft: [makeAircraft()], receiver: null }, T0);
    expect(store().aircraft.ae1463?.receivedAt).toBe(T0);
  });

  it("keeps the receiver block, and the previous one when a frame omits it", () => {
    const receiver = {
      site_name: "Test",
      latitude: 47.6,
      longitude: -122.3,
      antenna_height_ft: null,
      timezone: "UTC",
      units: "aviation" as const,
      display_radius_nm: 250,
      alert_radius_nm: null,
      demo_mode: true,
      t0: null,
    };
    store().applySnapshot({ aircraft: [], receiver }, T0);
    expect(store().receiver).toEqual(receiver);

    store().applySnapshot({ aircraft: [], receiver: null }, T0 + 1000);
    expect(store().receiver).toEqual(receiver);
  });
});

describe("applyDelta", () => {
  beforeEach(() => {
    store().applySnapshot(
      {
        aircraft: [
          makeAircraft({ icao: "aaaaaa" }),
          makeAircraft({ icao: "bbbbbb" }),
        ],
        receiver: null,
      },
      T0,
    );
  });

  it("upserts complete objects from `updated`", () => {
    store().applyDelta(
      {
        updated: [
          makeAircraft({ icao: "aaaaaa", altitude_ft: 12000 }),
          makeAircraft({ icao: "cccccc" }),
        ],
        stale: [],
        removed: [],
      },
      T0 + 1000,
    );

    expect(store().aircraft.aaaaaa?.aircraft.altitude_ft).toBe(12000);
    expect(store().aircraft.aaaaaa?.receivedAt).toBe(T0 + 1000);
    expect(Object.keys(store().aircraft).sort()).toEqual([
      "aaaaaa",
      "bbbbbb",
      "cccccc",
    ]);
  });

  it("flips `stale` entries without touching their payload", () => {
    store().applyDelta(
      { updated: [], stale: ["bbbbbb"], removed: [] },
      T0 + 1000,
    );
    expect(store().aircraft.bbbbbb?.aircraft.state).toBe("stale");
    // The position did not change, so its age must not be reset — that age is
    // what the interpolator dead-reckons from.
    expect(store().aircraft.bbbbbb?.receivedAt).toBe(T0);
  });

  it("moves `removed` aircraft into the fade-out set", () => {
    store().applyDelta(
      { updated: [], stale: [], removed: ["aaaaaa"] },
      T0 + 1000,
    );
    expect(store().aircraft.aaaaaa).toBeUndefined();
    expect(store().departing.aaaaaa?.removedAt).toBe(T0 + 1000);
  });

  it("applies removed, then stale, then updated", () => {
    // The documented order (backend/src/flightsite/api/ws.py). An aircraft
    // listed as removed and then carried in `updated` must survive, because
    // `updated` is applied last.
    store().applyDelta(
      {
        updated: [makeAircraft({ icao: "aaaaaa", altitude_ft: 500 })],
        stale: ["aaaaaa"],
        removed: ["aaaaaa"],
      },
      T0 + 1000,
    );

    expect(store().aircraft.aaaaaa?.aircraft.state).toBe("live");
    expect(store().aircraft.aaaaaa?.aircraft.altitude_ft).toBe(500);
    expect(store().departing.aaaaaa).toBeUndefined();
  });

  it("lets a complete object carrying state:stale agree with the stale list", () => {
    store().applyDelta(
      {
        updated: [makeAircraft({ icao: "bbbbbb", state: "stale" })],
        stale: ["bbbbbb"],
        removed: [],
      },
      T0 + 1000,
    );
    expect(store().aircraft.bbbbbb?.aircraft.state).toBe("stale");
  });

  it("ignores flags for aircraft it does not hold", () => {
    store().applyDelta(
      { updated: [], stale: ["zzzzzz"], removed: ["zzzzzz"] },
      T0 + 1000,
    );
    expect(store().departing.zzzzzz).toBeUndefined();
    expect(Object.keys(store().aircraft).sort()).toEqual(["aaaaaa", "bbbbbb"]);
  });

  it("expires fade-outs once the animation window has passed", () => {
    store().applyDelta(
      { updated: [], stale: [], removed: ["aaaaaa"] },
      T0 + 1000,
    );
    store().applyDelta(
      { updated: [], stale: [], removed: [] },
      T0 + 1000 + REMOVAL_FADE_MS,
    );
    expect(store().departing).toEqual({});
  });
});

describe("selection and track accumulation", () => {
  beforeEach(() => {
    store().applySnapshot(
      {
        aircraft: [
          makeAircraft({ icao: "aaaaaa", position: { lat: 47, lon: -122 } }),
        ],
        receiver: null,
      },
      T0,
    );
  });

  it("seeds the track from the aircraft's current position on selection", () => {
    store().selectAircraft("aaaaaa", T0 + 10);
    expect(store().selectedIcao).toBe("aaaaaa");
    expect(store().track?.points).toEqual([
      { lat: 47, lon: -122, at: T0 + 10 },
    ]);
  });

  it("extends the track as the selected aircraft moves", () => {
    store().selectAircraft("aaaaaa", T0);
    store().applyDelta(
      {
        updated: [
          makeAircraft({ icao: "aaaaaa", position: { lat: 47.1, lon: -122 } }),
        ],
        stale: [],
        removed: [],
      },
      T0 + 1000,
    );
    expect(store().track?.points).toHaveLength(2);
    expect(store().track?.points.at(-1)).toEqual({
      lat: 47.1,
      lon: -122,
      at: T0 + 1000,
    });
  });

  it("does not grow the track while the position repeats", () => {
    store().selectAircraft("aaaaaa", T0);
    store().applyDelta(
      {
        updated: [
          makeAircraft({ icao: "aaaaaa", position: { lat: 47, lon: -122 } }),
        ],
        stale: [],
        removed: [],
      },
      T0 + 1000,
    );
    expect(store().track?.points).toHaveLength(1);
  });

  it("accumulates nothing for aircraft other than the selected one", () => {
    store().selectAircraft("aaaaaa", T0);
    store().applyDelta(
      {
        updated: [
          makeAircraft({ icao: "bbbbbb", position: { lat: 10, lon: 10 } }),
        ],
        stale: [],
        removed: [],
      },
      T0 + 1000,
    );
    expect(store().track?.points).toHaveLength(1);
  });

  it("restarts the track when a different aircraft is selected", () => {
    store().selectAircraft("aaaaaa", T0);
    store().applySnapshot(
      {
        aircraft: [
          makeAircraft({ icao: "bbbbbb", position: { lat: 10, lon: 10 } }),
        ],
        receiver: null,
      },
      T0 + 1000,
    );
    store().selectAircraft("bbbbbb", T0 + 1000);
    expect(store().track).toEqual({
      icao: "bbbbbb",
      points: [{ lat: 10, lon: 10, at: T0 + 1000 }],
    });
  });

  it("clears selection and track together", () => {
    store().selectAircraft("aaaaaa", T0);
    store().selectAircraft(null, T0 + 10);
    expect(store().selectedIcao).toBeNull();
    expect(store().track).toBeNull();
  });

  it("keeps the track when the selected aircraft reports no position", () => {
    store().selectAircraft("aaaaaa", T0);
    store().applyDelta(
      {
        updated: [
          makeAircraft({
            icao: "aaaaaa",
            position: null,
            position_source: "none",
          }),
        ],
        stale: [],
        removed: [],
      },
      T0 + 1000,
    );
    expect(store().track?.points).toHaveLength(1);
  });

  it("caps retained points", () => {
    store().selectAircraft("aaaaaa", T0);
    for (let i = 1; i <= TRACK_MAX_POINTS + 50; i += 1) {
      store().applyDelta(
        {
          updated: [
            makeAircraft({
              icao: "aaaaaa",
              position: { lat: 47 + i / 1000, lon: -122 },
            }),
          ],
          stale: [],
          removed: [],
        },
        T0 + i * 1000,
      );
    }
    expect(store().track?.points).toHaveLength(TRACK_MAX_POINTS);
  });
});

describe("connection status", () => {
  it("starts connecting and follows the socket", () => {
    expect(store().connection).toBe("connecting");
    store().setConnection("live");
    expect(store().connection).toBe("live");
    store().setConnection("reconnecting");
    expect(store().connection).toBe("reconnecting");
  });
});

describe("reset", () => {
  it("returns every field to its initial value", () => {
    store().applySnapshot({ aircraft: [makeAircraft()], receiver: null }, T0);
    store().selectAircraft("ae1463", T0);
    store().setConnection("live");

    store().reset();

    expect(store().aircraft).toEqual({});
    expect(store().departing).toEqual({});
    expect(store().selectedIcao).toBeNull();
    expect(store().track).toBeNull();
    expect(store().receiver).toBeNull();
    expect(store().connection).toBe("connecting");
  });
});

describe("batching", () => {
  it("notifies subscribers once per frame, not once per aircraft", () => {
    // 500 aircraft at 1 Hz through a per-aircraft write would be 500 store
    // notifications a second for a picture that is drawn once.
    let notifications = 0;
    const unsubscribe = useLiveAircraftStore.subscribe(() => {
      notifications += 1;
    });
    store().applySnapshot(
      {
        aircraft: Array.from({ length: 200 }, (_unused, index) =>
          makeAircraft({ icao: index.toString(16).padStart(6, "0") }),
        ),
        receiver: null,
      },
      T0,
    );
    store().applyDelta(
      {
        updated: Array.from({ length: 200 }, (_unused, index) =>
          makeAircraft({ icao: index.toString(16).padStart(6, "0") }),
        ),
        stale: [],
        removed: [],
      },
      T0 + 1000,
    );
    unsubscribe();

    expect(notifications).toBe(2);
  });
});

describe("positionChangedAt", () => {
  const AT = { icao: "aaaaaa", position: { lat: 47, lon: -122 } } as const;

  function anchor(): number | undefined {
    return store().aircraft.aaaaaa?.positionChangedAt;
  }

  beforeEach(() => {
    store().applySnapshot({ aircraft: [makeAircraft(AT)], receiver: null }, T0);
  });

  it("starts at the frame the aircraft first appeared on", () => {
    expect(anchor()).toBe(T0);
  });

  it("survives a delta that repeats the same fix", () => {
    // Issue #119: the backend sends complete objects, so a frame reporting
    // only a new RSSI still carries the last decoded position verbatim.
    store().applyDelta(
      {
        updated: [makeAircraft({ ...AT, rssi_db: -30 })],
        stale: [],
        removed: [],
      },
      T0 + 1000,
    );

    expect(anchor()).toBe(T0);
    expect(store().aircraft.aaaaaa?.receivedAt).toBe(T0 + 1000);
  });

  it("advances when the fix actually moves", () => {
    store().applyDelta(
      {
        updated: [makeAircraft({ ...AT, position: { lat: 47.01, lon: -122 } })],
        stale: [],
        removed: [],
      },
      T0 + 1000,
    );

    expect(anchor()).toBe(T0 + 1000);
  });

  it("advances when only the longitude moves", () => {
    store().applyDelta(
      {
        updated: [makeAircraft({ ...AT, position: { lat: 47, lon: -122.01 } })],
        stale: [],
        removed: [],
      },
      T0 + 1000,
    );

    expect(anchor()).toBe(T0 + 1000);
  });

  it("advances when a different source places the aircraft", () => {
    // Identical coordinates from a different measurement chain is still a new
    // report, and costs nothing to honour: an aircraft that has not moved has
    // nothing to re-anchor.
    store().applyDelta(
      {
        updated: [makeAircraft({ ...AT, position_source: "mlat" })],
        stale: [],
        removed: [],
      },
      T0 + 1000,
    );

    expect(anchor()).toBe(T0 + 1000);
  });

  it("advances when a position appears for a Mode S-only aircraft", () => {
    store().applySnapshot(
      {
        aircraft: [
          makeAircraft({
            icao: "aaaaaa",
            position: null,
            position_source: "none",
          }),
        ],
        receiver: null,
      },
      T0 + 1000,
    );
    store().applyDelta(
      { updated: [makeAircraft(AT)], stale: [], removed: [] },
      T0 + 2000,
    );

    expect(anchor()).toBe(T0 + 2000);
  });

  it("survives a snapshot that repeats the same fix", () => {
    // A resync or reconnect is not evidence that the aircraft moved.
    store().applySnapshot(
      { aircraft: [makeAircraft(AT)], receiver: null },
      T0 + 5000,
    );

    expect(anchor()).toBe(T0);
  });

  it("survives a stale flip", () => {
    store().applyDelta(
      { updated: [], stale: ["aaaaaa"], removed: [] },
      T0 + 1000,
    );

    expect(anchor()).toBe(T0);
  });

  it("restarts for an aircraft removed and restored in the same batch", () => {
    // A returning aircraft is a new track, not a continuation of the old one.
    store().applyDelta(
      { updated: [makeAircraft(AT)], stale: [], removed: ["aaaaaa"] },
      T0 + 1000,
    );

    expect(anchor()).toBe(T0 + 1000);
  });
});
