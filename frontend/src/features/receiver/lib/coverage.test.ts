import { describe, expect, it } from "vitest";

import { resolveChartTheme } from "@/features/analytics/lib/chartTheme";
import {
  bandButtonLabel,
  bandPhrase,
  buildCoverageChart,
  findingSentence,
  formatHeight,
  type CoverageSectorPoint,
} from "@/features/receiver/lib/coverage";
import type { ReceiverCoverageFinding } from "@/lib/api/receiverStats";

const theme = resolveChartTheme("light");

const LOW = { min_ft: null, max_ft: 10000 };
const MID = { min_ft: 10000, max_ft: 25000 };
const HIGH = { min_ft: 25000, max_ft: null };

interface FakeSeries {
  name: string;
  data: Array<number | null>;
  lineStyle: { type: string };
}

function series(option: unknown): FakeSeries[] {
  return (option as { series: FakeSeries[] }).series;
}

function sectors(values: Record<number, number>): CoverageSectorPoint[] {
  return Array.from({ length: 72 }, (_, bucket) => ({
    bearing_deg: bucket * 5 + 2.5,
    value: values[bucket] ?? null,
  }));
}

function finding(
  overrides: Partial<ReceiverCoverageFinding> = {},
): ReceiverCoverageFinding {
  return {
    band: "above_25k",
    start_deg: 40,
    end_deg: 60,
    compass: "NE",
    max_range_nm: 116.3,
    horizon_nm: 200.6,
    share_of_horizon: 0.58,
    samples: 480,
    days: 5,
    message: "unused by the page",
    ...overrides,
  };
}

describe("band wording", () => {
  it("states heights in the receiver's units", () => {
    expect(formatHeight(25000, "aviation")).toBe("25,000 ft");
    expect(formatHeight(25000, "metric")).toBe("7,620 m");
  });

  it("phrases each band for a sentence and for a button", () => {
    expect(bandPhrase(LOW, "aviation")).toBe("below 10,000 ft");
    expect(bandPhrase(MID, "aviation")).toBe("between 10,000 ft and 25,000 ft");
    expect(bandPhrase(HIGH, "metric")).toBe("above 7,620 m");
    expect(bandButtonLabel(LOW, "aviation")).toBe("Below 10,000 ft");
    expect(bandButtonLabel(MID, "aviation")).toBe("10,000–25,000 ft");
    expect(bandButtonLabel(HIGH, "aviation")).toBe("Above 25,000 ft");
  });
});

describe("findingSentence", () => {
  it("names the direction, the span, the share and the band", () => {
    expect(findingSentence(finding(), HIGH, "aviation")).toBe(
      "NE 40–60° reaches 58 % of the radio horizon above 25,000 ft — likely obstruction",
    );
  });

  it("speaks metric heights to a metric install", () => {
    expect(findingSentence(finding(), HIGH, "metric")).toContain(
      "above 7,620 m",
    );
  });

  it("keeps a span through north as the backend reports it", () => {
    expect(
      findingSentence(
        finding({ start_deg: 350, end_deg: 10, compass: "N" }),
        MID,
        "aviation",
      ),
    ).toMatch(/^N 350–10° reaches/);
  });

  it("calls a short ring all the way round a receiver-wide limit", () => {
    expect(
      findingSentence(
        finding({ start_deg: 0, end_deg: 360, compass: "N" }),
        HIGH,
        "aviation",
      ),
    ).toMatch(/^Every bearing reaches at most 58 %.*receiver-wide limit/);
  });
});

describe("buildCoverageChart", () => {
  it("asks for the empty state when the band has no data", () => {
    const { buildOption, summary } = buildCoverageChart({
      sectors: sectors({}),
      horizon: 200,
      bandLabel: "Above 25,000 ft",
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
    });

    expect(buildOption(theme)).toBeNull();
    expect(summary).toMatch(/no aircraft heard/i);
  });

  it("draws the observed ranges with nulls kept and the horizon as a dashed ring", () => {
    const { buildOption, summary } = buildCoverageChart({
      sectors: sectors({ 0: 150, 9: 110 }),
      horizon: 200,
      bandLabel: "Above 25,000 ft",
      unitLabel: "nm",
      formatValue: (value) => `${value} nm`,
    });

    const [observed, horizon] = series(buildOption(theme));
    expect(observed?.name).toBe("Observed");
    expect(observed?.data).toHaveLength(72);
    expect(observed?.data[0]).toBe(150);
    expect(observed?.data[1]).toBeNull();
    expect(horizon?.name).toBe("Radio horizon");
    expect(new Set(horizon?.data)).toEqual(new Set([200]));
    expect(horizon?.lineStyle.type).toBe("dashed");
    expect(summary).toBe(
      "Above 25,000 ft: furthest 150 nm, heard in 2 of 72 bearing sectors; radio horizon 200 nm.",
    );
  });

  it("omits the horizon ring and says why when the antenna height is unset", () => {
    const { buildOption, summary } = buildCoverageChart({
      sectors: sectors({ 4: 80 }),
      horizon: null,
      bandLabel: "Below 10,000 ft",
      unitLabel: "km",
      formatValue: (value) => `${value} km`,
    });

    expect(series(buildOption(theme)).map((entry) => entry.name)).toEqual([
      "Observed",
    ]);
    expect(summary).toContain("antenna height not set");
  });
});
