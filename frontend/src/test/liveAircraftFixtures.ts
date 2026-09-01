/**
 * Fixtures for the §3.3 aircraft object.
 *
 * The full key set matters here: `docs/API.md` §2.7 makes every unknown field
 * present-and-`null` rather than absent, so a fixture that omitted keys would
 * let a test pass against a payload the backend never sends. `makeAircraft`
 * therefore starts from a complete object and takes overrides.
 *
 * `makeRecord` wraps one in the store's record shape so tests that only need
 * "an aircraft in the live picture" do not each hand-assemble the local
 * timestamps — and do not each need editing when the record grows a field.
 */

import type { LiveAircraftRecord } from "@/features/map/aircraft/store/useLiveAircraftStore";
import type { LiveAircraft } from "@/lib/api/live";

const BASE: LiveAircraft = {
  icao: "ae1463",
  callsign: "RCH471",
  registration: null,
  position: { lat: 47.6, lon: -122.3 },
  position_source: "adsb",
  altitude_ft: 31000,
  ground_speed_kt: 450,
  track_deg: 90,
  vertical_rate_fpm: 0,
  squawk: "1200",
  emergency: null,
  on_ground: false,
  distance_nm: 12.5,
  bearing_deg: 180,
  rssi_db: -18.2,
  message_count: 1200,
  seen_s: 0.4,
  seen_pos_s: 0.6,
  last_seen: "2026-08-31T14:03:22.418Z",
  state: "live",
  sighting_id: 42,
  aircraft_type: null,
  model: null,
  operator: null,
  operator_group: null,
  classification: null,
  route: { origin: null, destination: null },
  nearest_airport: null,
  interesting: null,
  watchlists: [],
  provenance: {},
};

export function makeAircraft(
  overrides: Partial<LiveAircraft> = {},
): LiveAircraft {
  return { ...BASE, ...overrides };
}

/** Timestamps for {@link makeRecord}. `positionChangedAt` defaults to
 * `receivedAt`: the anchor an aircraft gets on the frame it first appears. */
export interface RecordTimes {
  receivedAt?: number;
  positionChangedAt?: number;
}

/** One aircraft in the store's record shape. */
export function makeRecord(
  overrides: Partial<LiveAircraft> = {},
  times: RecordTimes = {},
): LiveAircraftRecord {
  const receivedAt = times.receivedAt ?? 0;
  return {
    aircraft: makeAircraft(overrides),
    receivedAt,
    positionChangedAt: times.positionChangedAt ?? receivedAt,
  };
}
