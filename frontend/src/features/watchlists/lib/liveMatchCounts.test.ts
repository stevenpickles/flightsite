import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  computeLiveMatchCounts,
  useLiveWatchlistCounts,
} from "@/features/watchlists/lib/liveMatchCounts";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { makeAircraft } from "@/test/liveAircraftFixtures";

beforeEach(() => {
  useLiveAircraftStore.getState().reset();
});

describe("computeLiveMatchCounts", () => {
  it("counts one aircraft toward every watchlist it matches", () => {
    const counts = computeLiveMatchCounts({
      aaaaaa: {
        aircraft: makeAircraft({
          icao: "aaaaaa",
          watchlists: ["Police", "Rare"],
        }),
        receivedAt: 0,
      },
    });

    expect(counts).toEqual({ Police: 1, Rare: 1 });
  });

  it("sums across multiple aircraft matching the same watchlist", () => {
    const counts = computeLiveMatchCounts({
      aaaaaa: {
        aircraft: makeAircraft({ icao: "aaaaaa", watchlists: ["Police"] }),
        receivedAt: 0,
      },
      bbbbbb: {
        aircraft: makeAircraft({ icao: "bbbbbb", watchlists: ["Police"] }),
        receivedAt: 0,
      },
    });

    expect(counts).toEqual({ Police: 2 });
  });

  it("gives an empty object for no live aircraft", () => {
    expect(computeLiveMatchCounts({})).toEqual({});
  });

  it("omits a watchlist name with no live match rather than reporting zero", () => {
    const counts = computeLiveMatchCounts({
      aaaaaa: {
        aircraft: makeAircraft({ icao: "aaaaaa", watchlists: [] }),
        receivedAt: 0,
      },
    });

    expect(counts).toEqual({});
    expect(counts["Police"]).toBeUndefined();
  });
});

describe("useLiveWatchlistCounts", () => {
  it("reflects the live store's current aircraft", () => {
    act(() => {
      useLiveAircraftStore.getState().applySnapshot({
        aircraft: [makeAircraft({ icao: "aaaaaa", watchlists: ["Police"] })],
        receiver: null,
      });
    });

    const { result } = renderHook(() => useLiveWatchlistCounts());

    expect(result.current).toEqual({ Police: 1 });
  });

  it("updates when the live store updates", () => {
    const { result } = renderHook(() => useLiveWatchlistCounts());
    expect(result.current).toEqual({});

    act(() => {
      useLiveAircraftStore.getState().applySnapshot({
        aircraft: [
          makeAircraft({ icao: "aaaaaa", watchlists: ["Rare Types"] }),
        ],
        receiver: null,
      });
    });

    expect(result.current).toEqual({ "Rare Types": 1 });
  });
});
