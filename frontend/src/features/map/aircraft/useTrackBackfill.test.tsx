import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import {
  toTrackPoints,
  useTrackBackfill,
} from "@/features/map/aircraft/useTrackBackfill";
import type {
  SightingDetail,
  SightingListResponse,
  SightingRow,
} from "@/lib/api/sightings";
import { makeAircraft } from "@/test/liveAircraftFixtures";
import { createQueryWrapper } from "@/test/queryWrapper";
import { sightingDetail, sightingRow } from "@/test/sightingsApiMock";

/**
 * The backfill chain in isolation (issue #133): the two history reads, the
 * ICAO guard that survives a selection race, and the failure modes that must
 * leave the live picture exactly as it was.
 *
 * This file drives `fetch` directly rather than through
 * `test/overlaysApiMock`, because one of the cases it has to pin — a response
 * landing after the aircraft was deselected — only exists if the test controls
 * *when* the response arrives.
 */

const T0 = 1_800_000_000_000;
const OPEN_SIGHTING_ID = 91_001;

function listOf(rows: SightingRow[]): SightingListResponse {
  return { items: rows, total: null, limit: 1, offset: 0 };
}

function openRow(overrides: Partial<SightingRow> = {}): SightingRow {
  return sightingRow({
    id: OPEN_SIGHTING_ID,
    icao: "aaaaaa",
    ended_at: null,
    duration_s: null,
    closure_reason: null,
    ...overrides,
  });
}

function openDetail(overrides: Partial<SightingDetail> = {}): SightingDetail {
  return sightingDetail({
    id: OPEN_SIGHTING_ID,
    icao: "aaaaaa",
    ended_at: null,
    duration_s: null,
    closure_reason: null,
    path: [
      {
        t: new Date(T0 - 300_000).toISOString(),
        lat: 47.1,
        lon: -122,
        altitude_ft: 21000,
        source: "adsb",
      },
      {
        t: new Date(T0 - 150_000).toISOString(),
        lat: 47.3,
        lon: -122,
        altitude_ft: 22000,
        source: "adsb",
      },
    ],
    ...overrides,
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

interface ApiScript {
  list?: SightingListResponse;
  /** Resolves to the detail body; a rejection stands in for a dead backend. */
  detail?: () => Promise<Response>;
}

function installApi(script: ApiScript) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const raw = typeof input === "string" ? input : input.toString();
    const url = new URL(raw, "http://localhost");
    if (url.pathname === "/api/v1/sightings") {
      return jsonResponse(script.list ?? listOf([]));
    }
    if (/^\/api\/v1\/sightings\/\d+$/.test(url.pathname)) {
      return script.detail ? await script.detail() : jsonResponse(openDetail());
    }
    throw new Error(`Unhandled fetch in test: ${raw}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function mount() {
  return renderHook(
    () => {
      useTrackBackfill();
    },
    { wrapper: createQueryWrapper() },
  );
}

function points() {
  return useLiveAircraftStore.getState().track?.points;
}

beforeEach(() => {
  useLiveAircraftStore.getState().reset();
  useLiveAircraftStore.getState().applySnapshot(
    {
      aircraft: [
        makeAircraft({ icao: "aaaaaa", position: { lat: 47.5, lon: -122 } }),
        makeAircraft({ icao: "bbbbbb", position: { lat: 10, lon: 10 } }),
      ],
      receiver: null,
    },
    T0,
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("toTrackPoints", () => {
  it("maps ISO instants to UTC milliseconds", () => {
    expect(
      toTrackPoints([
        {
          t: "2026-08-30T22:02:10.000Z",
          lat: 47.11,
          lon: -121.8,
          altitude_ft: 21000,
          source: "adsb",
        },
      ]),
    ).toEqual([{ lat: 47.11, lon: -121.8, at: 1_788_127_330_000 }]);
  });

  it("drops a point whose timestamp will not parse", () => {
    // A NaN `at` compares false against every timestamp, so it would strand a
    // point wherever the merge happened to place it.
    expect(
      toTrackPoints([
        {
          t: "not a date",
          lat: 47,
          lon: -122,
          altitude_ft: null,
          source: "adsb",
        },
      ]),
    ).toEqual([]);
  });
});

describe("useTrackBackfill", () => {
  it("fetches nothing while no aircraft is selected", () => {
    const fetchMock = installApi({});
    mount();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("backfills the open sighting's path under the selected track", async () => {
    installApi({ list: listOf([openRow()]) });
    mount();

    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa", T0);
    });

    await waitFor(() => {
      expect(points()).toHaveLength(3);
    });
    expect(points()?.map((point) => point.lat)).toEqual([47.1, 47.3, 47.5]);
  });

  it("asks only for the selected aircraft's currently-open sighting", async () => {
    const fetchMock = installApi({ list: listOf([openRow()]) });
    mount();

    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa", T0);
    });
    await waitFor(() => {
      expect(points()).toHaveLength(3);
    });

    const listUrl = new URL(
      String(fetchMock.mock.calls[0]?.[0]),
      "http://localhost",
    );
    expect(listUrl.pathname).toBe("/api/v1/sightings");
    expect(listUrl.searchParams.get("icao")).toBe("aaaaaa");
    expect(listUrl.searchParams.get("open")).toBe("true");
    expect(listUrl.searchParams.get("limit")).toBe("1");
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe(
      `/api/v1/sightings/${OPEN_SIGHTING_ID}`,
    );
  });

  it("leaves the track alone when the aircraft has no open sighting", async () => {
    // An aircraft that has only just appeared has nothing checkpointed yet —
    // the pre-slice behaviour, and not an error.
    const fetchMock = installApi({ list: listOf([]) });
    mount();

    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa", T0);
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    expect(points()).toHaveLength(1);
  });

  it("ignores a closed sighting the lookup happens to return", async () => {
    const fetchMock = installApi({
      list: listOf([sightingRow({ id: OPEN_SIGHTING_ID, icao: "aaaaaa" })]),
    });
    mount();

    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa", T0);
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    expect(points()).toHaveLength(1);
  });

  it("leaves the selection and the live track intact when the fetch fails", async () => {
    installApi({
      list: listOf([openRow()]),
      detail: () => Promise.reject(new Error("network down")),
    });
    mount();

    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa", T0);
    });

    await waitFor(() => {
      expect(useLiveAircraftStore.getState().selectedIcao).toBe("aaaaaa");
    });
    expect(points()).toHaveLength(1);
  });

  it("discards a response that lands after the aircraft was deselected", async () => {
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    installApi({
      list: listOf([openRow()]),
      detail: async () => {
        await gate;
        return jsonResponse(openDetail());
      },
    });
    mount();

    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa", T0);
    });
    act(() => {
      useLiveAircraftStore.getState().selectAircraft(null, T0 + 10);
    });

    await act(async () => {
      release?.();
      await gate;
    });

    expect(useLiveAircraftStore.getState().track).toBeNull();
  });

  it("discards a response for an aircraft the selection has moved on from", async () => {
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    installApi({
      list: listOf([openRow()]),
      detail: async () => {
        await gate;
        return jsonResponse(openDetail());
      },
    });
    mount();

    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa", T0);
    });
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("bbbbbb", T0 + 10);
    });

    await act(async () => {
      release?.();
      await gate;
    });

    expect(useLiveAircraftStore.getState().track).toEqual({
      icao: "bbbbbb",
      points: [{ lat: 10, lon: 10, at: T0 + 10 }],
    });
  });

  it("re-backfills when the same aircraft is selected again", async () => {
    installApi({ list: listOf([openRow()]) });
    mount();

    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa", T0);
    });
    await waitFor(() => {
      expect(points()).toHaveLength(3);
    });

    act(() => {
      useLiveAircraftStore.getState().selectAircraft(null, T0 + 10);
    });
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa", T0 + 20);
    });

    await waitFor(() => {
      expect(points()).toHaveLength(3);
    });
  });
});
