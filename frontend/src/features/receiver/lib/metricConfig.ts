/**
 * The SPEC §62 v1 chart catalog's line/bar entries (range-by-bearing and
 * signal-distribution have their own shape and their own components) — one
 * config per `ReceiverSeriesMetric`, driving `ReceiverSeriesChart`.
 */
import type { UnitSystem } from "@/lib/api/config";
import type {
  ReceiverSeriesMetric,
  ReceiverSeriesResolution,
} from "@/lib/api/receiverStats";
import {
  distanceAxisValue,
  distanceUnitLabel,
  formatCount,
  formatRatePerSec,
} from "@/features/receiver/lib/format";

export interface MetricChartConfig {
  metric: ReceiverSeriesMetric;
  title: string;
  kind: "line" | "bar";
  /** True for the charts that are always daily bars, independent of the
   * page's window selector: SPEC §62's "unique aircraft per day" and "daily
   * message/position totals" have no meaningful raw or hourly resolution
   * (`docs/API.md` §3.8 — `unique_aircraft` is daily-only by construction,
   * and `messages_total`/`positions_total` have no raw representation). */
  alwaysDaily: boolean;
  unitLabel: (units: UnitSystem) => string;
  convert: (raw: number, units: UnitSystem) => number;
  formatValue: (converted: number, units: UnitSystem) => string;
}

/** Window selector values, mapped to the resolution that can answer them —
 * matching the backend's own default lookback per resolution
 * (`flightsite.api.receiver_stats.DEFAULT_LOOKBACK_MS`): a day of raw
 * samples, a week of hourly summaries, a month of daily ones. */
export type ReceiverWindow = "24h" | "7d" | "30d";

export const WINDOW_OPTIONS: readonly ReceiverWindow[] = ["24h", "7d", "30d"];

export const WINDOW_RESOLUTION: Record<
  ReceiverWindow,
  ReceiverSeriesResolution
> = {
  "24h": "high",
  "7d": "hourly",
  "30d": "daily",
};

export const WINDOW_LABEL: Record<ReceiverWindow, string> = {
  "24h": "24 hours",
  "7d": "7 days",
  "30d": "30 days",
};

export const METRIC_CHARTS: readonly MetricChartConfig[] = [
  {
    metric: "messages_per_sec",
    title: "Messages per second",
    kind: "line",
    alwaysDaily: false,
    unitLabel: () => "msg/s",
    convert: (raw) => raw,
    formatValue: (value) => formatRatePerSec(value, "msg"),
  },
  {
    metric: "positions_per_sec",
    title: "Positions per second",
    kind: "line",
    alwaysDaily: false,
    unitLabel: () => "pos/s",
    convert: (raw) => raw,
    formatValue: (value) => formatRatePerSec(value, "pos"),
  },
  {
    metric: "aircraft_count",
    title: "Simultaneous aircraft",
    kind: "line",
    alwaysDaily: false,
    unitLabel: () => "aircraft",
    convert: (raw) => raw,
    formatValue: (value) => formatCount(Math.round(value)),
  },
  {
    metric: "max_range_nm",
    title: "Maximum range",
    kind: "line",
    alwaysDaily: false,
    unitLabel: (units) => distanceUnitLabel(units),
    convert: (raw, units) => distanceAxisValue(raw, units),
    formatValue: (value, units) => `${value} ${distanceUnitLabel(units)}`,
  },
  {
    metric: "unique_aircraft",
    title: "Unique aircraft per day",
    kind: "bar",
    alwaysDaily: true,
    unitLabel: () => "aircraft",
    convert: (raw) => raw,
    formatValue: (value) => formatCount(Math.round(value)),
  },
  {
    metric: "messages_total",
    title: "Daily message totals",
    kind: "bar",
    alwaysDaily: true,
    unitLabel: () => "messages",
    convert: (raw) => raw,
    formatValue: (value) => formatCount(Math.round(value)),
  },
  {
    metric: "positions_total",
    title: "Daily position totals",
    kind: "bar",
    alwaysDaily: true,
    unitLabel: () => "positions",
    convert: (raw) => raw,
    formatValue: (value) => formatCount(Math.round(value)),
  },
];
