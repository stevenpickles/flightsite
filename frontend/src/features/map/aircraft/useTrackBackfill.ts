/**
 * Backfills the selected aircraft's track from its open sighting (issue #133).
 *
 * Slice 014 could only draw positions the client had watched arrive, so
 * clicking an airborne aircraft showed nothing and then grew a trail from the
 * click onwards — the aircraft's earlier path in the same sighting was never
 * shown. Slice 052's history API supplies it, in two reads chained here:
 *
 * 1. `GET /api/v1/sightings?icao=<hex>&open=true&limit=1` — the aircraft's
 *    currently-open sighting, if it has one.
 * 2. `GET /api/v1/sightings/{id}` — that sighting's `path`, the timestamp-
 *    ordered checkpointed track-so-far (`docs/API.md` §3.7).
 *
 * The result is merged *under* the live-accumulated points by the store's
 * `backfillTrack`, never assigned over them: the checkpoint lags the live
 * picture by design, so the two overlap and `mergeTrackPoints` is what
 * reconciles them.
 *
 * Three things it must not do, and how each is handled:
 *
 * * **Break selection.** Every failure mode — no open sighting (the aircraft
 *   just appeared and has no checkpoint yet), a 404, a dead backend — leaves
 *   the query in an error or empty state and simply backfills nothing. The
 *   selection, the panel and the live trail are unaffected; this is an
 *   enhancement layered on a picture that already works without it.
 * * **Draw one aircraft's history against another.** The response is applied
 *   only for the ICAO it was requested for, and `backfillTrack` re-checks that
 *   against the track it would merge into, so a response that lands after the
 *   selection moved on is discarded at both ends.
 * * **Re-render the map.** Only `selectedIcao` is subscribed to — a field that
 *   changes on a click, not at the frame rate — so the ~1 Hz live picture still
 *   never renders React through this hook.
 *
 * Deselecting clears the track, so a reselect backfills again; TanStack Query
 * answers the repeat from cache rather than re-reading the backend.
 */

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import type { TrackPoint } from "@/features/map/aircraft/track";
import type {
  SightingListParams,
  SightingPathPoint,
} from "@/lib/api/sightings";
import {
  getSightingDetail,
  getSightingList,
  sightingsQueryKeys,
} from "@/lib/api/sightings";

/** The open-sighting lookup, as `GET /api/v1/sightings` wants it: the single
 * newest currently-open sighting for one aircraft. */
function openSightingParams(icao: string): SightingListParams {
  return {
    limit: 1,
    offset: 0,
    sort: "started_at",
    order: "desc",
    icao,
    open: true,
  };
}

/**
 * The sighting path as track points.
 *
 * `t` is an ISO-8601 UTC instant from the receiver's clock; `TrackPoint.at` is
 * UTC milliseconds. Anything that will not parse is dropped rather than
 * poisoning the merge with `NaN`, which compares false against every timestamp
 * and would leave a point stranded wherever the merge happened to place it.
 */
export function toTrackPoints(
  path: readonly SightingPathPoint[],
): TrackPoint[] {
  const points: TrackPoint[] = [];
  for (const point of path) {
    const at = Date.parse(point.t);
    if (!Number.isNaN(at)) {
      points.push({ lat: point.lat, lon: point.lon, at });
    }
  }
  return points;
}

export function useTrackBackfill(): void {
  const selectedIcao = useLiveAircraftStore((state) => state.selectedIcao);

  // Deliberately `useQuery` rather than `useSightingListQuery`: that hook keeps
  // the previous page's rows on screen while the next loads, which for a
  // per-selection lookup would mean briefly holding *another aircraft's*
  // sighting. Here a pending lookup must read as pending.
  const listQuery = useQuery({
    queryKey: sightingsQueryKeys.list(openSightingParams(selectedIcao ?? "")),
    queryFn: () => getSightingList(openSightingParams(selectedIcao as string)),
    enabled: selectedIcao !== null,
  });

  // An open sighting reports `ended_at: null`; the ICAO is re-checked because
  // the row is what the rest of this chain is keyed on.
  const row = listQuery.data?.items[0];
  const sightingId =
    row && row.ended_at === null && row.icao === selectedIcao ? row.id : null;

  const detailQuery = useQuery({
    queryKey: sightingsQueryKeys.detail(sightingId ?? -1),
    queryFn: () => getSightingDetail(sightingId as number),
    enabled: sightingId !== null,
  });

  const detail = detailQuery.data;

  useEffect(() => {
    if (selectedIcao === null || detail === undefined) {
      return;
    }
    if (detail.icao !== selectedIcao) {
      return;
    }
    useLiveAircraftStore
      .getState()
      .backfillTrack(selectedIcao, toTrackPoints(detail.path));
  }, [selectedIcao, detail]);
}
