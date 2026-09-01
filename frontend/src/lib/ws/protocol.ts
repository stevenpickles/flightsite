/**
 * The `/api/v1/ws/live` wire protocol, client side.
 *
 * The authoritative reference is the module docstring of
 * `backend/src/flightsite/api/ws.py` (OpenAPI 3.1 cannot describe a WebSocket,
 * so `docs/API.md` §4 plus that docstring are the contract). What this module
 * owns is the parsing half: turning an arbitrary text frame into a typed,
 * trusted envelope — or into `null`, which the socket client treats as "ignore".
 *
 * Two protocol rules shape the types below:
 *
 * - **`seq` is per connection and starts at 1 with the snapshot.** A gap means
 *   frames were missed and the client must resync (§4.1/§4.5). Every
 *   server-to-client frame carries one, `ping` included, so the gap check runs
 *   over all of them and not just the data frames.
 * - **Unknown `type`s must be ignored** (§6), not treated as errors. Slice 035
 *   adds `activity` to this same socket; a client written today has to survive
 *   that without reconnecting, so parsing keeps the envelope and lets the
 *   caller decide it has nothing to do with the payload.
 */

import type { LiveAircraft, ReceiverInfo } from "@/lib/api/live";

/** Path of the live socket, relative to the origin the app is served from —
 * the Vite dev proxy and the production reverse proxy both make it reach the
 * backend, exactly like the REST paths in `@/lib/api/client`. */
export const LIVE_WS_PATH = "/api/v1/ws/live";

/** Frame types this client understands. Anything else is ignored per §6. */
export type ServerFrameType = "snapshot" | "delta" | "ping" | "pong";

/** `docs/API.md` §4.2: the complete live picture, replacing whatever the
 * client held. Sent on connect and again whenever the server resyncs. */
export interface SnapshotData {
  aircraft: LiveAircraft[];
  receiver: ReceiverInfo | null;
}

/** `docs/API.md` §4.3: one second's batch. `updated` carries **complete**
 * aircraft objects, never field patches, so a client upserts without merge
 * logic. Application order is `removed`, then `stale`, then `updated`. */
export interface DeltaData {
  updated: LiveAircraft[];
  stale: string[];
  removed: string[];
}

/** One parsed §4.1 envelope. `data` stays `unknown` for frame types that carry
 * no payload this client reads (`ping`/`pong`) or that it does not know. */
export interface ServerFrame {
  type: string;
  seq: number;
  ts: string;
  data: unknown;
}

/** The client's answer to a server `ping` (§4.5). The server also accepts a
 * bare `"pong"` string; the object form is what the documented protocol shows,
 * so it is what this client sends. */
export const PONG_MESSAGE = JSON.stringify({ type: "pong" });

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Parses one text frame into a §4.1 envelope, or returns `null` when the frame
 * is not one (malformed JSON, a non-object body, a missing/ non-numeric `seq`).
 *
 * Returning `null` rather than throwing is deliberate: a frame the client
 * cannot read is not a reason to tear down a working connection, and the
 * sequence check that *does* force a resync only makes sense over frames whose
 * `seq` could actually be read.
 */
export function parseServerFrame(raw: unknown): ServerFrame | null {
  if (typeof raw !== "string") {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(parsed)) {
    return null;
  }
  const { type, seq, ts, data } = parsed;
  if (typeof type !== "string" || typeof seq !== "number") {
    return null;
  }
  return {
    type,
    seq,
    ts: typeof ts === "string" ? ts : "",
    data,
  };
}

/** Narrows a frame body to §4.2 snapshot data, tolerating a missing
 * `receiver` block rather than discarding an otherwise usable picture. */
export function asSnapshotData(data: unknown): SnapshotData | null {
  if (!isRecord(data) || !Array.isArray(data.aircraft)) {
    return null;
  }
  return {
    aircraft: data.aircraft as LiveAircraft[],
    receiver: isRecord(data.receiver)
      ? (data.receiver as unknown as ReceiverInfo)
      : null,
  };
}

/** Narrows a frame body to §4.3 delta data. Each of the three lists defaults
 * to empty: the server omits nothing today, but §6 allows the payload to grow
 * and a partial delta is still safely applicable. */
export function asDeltaData(data: unknown): DeltaData | null {
  if (!isRecord(data)) {
    return null;
  }
  const { updated, stale, removed } = data;
  return {
    updated: Array.isArray(updated) ? (updated as LiveAircraft[]) : [],
    stale: Array.isArray(stale) ? stale.filter(isIcao) : [],
    removed: Array.isArray(removed) ? removed.filter(isIcao) : [],
  };
}

function isIcao(value: unknown): value is string {
  return typeof value === "string";
}
