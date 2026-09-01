import { describe, expect, it } from "vitest";

import { resolveChartTheme } from "@/features/analytics/lib/chartTheme";
import {
  buildRangeByBearingChart,
  buildSignalHistogramChart,
  buildTimeSeriesChart,
  type BearingSectorPoint,
} from "@/features/receiver/lib/chartOptions";

const theme = resolveChartTheme("light");

interface FakeSeries {
  type: string;
  data: Array<number | null>;
  color?: string;
  symbol?: string;
  lineStyle?: { type: string; color: string };
}

// Narrow helper: every option here is built from a plain object, never an
// ECharts function form, so indexing is safe in tests.
function series(option: unknown): FakeSeries[] {
  return (option as { series: FakeSeries[] }).series;
}

describe("buildTimeSeriesChart", () => {
  it("asks the wrapper for the empty state (buildOption returns null) when there are no points", () => {
    const { buildOption, summary } = buildTimeSeriesChart({
      points: [],
      kind: "line",
      timezone: "UTC",
      resolution: "hourly",
      seriesName: "Messages per second",
      unitLabel: "msg/s",
      formatValue: (value) => `${value} msg/s`,
    });

    expect(summary).toMatch(/no data/i);
    expect(buildOption(theme)).toBeNull();
  });

  it("builds categories/values and a summary naming the latest and peak values", () => {
    const { buildOption, summary } = buildTimeSeriesChart({
      points: [
        { t: "2026-08-30T00:00:00.000Z", value: 10 },
        { t: "2026-08-30T01:00:00.000Z", value: 25 },
        { t: "2026-08-30T02:00:00.000Z", value: null },
      ],
      kind: "line",
      timezone: "UTC",
      resolution: "high",
      seriesName: "Messages per second",
      unitLabel: "msg/s",
      formatValue: (value) => `${value} msg/s`,
    });

    const [chartSeries] = series(buildOption(theme));
    expect(chartSeries?.data).toEqual([10, 25, null]);
    expect(chartSeries?.type).toBe("line");
    // Latest present value is 25 (index 2 is null); peak of [10, 25] is 25.
    expect(summary).toContain("25 msg/s");
    expect(summary).toContain("3 points");
  });

  it("reports 'no readings' when every point is null", () => {
    const { summary } = buildTimeSeriesChart({
      points: [
        { t: "2026-08-30T00:00:00.000Z", value: null },
        { t: "2026-08-30T01:00:00.000Z", value: null },
      ],
      kind: "bar",
      timezone: "UTC",
      resolution: "daily",
      seriesName: "Daily message totals",
      unitLabel: "messages",
      formatValue: (value) => String(value),
    });

    expect(summary).toMatch(/no readings/i);
  });

  it("uses a bar series for kind='bar'", () => {
    const { buildOption } = buildTimeSeriesChart({
      points: [{ t: "2026-08-30T00:00:00.000Z", value: 5 }],
      kind: "bar",
      timezone: "UTC",
      resolution: "daily",
      seriesName: "Unique aircraft per day",
      unitLabel: "aircraft",
      formatValue: (value) => String(value),
    });

    expect(series(buildOption(theme))[0]?.type).toBe("bar");
  });

  it("colors its series from the theme's first categorical slot", () => {
    const { buildOption } = buildTimeSeriesChart({
      points: [{ t: "2026-08-30T00:00:00.000Z", value: 5 }],
      kind: "line",
      timezone: "UTC",
      resolution: "daily",
      seriesName: "Messages per second",
      unitLabel: "msg/s",
      formatValue: (value) => String(value),
    });

    expect(series(buildOption(theme))[0]?.color).toBe(theme.series[0]);
  });
});

describe("buildSignalHistogramChart", () => {
  it("asks the wrapper for the empty state when there are no buckets", () => {
    const { buildOption, summary } = buildSignalHistogramChart({ buckets: [] });

    expect(summary).toMatch(/no signal readings/i);
    expect(buildOption(theme)).toBeNull();
  });

  it("names the most common band in the summary", () => {
    const { summary, buildOption } = buildSignalHistogramChart({
      buckets: [
        { min_db: -30, max_db: -27, count: 3 },
        { min_db: -27, max_db: -24, count: 41 },
        { min_db: -24, max_db: -21, count: 12 },
      ],
    });

    expect(summary).toContain("56 sightings");
    expect(summary).toContain("-27…-24");
    const [chartSeries] = series(buildOption(theme));
    expect(chartSeries?.data).toEqual([3, 41, 12]);
  });
});

describe("buildRangeByBearingChart", () => {
  function sectors(overrides: Record<number, number>): BearingSectorPoint[] {
    return Array.from({ length: 72 }, (_, bucket) => ({
      bearing_deg: bucket * 5 + 2.5,
      value: overrides[bucket] ?? null,
    }));
  }

  it("asks the wrapper for the empty state when 'ever' has no sectors at all", () => {
    const { buildOption, summary } = buildRangeByBearingChart({
      today: [],
      ever: [],
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
    });

    expect(summary).toMatch(/no range-by-bearing data/i);
    expect(buildOption(theme)).toBeNull();
  });

  it("orients the polar axis with bearing 0 (North) at top, increasing clockwise", () => {
    const { buildOption } = buildRangeByBearingChart({
      today: sectors({}),
      ever: sectors({ 0: 100 }),
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
    });

    const angleAxis = (
      buildOption(theme) as { angleAxis: Record<string, unknown> }
    ).angleAxis;
    expect(angleAxis.startAngle).toBe(90);
    expect(angleAxis.clockwise).toBe(true);
  });

  it("maps each bearing bucket to its category label in ascending order", () => {
    const { buildOption } = buildRangeByBearingChart({
      today: sectors({}),
      ever: sectors({ 0: 10, 1: 20, 71: 30 }),
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
    });

    const angleAxis = (buildOption(theme) as { angleAxis: { data: string[] } })
      .angleAxis;
    // Bucket 0 = 2.5deg (North sector), bucket 1 = 7.5deg, ..., bucket 71 = 357.5deg.
    expect(angleAxis.data[0]).toBe("3°");
    expect(angleAxis.data[1]).toBe("8°");
    expect(angleAxis.data[71]).toBe("358°");
    expect(angleAxis.data).toHaveLength(72);
  });

  it("carries null through for sectors with no recorded range (a gap, not zero)", () => {
    const { buildOption } = buildRangeByBearingChart({
      today: sectors({}),
      ever: sectors({ 5: 42 }),
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
    });

    const [everSeries] = series(buildOption(theme));
    expect(everSeries?.data[5]).toBe(42);
    expect(everSeries?.data[6]).toBeNull();
  });

  it("distinguishes 'Ever' and 'Today' by more than color — line style and marker shape", () => {
    const { buildOption } = buildRangeByBearingChart({
      today: sectors({ 0: 50 }),
      ever: sectors({ 0: 100 }),
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
    });

    const [everSeries, todaySeries] = series(buildOption(theme));
    expect((everSeries?.lineStyle as { type: string }).type).toBe("solid");
    expect((todaySeries?.lineStyle as { type: string }).type).toBe("dashed");
    expect(everSeries?.symbol).not.toBe(todaySeries?.symbol);
  });

  it("colors 'Ever' and 'Today' from the theme's first two categorical slots", () => {
    const { buildOption } = buildRangeByBearingChart({
      today: sectors({ 0: 50 }),
      ever: sectors({ 0: 100 }),
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
    });

    const [everSeries, todaySeries] = series(buildOption(theme));
    expect(everSeries?.lineStyle?.color).toBe(theme.series[0]);
    expect(todaySeries?.lineStyle?.color).toBe(theme.series[1]);
  });

  it("summarizes lifetime and today's maximum range", () => {
    const { summary } = buildRangeByBearingChart({
      today: sectors({ 10: 40 }),
      ever: sectors({ 10: 150, 20: 90 }),
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
    });

    expect(summary).toContain("150 nm");
    expect(summary).toContain("40 nm");
  });

  it("reports 'not set yet' when 'ever' has data but 'today' does not", () => {
    const { summary } = buildRangeByBearingChart({
      today: sectors({}),
      ever: sectors({ 10: 150 }),
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
    });

    expect(summary).toContain("not set yet");
  });
});
