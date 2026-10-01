/**
 * Pure helpers for the Receiver page's coverage chart (roadmap slice 087,
 * issue #230): how far the receiver hears in each 5° sector of one altitude
 * band, against that band's radio horizon.
 *
 * Same contract as `chartOptions.ts` — a `buildOption(theme)` closure plus a
 * screen-reader `summary`, `null` for the wrapper's empty state — and the
 * same polar conventions as the range-by-bearing plot (north at the top,
 * clockwise, one label per cardinal), so the two charts read alike.
 *
 * The finding sentences are composed here rather than taken from the API's
 * `message`, because the API's is in canonical units (ft) and this page
 * speaks the receiver's `units` preference — "above 7,620 m" for a metric
 * install. The numbers and the rule are the backend's; only the wording is
 * localized.
 */
import type { ChartResult } from "@/features/receiver/lib/chartOptions";
import type { UnitSystem } from "@/lib/api/config";
import type {
  ReceiverCoverageBand,
  ReceiverCoverageFinding,
  ReceiverCoverageWindow,
} from "@/lib/api/receiverStats";

const FT_PER_M = 1 / 0.3048;

export const COVERAGE_WINDOWS: readonly ReceiverCoverageWindow[] = [
  "7d",
  "30d",
  "90d",
  "all",
];

export const COVERAGE_WINDOW_LABEL: Record<ReceiverCoverageWindow, string> = {
  "7d": "7d",
  "30d": "30d",
  "90d": "90d",
  all: "All",
};

/** A height in the receiver's units — `"25,000 ft"` or `"7,620 m"`. */
export function formatHeight(heightFt: number, units: UnitSystem): string {
  const value = units === "metric" ? heightFt / FT_PER_M : heightFt;
  const unit = units === "metric" ? "m" : "ft";
  return `${Math.round(value).toLocaleString("en-US")} ${unit}`;
}

/** "below 10,000 ft" / "between 10,000 ft and 25,000 ft" / "above 25,000 ft". */
export function bandPhrase(
  band: Pick<ReceiverCoverageBand, "min_ft" | "max_ft">,
  units: UnitSystem,
): string {
  if (band.min_ft === null && band.max_ft !== null) {
    return `below ${formatHeight(band.max_ft, units)}`;
  }
  if (band.max_ft === null && band.min_ft !== null) {
    return `above ${formatHeight(band.min_ft, units)}`;
  }
  if (band.min_ft !== null && band.max_ft !== null) {
    return `between ${formatHeight(band.min_ft, units)} and ${formatHeight(band.max_ft, units)}`;
  }
  return "at any altitude";
}

/** The band selector's button text: "Below 10,000 ft", "10,000–25,000 ft", … */
export function bandButtonLabel(
  band: Pick<ReceiverCoverageBand, "min_ft" | "max_ft">,
  units: UnitSystem,
): string {
  if (band.min_ft !== null && band.max_ft !== null) {
    const unit = units === "metric" ? " m" : " ft";
    const strip = (text: string) => text.replace(unit, "");
    return `${strip(formatHeight(band.min_ft, units))}–${formatHeight(band.max_ft, units)}`;
  }
  const phrase = bandPhrase(band, units);
  return phrase.charAt(0).toUpperCase() + phrase.slice(1);
}

function degrees(value: number): string {
  return `${Math.round(value)}`;
}

/** The plain sentence a finding is listed as, in the receiver's units — e.g.
 * `"NE 40–60° reaches 58 % of the radio horizon above 25,000 ft — likely
 * obstruction"`. A run covering every sector is a receiver-wide limit, and
 * says so instead of naming a direction. */
export function findingSentence(
  finding: ReceiverCoverageFinding,
  band: Pick<ReceiverCoverageBand, "min_ft" | "max_ft">,
  units: UnitSystem,
): string {
  const percent = Math.round(finding.share_of_horizon * 100);
  const phrase = bandPhrase(band, units);
  if (finding.end_deg - finding.start_deg >= 360) {
    return `Every bearing reaches at most ${percent} % of the radio horizon ${phrase} — likely a receiver-wide limit (antenna, cable or gain) rather than an obstruction`;
  }
  return `${finding.compass} ${degrees(finding.start_deg)}–${degrees(finding.end_deg)}° reaches ${percent} % of the radio horizon ${phrase} — likely obstruction`;
}

export interface CoverageSectorPoint {
  bearing_deg: number;
  /** Already converted to display units; `null` for an unheard sector. */
  value: number | null;
}

/** Index of the category-axis tick nearest a cardinal bearing. */
function cardinalTickIndex(totalSectors: number, targetDeg: number): number {
  return Math.round((targetDeg / 360) * totalSectors) % totalSectors;
}

/**
 * One band's coverage polar plot: the furthest detection per sector, and —
 * when the antenna height is known — the band's radio horizon as a ring.
 * The two are told apart by more than color (SPEC §80): the observed series
 * is a solid line with markers, the horizon a dashed line without.
 */
export function buildCoverageChart(params: {
  sectors: CoverageSectorPoint[];
  /** In display units; `null` while the antenna height is unset. */
  horizon: number | null;
  bandLabel: string;
  unitLabel: string;
  formatValue: (value: number) => string;
}): ChartResult {
  const { sectors, horizon, bandLabel, unitLabel, formatValue } = params;
  const values = sectors.map((sector) => sector.value);
  const present = values.filter((value): value is number => value !== null);

  if (present.length === 0) {
    return {
      buildOption: () => null,
      summary: `${bandLabel}: no aircraft heard in this band yet.`,
    };
  }

  const horizonPhrase =
    horizon === null
      ? "radio horizon unknown (antenna height not set)"
      : `radio horizon ${formatValue(horizon)}`;
  const summary =
    `${bandLabel}: furthest ${formatValue(Math.max(...present))}, ` +
    `heard in ${present.length} of ${sectors.length} bearing sectors; ${horizonPhrase}.`;

  const categories = sectors.map(
    (sector) => `${Math.round(sector.bearing_deg)}°`,
  );
  const total = categories.length;
  const cardinalLabelByIndex: Record<number, string> = {
    [cardinalTickIndex(total, 0)]: "N",
    [cardinalTickIndex(total, 90)]: "E",
    [cardinalTickIndex(total, 180)]: "S",
    [cardinalTickIndex(total, 270)]: "W",
  };

  return {
    summary,
    buildOption: (theme) => ({
      backgroundColor: "transparent",
      textStyle: { color: theme.mutedInk },
      legend: {
        data: horizon === null ? ["Observed"] : ["Observed", "Radio horizon"],
        top: 0,
        textStyle: { color: theme.mutedInk },
      },
      tooltip: {
        trigger: "item",
        valueFormatter: (value: unknown) =>
          typeof value === "number" ? formatValue(value) : "no data",
      },
      polar: { radius: "62%" },
      angleAxis: {
        type: "category",
        data: categories,
        startAngle: 90,
        clockwise: true,
        boundaryGap: false,
        axisLabel: {
          color: theme.mutedInk,
          interval: 0,
          formatter: (_value: string, index: number) =>
            cardinalLabelByIndex[index] ?? "",
        },
        axisLine: { lineStyle: { color: theme.grid } },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      radiusAxis: {
        type: "value",
        axisLabel: {
          color: theme.mutedInk,
          formatter: (value: number) => `${value} ${unitLabel}`,
        },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      series: [
        {
          name: "Observed",
          type: "line",
          coordinateSystem: "polar",
          data: values,
          lineStyle: { width: 2, color: theme.series[0], type: "solid" },
          itemStyle: { color: theme.series[0] },
          symbol: "circle",
          symbolSize: 5,
          connectNulls: false,
        },
        ...(horizon === null
          ? []
          : [
              {
                name: "Radio horizon",
                type: "line" as const,
                coordinateSystem: "polar",
                // One value per sector: a constant ring around the plot.
                data: values.map(() => horizon),
                lineStyle: {
                  width: 2,
                  color: theme.series[1],
                  type: "dashed" as const,
                },
                itemStyle: { color: theme.series[1] },
                symbol: "none",
                silent: true,
              },
            ]),
      ],
    }),
  };
}
