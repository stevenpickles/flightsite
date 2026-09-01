/**
 * Live match counts per watchlist name, computed from the live store's own
 * flagged aircraft (`LiveAircraft.watchlists`, `docs/API.md` §3.3, slice
 * 037) rather than a separate backend query — the same "read what the map
 * already has" approach `useFilteredLiveAircraft` takes, so the count a
 * watchlist card shows can never disagree with what a person would count on
 * the live map themselves.
 */
import type { LiveAircraftRecord } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";

/** Watchlist name → number of live aircraft currently matching it. A name
 * with no live match is simply absent, not zero — callers read it with
 * `counts[name] ?? 0`. */
export type LiveMatchCounts = Record<string, number>;

export function computeLiveMatchCounts(
  aircraftRecords: Record<string, LiveAircraftRecord>,
): LiveMatchCounts {
  const counts: LiveMatchCounts = {};
  for (const record of Object.values(aircraftRecords)) {
    for (const name of record.aircraft.watchlists) {
      counts[name] = (counts[name] ?? 0) + 1;
    }
  }
  return counts;
}

/** The current live match count per watchlist name. Recomputed once per
 * store update (the map's own frame rate — at most a few times a second),
 * not per render. */
export function useLiveWatchlistCounts(): LiveMatchCounts {
  const aircraftRecords = useLiveAircraftStore((state) => state.aircraft);
  return computeLiveMatchCounts(aircraftRecords);
}
