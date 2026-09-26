import { describe, expect, it } from "vitest";

import {
  buildFeederMetricChart,
  hasMetricSamples,
} from "@/features/feeders/lib/chartOptions";
import type { FeederSample } from "@/lib/api/feeders";

function sample(t: string, mlat_peers: number | null): FeederSample {
  return { t, state: "up", metrics: { mlat_peers } };
}

describe("hasMetricSamples", () => {
  it("is false when every sample is missing or null for the key", () => {
    expect(hasMetricSamples([sample("t", null)], "mlat_peers")).toBe(false);
    expect(
      hasMetricSamples([{ t: "t", state: "up", metrics: {} }], "mlat_peers"),
    ).toBe(false);
  });

  it("is true when at least one sample has a reading", () => {
    expect(
      hasMetricSamples([sample("t", null), sample("t2", 4)], "mlat_peers"),
    ).toBe(true);
  });
});

describe("buildFeederMetricChart", () => {
  const baseParams = {
    metricKey: "mlat_peers",
    window: "24h" as const,
    timezone: "UTC",
    seriesName: "MLAT peers",
    unitLabel: "peers",
    formatValue: (value: number) => `${value} peers`,
  };

  it("returns the empty state when no sample has a reading", () => {
    const result = buildFeederMetricChart({
      ...baseParams,
      samples: [sample("2026-09-26T00:00:00.000Z", null)],
    });
    expect(result.buildOption(fakeTheme())).toBeNull();
    expect(result.summary).toBe("No mlat peers samples in this window.");
  });

  it("summarizes the latest and peak readings", () => {
    const result = buildFeederMetricChart({
      ...baseParams,
      samples: [
        sample("2026-09-26T00:00:00.000Z", 3),
        sample("2026-09-26T01:00:00.000Z", null),
        sample("2026-09-26T02:00:00.000Z", 7),
      ],
    });
    expect(result.summary).toBe(
      "MLAT peers: 2 samples. Latest 7 peers, peak 7 peers.",
    );
    const option = result.buildOption(fakeTheme());
    expect(option).not.toBeNull();
  });
});

function fakeTheme() {
  return {
    mode: "light",
    ink: "#000",
    mutedInk: "#666",
    grid: "#ccc",
    series: ["#111", "#222", "#333"],
  } as unknown as Parameters<
    ReturnType<typeof buildFeederMetricChart>["buildOption"]
  >[0];
}
