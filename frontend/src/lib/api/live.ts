/**
 * TypeScript shapes for the live `/api/v1` payloads (`docs/API.md` §3.2/§3.3).
 *
 * These mirror `backend/src/flightsite/api/schemas.py` exactly, including the
 * metadata keys that are present-and-`null` until slices 021–024 fill them in:
 * §2.7 makes `null` the representation of "unknown" and §6 promises the key set
 * only grows, so the frontend codes against the full object now and needs no
 * change when values start arriving.
 *
 * The same object is served by `GET /api/v1/aircraft/current` and carried by
 * every WebSocket `snapshot` / `delta` frame — one shape, one type.
 */

/** §2.8 / SPEC §21. `none` means tracked without a valid position (Mode S
 * only), which is a first-class live entry rather than an error. */
export type PositionSource = "adsb" | "mlat" | "none" | "other";

/** Lifecycle state of a live record; `stale` aircraft fade rather than vanish. */
export type AircraftState = "live" | "stale";

/** A WGS-84 surface position in decimal degrees. */
export interface GeoPosition {
  lat: number;
  lon: number;
}

/** Military / government / law-enforcement classification (slice 024).
 * `icon_category` is the metadata-driven icon hint the icon resolver will
 * consume once that slice populates it; it is `null` on every live payload
 * this slice can receive. */
export interface Classification {
  military: boolean;
  government: boolean;
  law_enforcement: boolean;
  mission: string | null;
  icon_category: string | null;
  confidence: string | null;
}

/** An active alert match (slice 038); `null` when nothing matches. */
export interface InterestingMatch {
  severity: "info" | "interesting" | "high" | "critical";
  reasons: string[];
}

/** One live aircraft — `docs/API.md` §3.3. */
export interface LiveAircraft {
  icao: string;
  callsign: string | null;
  registration: string | null;

  position: GeoPosition | null;
  position_source: PositionSource;
  altitude_ft: number | null;
  ground_speed_kt: number | null;
  track_deg: number | null;
  vertical_rate_fpm: number | null;
  squawk: string | null;
  emergency: "7500" | "7600" | "7700" | null;
  on_ground: boolean | null;

  distance_nm: number | null;
  bearing_deg: number | null;
  rssi_db: number | null;
  message_count: number | null;
  seen_s: number | null;
  seen_pos_s: number | null;

  last_seen: string;
  state: AircraftState;
  sighting_id: number | null;

  aircraft_type: string | null;
  model: string | null;
  operator: string | null;
  operator_group: string | null;
  classification: Classification | null;
  interesting: InterestingMatch | null;

  /** §2.6: keys name fields, values name the source. A field with no entry is
   * decoder-direct. */
  provenance: Record<string, string>;
}

/** Non-secret receiver identity and configuration — `docs/API.md` §3.2. */
export interface ReceiverInfo {
  site_name: string | null;
  latitude: number | null;
  longitude: number | null;
  antenna_height_ft: number | null;
  timezone: string;
  units: "aviation" | "metric";
  display_radius_nm: number;
  alert_radius_nm: number | null;
  demo_mode: boolean;
  t0: string | null;
}
