import { describe, expect, it } from "vitest";

import {
  buildRangeByBearingOption,
  buildSignalHistogramOption,
  buildTimeSeriesChartOption,
  type BearingSectorPoint,
} from "@/features/receiver/lib/chartOptions";
import { chartPalette } from "@/features/receiver/lib/palette";

const palette = chartPalette(false);

interface FakeSeries {
  type: string;
  data: Array<number | null>;
  symbol?: string;
  lineStyle?: { type: string };
}

// Narrow helper: every option here is built from a plain object, never an
// ECharts function form, so indexing is safe in tests.
function series(
  option: ReturnType<typeof buildTimeSeriesChartOption>["option"],
): FakeSeries[] {
  return (option as { series: FakeSeries[] }).series;
}

describe("buildTimeSeriesChartOption", () => {
  it("renders an empty-state option and summary when there are no points", () => {
    const { option, summary } = buildTimeSeriesChartOption({
      points: [],
      kind: "line",
      timezone: "UTC",
      resolution: "hourly",
      seriesName: "Messages per second",
      unitLabel: "msg/s",
      palette,
      formatValue: (value) => `${value} msg/s`,
    });

    expect(summary).toMatch(/no data/i);
    expect((option as { series?: unknown }).series).toBeUndefined();
  });

  it("builds categories/values and a summary naming the latest and peak values", () => {
    const { option, summary } = buildTimeSeriesChartOption({
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
      palette,
      formatValue: (value) => `${value} msg/s`,
    });

    const [chartSeries] = series(option);
    expect(chartSeries?.data).toEqual([10, 25, null]);
    expect(chartSeries?.type).toBe("line");
    // Latest present value is 25 (index 2 is null); peak of [10, 25] is 25.
    expect(summary).toContain("25 msg/s");
    expect(summary).toContain("3 points");
  });

  it("reports 'no readings' when every point is null", () => {
    const { summary } = buildTimeSeriesChartOption({
      points: [
        { t: "2026-08-30T00:00:00.000Z", value: null },
        { t: "2026-08-30T01:00:00.000Z", value: null },
      ],
      kind: "bar",
      timezone: "UTC",
      resolution: "daily",
      seriesName: "Daily message totals",
      unitLabel: "messages",
      palette,
      formatValue: (value) => String(value),
    });

    expect(summary).toMatch(/no readings/i);
  });

  it("uses a bar series for kind='bar'", () => {
    const { option } = buildTimeSeriesChartOption({
      points: [{ t: "2026-08-30T00:00:00.000Z", value: 5 }],
      kind: "bar",
      timezone: "UTC",
      resolution: "daily",
      seriesName: "Unique aircraft per day",
      unitLabel: "aircraft",
      palette,
      formatValue: (value) => String(value),
    });

    expect(series(option)[0]?.type).toBe("bar");
  });
});

describe("buildSignalHistogramOption", () => {
  it("renders an empty-state option and summary when there are no buckets", () => {
    const { option, summary } = buildSignalHistogramOption({
      buckets: [],
      palette,
    });

    expect(summary).toMatch(/no signal readings/i);
    expect((option as { series?: unknown }).series).toBeUndefined();
  });

  it("names the most common band in the summary", () => {
    const { summary, option } = buildSignalHistogramOption({
      buckets: [
        { min_db: -30, max_db: -27, count: 3 },
        { min_db: -27, max_db: -24, count: 41 },
        { min_db: -24, max_db: -21, count: 12 },
      ],
      palette,
    });

    expect(summary).toContain("56 sightings");
    expect(summary).toContain("-27…-24");
    const [chartSeries] = series(option);
    expect(chartSeries?.data).toEqual([3, 41, 12]);
  });
});

describe("buildRangeByBearingOption", () => {
  function sectors(overrides: Record<number, number>): BearingSectorPoint[] {
    return Array.from({ length: 72 }, (_, bucket) => ({
      bearing_deg: bucket * 5 + 2.5,
      value: overrides[bucket] ?? null,
    }));
  }

  it("renders an empty-state option when 'ever' has no sectors at all", () => {
    const { option, summary } = buildRangeByBearingOption({
      today: [],
      ever: [],
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
      palette,
    });

    expect(summary).toMatch(/no range-by-bearing data/i);
    expect((option as { series?: unknown }).series).toBeUndefined();
  });

  it("orients the polar axis with bearing 0 (North) at top, increasing clockwise", () => {
    const { option } = buildRangeByBearingOption({
      today: sectors({}),
      ever: sectors({ 0: 100 }),
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
      palette,
    });

    const angleAxis = (option as { angleAxis: Record<string, unknown> })
      .angleAxis;
    expect(angleAxis.startAngle).toBe(90);
    expect(angleAxis.clockwise).toBe(true);
  });

  it("maps each bearing bucket to its category label in ascending order", () => {
    const { option } = buildRangeByBearingOption({
      today: sectors({}),
      ever: sectors({ 0: 10, 1: 20, 71: 30 }),
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
      palette,
    });

    const angleAxis = (option as { angleAxis: { data: string[] } }).angleAxis;
    // Bucket 0 = 2.5deg (North sector), bucket 1 = 7.5deg, ..., bucket 71 = 357.5deg.
    expect(angleAxis.data[0]).toBe("3°");
    expect(angleAxis.data[1]).toBe("8°");
    expect(angleAxis.data[71]).toBe("358°");
    expect(angleAxis.data).toHaveLength(72);
  });

  it("carries null through for sectors with no recorded range (a gap, not zero)", () => {
    const { option } = buildRangeByBearingOption({
      today: sectors({}),
      ever: sectors({ 5: 42 }),
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
      palette,
    });

    const [everSeries] = series(option);
    expect(everSeries?.data[5]).toBe(42);
    expect(everSeries?.data[6]).toBeNull();
  });

  it("distinguishes 'Ever' and 'Today' by more than color — line style and marker shape", () => {
    const { option } = buildRangeByBearingOption({
      today: sectors({ 0: 50 }),
      ever: sectors({ 0: 100 }),
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
      palette,
    });

    const [everSeries, todaySeries] = series(option);
    expect((everSeries?.lineStyle as { type: string }).type).toBe("solid");
    expect((todaySeries?.lineStyle as { type: string }).type).toBe("dashed");
    expect(everSeries?.symbol).not.toBe(todaySeries?.symbol);
  });

  it("summarizes lifetime and today's maximum range", () => {
    const { summary } = buildRangeByBearingOption({
      today: sectors({ 10: 40 }),
      ever: sectors({ 10: 150, 20: 90 }),
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
      palette,
    });

    expect(summary).toContain("150 nm");
    expect(summary).toContain("40 nm");
  });

  it("reports 'not set yet' when 'ever' has data but 'today' does not", () => {
    const { summary } = buildRangeByBearingOption({
      today: sectors({}),
      ever: sectors({ 10: 150 }),
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
      palette,
    });

    expect(summary).toContain("not set yet");
  });
});
