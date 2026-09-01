/**
 * The Analytics page's preset <-> query string, round-tripped through one
 * key: `preset` (SPEC §58: Today / 7 days / 30 days / This year / Since T0).
 * Mirrors `features/aircraft-page/lib/urlState.ts`'s split — pure
 * `URLSearchParams` in and out, so this half is unit-testable without a
 * router. Only written when it differs from the default, so `/analytics`
 * and `/analytics?preset=today` are the same page.
 */

import { ANALYTICS_PRESETS, type AnalyticsPreset } from "@/lib/api/analytics";

export const DEFAULT_PRESET: AnalyticsPreset = "today";

const KEY = "preset";

function isAnalyticsPreset(value: string): value is AnalyticsPreset {
  return (ANALYTICS_PRESETS as readonly string[]).includes(value);
}

/** Restores the preset from a query string, defaulting to `"today"` when
 * absent or malformed rather than rejecting the whole URL. */
export function parseAnalyticsPreset(params: URLSearchParams): AnalyticsPreset {
  const raw = params.get(KEY);
  return raw !== null && isAnalyticsPreset(raw) ? raw : DEFAULT_PRESET;
}

/** Builds the query-string representation of `preset` — empty for the
 * default, so a shared link to the default view stays short. */
export function serializeAnalyticsPreset(
  preset: AnalyticsPreset,
): URLSearchParams {
  const params = new URLSearchParams();
  if (preset !== DEFAULT_PRESET) {
    params.set(KEY, preset);
  }
  return params;
}

/** Human labels for the preset selector, in SPEC §58's documented order. */
export const PRESET_LABELS: Record<AnalyticsPreset, string> = {
  today: "Today",
  "7d": "7 days",
  "30d": "30 days",
  ytd: "This year",
  t0: "Since T0",
};
