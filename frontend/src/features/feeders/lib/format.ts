/**
 * Formatting the Feeders page needs and nothing else has (roadmap slice
 * 077). Reuses `features/receiver/lib/format.ts` and
 * `features/health/lib/format.ts` for anything they already cover
 * (`formatCount`, `formatDurationCompact`, `formatReceiverLocalDateTime`,
 * `formatAgeAgo`, `NOT_AVAILABLE`) rather than duplicating them — the same
 * cross-feature import `features/health/HealthPage.tsx` already makes of
 * `features/receiver/lib/format.ts`.
 *
 * `null` always means "not available" (`docs/API.md` §2.7); the receiver
 * uplink tiles specifically render it as `NOT_OBSERVED` ("Not observed")
 * per the work package brief, a wording distinct from the health area's
 * bare "—" because a receiver metric being `null` here specifically means
 * the `readsb` kind's own probe returned no reading, not merely "unknown
 * ratio" or "no bytes yet".
 */
import { NOT_AVAILABLE, formatAgeAgo } from "@/features/health/lib/format";
import {
  formatCount,
  formatReceiverLocalDateTime,
} from "@/features/receiver/lib/format";
import type { FeederAdsbOutStatus, FeederMlatStatus } from "@/lib/api/feeders";

export { NOT_AVAILABLE };

/** The receiver-uplink tiles' own placeholder — see module docstring. */
export const NOT_OBSERVED = "Not observed";

function ageSeconds(iso: string | null, nowMs: number): number | null {
  if (iso === null) {
    return null;
  }
  const when = new Date(iso).getTime();
  if (Number.isNaN(when)) {
    return null;
  }
  return Math.max(0, (nowMs - when) / 1000);
}

/**
 * `"18m ago (14:02:10)"` — the "since"/"last data sent" combined relative
 * and absolute rendering the work package asks for, absolute in the
 * receiver's own local time (with its timezone named once by the caller,
 * the same "as of HH:MM:SS · timezone" pattern the page header uses rather
 * than repeating the zone abbreviation on every row).
 */
export function formatRelativeAndAbsolute(
  iso: string | null,
  timezone: string,
  nowMs: number,
): string {
  if (iso === null) {
    return NOT_AVAILABLE;
  }
  const relative = formatAgeAgo(ageSeconds(iso, nowMs));
  const absolute = formatReceiverLocalDateTime(iso, timezone);
  return `${relative} (${absolute})`;
}

export function formatBytesRate(bytesPerSec: number | null): string {
  if (bytesPerSec === null) {
    return NOT_OBSERVED;
  }
  if (bytesPerSec < 1024) {
    return `${Math.round(bytesPerSec)} B/s`;
  }
  const kb = bytesPerSec / 1024;
  const decimals = kb < 10 ? 1 : 0;
  return `${kb.toFixed(decimals)} KB/s`;
}

export function formatCountOrNotObserved(count: number | null): string {
  return count === null ? NOT_OBSERVED : formatCount(count);
}

export function formatPerMinute(count: number | null): string {
  return count === null
    ? NOT_OBSERVED
    : `${formatCount(Math.round(count))}/min`;
}

export function formatRangeNm(rangeNm: number | null): string {
  return rangeNm === null
    ? NOT_OBSERVED
    : `${formatCount(Math.round(rangeNm))} nm`;
}

/** `"6 peers · 98.4% sync"` (design record's "MLAT chip"), `null` when this
 * feeder carries no MLAT signal at all — the card omits the chip entirely
 * rather than render it empty. `good_sync_pct` arrives already scaled 0–100
 * (`docs/design/077-feeders-page.md`'s survey table names it
 * `good_sync_percentage_last_hour`, itself a percentage, not a ratio). */
export function formatMlatChip(mlat: FeederMlatStatus | null): string | null {
  if (mlat === null) {
    return null;
  }
  const peers =
    mlat.peers === null ? "? peers" : `${formatCount(mlat.peers)} peers`;
  const sync =
    mlat.good_sync_pct === null
      ? "sync unknown"
      : `${mlat.good_sync_pct.toFixed(1)}% sync`;
  return `${peers} · ${sync}`;
}

/** `"ADS-B out: connected"` / `"ADS-B out: disconnected"` — `null` when this
 * feeder does not carry an ADS-B-out signal (no Docker socket, or a kind
 * that never has one). */
export function formatAdsbOutChip(
  adsbOut: FeederAdsbOutStatus | null,
): string | null {
  if (adsbOut === null) {
    return null;
  }
  return adsbOut.connected ? "ADS-B out: connected" : "ADS-B out: disconnected";
}
