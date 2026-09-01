/**
 * Formatting the health area needs and nothing else has (roadmap slice 042).
 *
 * Deliberately small: `formatCount` and `formatDurationCompact` already exist
 * in `features/receiver/lib/format.ts` and are imported rather than copied —
 * the same call `features/activity` makes of that module. Only the byte and
 * age formatters are new, because SPEC §67's "database size" and "free disk
 * space" are the first place in the app that renders a byte count.
 *
 * `null` always means "not available" (`docs/API.md` §2.7) and every function
 * here renders it as the app-wide em-dash placeholder rather than throwing or
 * inventing a zero.
 */

/** The em-dash the rest of the app uses for "not available". */
export const NOT_AVAILABLE = "—";

const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"] as const;

/**
 * `"4.2 MB"` / `"812 KB"` / `"0 B"`, in binary multiples.
 *
 * Binary rather than decimal because every other tool the user will compare
 * this against on a Pi — `df`, `ls -lh`, the Docker stats output — reports
 * powers of 1024, and a size that disagrees with `df` is worse than no size.
 */
export function formatBytes(bytes: number | null): string {
  if (bytes === null || !Number.isFinite(bytes) || bytes < 0) {
    return NOT_AVAILABLE;
  }
  if (bytes < 1024) {
    return `${Math.round(bytes)} B`;
  }

  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < BYTE_UNITS.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }

  // One decimal below 10 so "1.4 GB" does not collapse to "1 GB", none above
  // it where the extra digit is noise on a scorecard tile.
  const decimals = value < 10 ? 1 : 0;
  return `${value.toFixed(decimals)} ${BYTE_UNITS[unitIndex]}`;
}

/** `"4m ago"` / `"3d ago"` / `"just now"` from an age in seconds. */
export function formatAgeAgo(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) {
    return NOT_AVAILABLE;
  }
  if (seconds < 10) {
    return "just now";
  }
  if (seconds < 60) {
    return `${Math.floor(seconds)}s ago`;
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m ago`;
  }
  if (seconds < 86400) {
    return `${Math.floor(seconds / 3600)}h ago`;
  }
  return `${Math.floor(seconds / 86400)}d ago`;
}

/** `"12.4%"` from a 0–1 ratio. */
export function formatPercent(ratio: number | null): string {
  if (ratio === null || !Number.isFinite(ratio)) {
    return NOT_AVAILABLE;
  }
  return `${(ratio * 100).toFixed(1)}%`;
}

/** Turn a snake_case wire key into a readable label — `sighting_tracks` →
 * `Sighting tracks`. Keeps the row list in step with the API without a
 * parallel table of display names to forget to update. */
export function humanizeKey(key: string): string {
  const spaced = key.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
