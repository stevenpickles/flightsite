import { beforeEach, describe, expect, it } from "vitest";

import { INTERPOLATION_MAX_FIX_AGE_MS } from "@/features/map/aircraft/interpolation";
import {
  REMOVAL_FADE_MS,
  useLiveAircraftStore,
} from "@/features/map/aircraft/store/useLiveAircraftStore";
import { TRACK_MAX_POINTS } from "@/features/map/aircraft/track";
import type { LiveAircraft } from "@/lib/api/live";
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

  it("preserves the track when the already-selected aircraft is selected again", () => {
    // A second click on the same aircraft — or a panel row, jump link, or
    // notification naming the one already selected — must not restart
    // accumulation: it would throw away the backfilled history with nothing
    // to rebuild it (issue #133).
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
    const before = store().track;

    store().selectAircraft("aaaaaa", T0 + 2000);

    expect(store().selectedIcao).toBe("aaaaaa");
    expect(store().track).toBe(before);
    expect(store().track?.points).toHaveLength(2);
  });

  it("does not notify subscribers when the selection does not change", () => {
    store().selectAircraft("aaaaaa", T0);
    let notifications = 0;
    const unsubscribe = useLiveAircraftStore.subscribe(() => {
      notifications += 1;
    });
    store().selectAircraft("aaaaaa", T0 + 10);
    unsubscribe();

    expect(notifications).toBe(0);
  });

  it("does not notify subscribers when nothing was selected and null is passed", () => {
    let notifications = 0;
    const unsubscribe = useLiveAircraftStore.subscribe(() => {
      notifications += 1;
    });
    store().selectAircraft(null, T0);
    unsubscribe();

    expect(notifications).toBe(0);
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

describe("backfillTrack", () => {
  beforeEach(() => {
    store().applySnapshot(
      {
        aircraft: [
          makeAircraft({ icao: "aaaaaa", position: { lat: 47.5, lon: -122 } }),
        ],
        receiver: null,
      },
      T0,
    );
  });

  const SIGHTING = 91_001;
  const NEXT_SIGHTING = 91_002;

  const history = [
    { lat: 47.1, lon: -122, at: T0 - 300_000 },
    { lat: 47.3, lon: -122, at: T0 - 150_000 },
  ];

  it("merges the sighting's history under the points seen since selection", () => {
    store().selectAircraft("aaaaaa", T0);
    store().backfillTrack("aaaaaa", SIGHTING, history);

    expect(store().track?.points).toEqual([
      ...history,
      { lat: 47.5, lon: -122, at: T0 },
    ]);
    expect(store().trackBackfilledFrom).toBe(SIGHTING);
  });

  it("keeps extending the track live after a backfill", () => {
    store().selectAircraft("aaaaaa", T0);
    store().backfillTrack("aaaaaa", SIGHTING, history);
    store().applyDelta(
      {
        updated: [
          makeAircraft({ icao: "aaaaaa", position: { lat: 47.6, lon: -122 } }),
        ],
        stale: [],
        removed: [],
      },
      T0 + 1000,
    );

    expect(store().track?.points).toHaveLength(4);
    expect(store().track?.points.at(-1)).toEqual({
      lat: 47.6,
      lon: -122,
      at: T0 + 1000,
    });
  });

  it("keeps the backfilled history when the aircraft is clicked again", () => {
    // The regression this pairs with: a re-click used to restart accumulation
    // while the backfill's inputs stayed unchanged, so nothing re-fetched and
    // the trail collapsed to a dot for the rest of the selection.
    store().selectAircraft("aaaaaa", T0);
    store().backfillTrack("aaaaaa", SIGHTING, history);
    store().selectAircraft("aaaaaa", T0 + 5000);

    expect(store().track?.points).toHaveLength(3);
  });

  it("discards a response that arrives after the aircraft was deselected", () => {
    store().selectAircraft("aaaaaa", T0);
    store().selectAircraft(null, T0 + 10);
    store().backfillTrack("aaaaaa", SIGHTING, history);

    expect(store().track).toBeNull();
    expect(store().trackLive).toEqual([]);
    expect(store().trackBackfilledFrom).toBeNull();
  });

  it("discards a response for an aircraft the selection has moved on from", () => {
    store().applySnapshot(
      {
        aircraft: [
          makeAircraft({ icao: "bbbbbb", position: { lat: 10, lon: 10 } }),
        ],
        receiver: null,
      },
      T0,
    );
    store().selectAircraft("bbbbbb", T0);
    store().backfillTrack("aaaaaa", SIGHTING, history);

    expect(store().track?.icao).toBe("bbbbbb");
    expect(store().track?.points).toEqual([{ lat: 10, lon: 10, at: T0 }]);
  });

  it("leaves the track alone when the aircraft has no open sighting", () => {
    store().selectAircraft("aaaaaa", T0);
    const before = store().track;
    store().backfillTrack("aaaaaa", SIGHTING, []);

    expect(store().track).toBe(before);
  });

  it("does not notify subscribers when the backfill adds nothing", () => {
    // The layer redraws on every store notification; a redundant backfill must
    // not cost one.
    store().selectAircraft("aaaaaa", T0);
    let notifications = 0;
    const unsubscribe = useLiveAircraftStore.subscribe(() => {
      notifications += 1;
    });
    store().backfillTrack("aaaaaa", SIGHTING, [
      { lat: 47.5, lon: -122, at: T0 },
    ]);
    store().backfillTrack("aaaaaa", SIGHTING, []);
    store().backfillTrack("bbbbbb", SIGHTING, history);
    unsubscribe();

    expect(notifications).toBe(0);
  });

  it("re-backfills after a deselect and reselect", () => {
    store().selectAircraft("aaaaaa", T0);
    store().backfillTrack("aaaaaa", SIGHTING, history);
    store().selectAircraft(null, T0 + 10);
    store().selectAircraft("aaaaaa", T0 + 20);
    expect(store().track?.points).toHaveLength(1);
    expect(store().trackBackfilledFrom).toBeNull();

    store().backfillTrack("aaaaaa", SIGHTING, history);
    expect(store().track?.points).toHaveLength(3);
  });

  it("stays idempotent when the same sighting is backfilled again", () => {
    // The refetch `staleTime: 0` provokes returns the same open sighting with
    // its path grown at the newest end — ground the live points already cover,
    // so the drawn track must simply not move.
    store().selectAircraft("aaaaaa", T0);
    store().backfillTrack("aaaaaa", SIGHTING, history);
    const afterFirst = store().track;

    store().backfillTrack("aaaaaa", SIGHTING, [
      ...history,
      { lat: 47.45, lon: -122, at: T0 - 1000 },
    ]);

    expect(store().track).toBe(afterFirst);
    expect(store().track?.points).toHaveLength(3);
  });

  it("replaces a closed sighting's path when the next sighting backfills", () => {
    // Issue #136: sighting N closes and N+1 opens for the same aircraft while
    // N's row is still in the query cache, so N's path is merged first. The
    // correction has to *remove* N's points, which no additive merge can do —
    // the rebuild runs against the live record instead.
    store().selectAircraft("aaaaaa", T0);
    store().backfillTrack("aaaaaa", SIGHTING, history);
    store().applyDelta(
      {
        updated: [
          makeAircraft({ icao: "aaaaaa", position: { lat: 47.6, lon: -122 } }),
        ],
        stale: [],
        removed: [],
      },
      T0 + 1000,
    );
    expect(store().track?.points).toHaveLength(4);

    const reopened = [{ lat: 48.9, lon: -122, at: T0 - 20_000 }];
    store().backfillTrack("aaaaaa", NEXT_SIGHTING, reopened);

    // The closed sighting's two points are gone, the new sighting's one point
    // is drawn, and both live positions survived untouched.
    expect(store().track?.points).toEqual([
      { lat: 48.9, lon: -122, at: T0 - 20_000 },
      { lat: 47.5, lon: -122, at: T0 },
      { lat: 47.6, lon: -122, at: T0 + 1000 },
    ]);
    expect(store().trackBackfilledFrom).toBe(NEXT_SIGHTING);
  });

  it("keeps accumulating live positions after a sighting replacement", () => {
    store().selectAircraft("aaaaaa", T0);
    store().backfillTrack("aaaaaa", SIGHTING, history);
    store().backfillTrack("aaaaaa", NEXT_SIGHTING, [
      { lat: 48.9, lon: -122, at: T0 - 20_000 },
    ]);
    store().applyDelta(
      {
        updated: [
          makeAircraft({ icao: "aaaaaa", position: { lat: 47.7, lon: -122 } }),
        ],
        stale: [],
        removed: [],
      },
      T0 + 2000,
    );

    expect(store().track?.points).toHaveLength(3);
    expect(store().track?.points.at(-1)).toEqual({
      lat: 47.7,
      lon: -122,
      at: T0 + 2000,
    });
  });

  it("caps the merged track at the retention limit", () => {
    store().selectAircraft("aaaaaa", T0);
    const long = Array.from(
      { length: TRACK_MAX_POINTS + 100 },
      (_u, index) => ({
        lat: 47 + index / 100_000,
        lon: -122,
        at: T0 - (TRACK_MAX_POINTS + 100 - index) * 1000,
      }),
    );
    store().backfillTrack("aaaaaa", SIGHTING, long);

    expect(store().track?.points).toHaveLength(TRACK_MAX_POINTS);
    // The newest end is kept: the live-accumulated point is still last.
    expect(store().track?.points.at(-1)).toEqual({
      lat: 47.5,
      lon: -122,
      at: T0,
    });
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
    expect(store().trackLive).toEqual([]);
    expect(store().trackBackfilledFrom).toBeNull();
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
  // `seen_pos_s: 0` throughout: these cases are about *which* frame re-anchors,
  // and pinning the reported age at zero keeps every expectation below the
  // exact pre-#144 dating. Back-dating a nonzero age is the next block.
  const AT = {
    icao: "aaaaaa",
    position: { lat: 47, lon: -122 },
    seen_pos_s: 0,
  } as const;

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

describe("positionChangedAt back-dating (issue #144)", () => {
  const AT = { icao: "aaaaaa", position: { lat: 47, lon: -122 } } as const;
  const MOVED = { ...AT, position: { lat: 47.01, lon: -122 } } as const;

  function anchor(): number | undefined {
    return store().aircraft.aaaaaa?.positionChangedAt;
  }

  function snapshot(overrides: Partial<LiveAircraft>, now: number): void {
    store().applySnapshot(
      { aircraft: [makeAircraft({ ...AT, ...overrides })], receiver: null },
      now,
    );
  }

  function delta(overrides: Partial<LiveAircraft>, now: number): void {
    store().applyDelta(
      {
        updated: [makeAircraft({ ...AT, ...overrides })],
        stale: [],
        removed: [],
      },
      now,
    );
  }

  it("dates a first fix at the age the decoder reports", () => {
    // The frame landed at T0, but the CPR solution behind it is 3 s old.
    snapshot({ seen_pos_s: 3 }, T0);

    expect(anchor()).toBe(T0 - 3000);
  });

  it("dates a new fix on the delta path by the same rule", () => {
    // Both application paths must date a position identically; a snapshot
    // arriving mid-stream must not shift a marker the deltas were placing.
    snapshot({ seen_pos_s: 0 }, T0);
    delta({ ...MOVED, seen_pos_s: 2.5 }, T0 + 4000);

    expect(anchor()).toBe(T0 + 1500);
  });

  it("dates the same fix identically whichever path delivers it", () => {
    snapshot({ seen_pos_s: 0 }, T0);
    delta({ ...MOVED, seen_pos_s: 2.5 }, T0 + 4000);
    const viaDelta = anchor();

    store().reset();
    snapshot({ seen_pos_s: 0 }, T0);
    snapshot({ ...MOVED, seen_pos_s: 2.5 }, T0 + 4000);

    expect(anchor()).toBe(viaDelta);
  });

  it("falls back to the arrival instant when no age is reported", () => {
    // §2.7 makes `null` the representation of "unknown"; without an age the
    // arrival instant is the best available guess, exactly as before #144.
    snapshot({ seen_pos_s: null }, T0);

    expect(anchor()).toBe(T0);
  });

  it("dates a zero-age fix at the arrival instant", () => {
    snapshot({ seen_pos_s: 0 }, T0);

    expect(anchor()).toBe(T0);
  });

  it.each([
    ["negative", -5],
    ["not a number", Number.NaN],
    ["infinite", Number.POSITIVE_INFINITY],
  ])("falls back to the arrival instant for a %s age", (_label, seen) => {
    // A nonsense age must not throw the anchor anywhere; under-projecting is
    // the safe direction.
    snapshot({ seen_pos_s: seen }, T0);

    expect(anchor()).toBe(T0);
  });

  it("clamps an outlier age to the fix-age cap", () => {
    // Five minutes: the decoder reporting something the interpolator has long
    // given up projecting. This pins the *stored field*, not a drawn position:
    // `displayPosition` caps elapsed time at the same constant, so clamped or
    // not the marker sits frozen at the bound either way. The point is that
    // `positionChangedAt` keeps meaning what its name says for anyone reading
    // it directly.
    snapshot({ seen_pos_s: 300 }, T0);

    expect(anchor()).toBe(T0 - INTERPOLATION_MAX_FIX_AGE_MS);
  });

  it("keeps the anchor when a repeated fix reports a growing age", () => {
    // The aircraft has not been placed anywhere new, so the moment it was
    // placed has not changed. The ages below outrun wall time — the decoder's
    // age is sampled afresh each poll and need not track the gap between the
    // frames that carry it — so re-dating each repeat would walk the anchor
    // backwards frame by frame, which is #119 inverted.
    snapshot({ seen_pos_s: 1 }, T0);
    delta({ seen_pos_s: 2.5 }, T0 + 1000);
    delta({ seen_pos_s: 4.5 }, T0 + 2000);
    delta({ seen_pos_s: 12 }, T0 + 8000);

    expect(anchor()).toBe(T0 - 1000);
    expect(store().aircraft.aaaaaa?.receivedAt).toBe(T0 + 8000);
  });

  it("keeps the anchor when a snapshot repeats a fix with a growing age", () => {
    snapshot({ seen_pos_s: 1 }, T0);
    snapshot({ seen_pos_s: 9 }, T0 + 5000);

    expect(anchor()).toBe(T0 - 1000);
  });

  it("re-dates only once the fix itself moves", () => {
    snapshot({ seen_pos_s: 1 }, T0);
    delta({ seen_pos_s: 6 }, T0 + 3000);
    delta({ ...MOVED, seen_pos_s: 1 }, T0 + 4000);

    expect(anchor()).toBe(T0 + 3000);
  });
});
