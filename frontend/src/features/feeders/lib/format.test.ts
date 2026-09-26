import { describe, expect, it } from "vitest";

import {
  formatAdsbOutChip,
  formatBytesRate,
  formatCountOrNotObserved,
  formatMlatChip,
  formatPerMinute,
  formatRangeNm,
  formatRelativeAndAbsolute,
  NOT_AVAILABLE,
  NOT_OBSERVED,
} from "@/features/feeders/lib/format";

const NOW_MS = new Date("2026-09-26T12:00:00.000Z").getTime();

describe("formatRelativeAndAbsolute", () => {
  it("renders NOT_AVAILABLE for null", () => {
    expect(formatRelativeAndAbsolute(null, "UTC", NOW_MS)).toBe(NOT_AVAILABLE);
  });

  it("combines the relative age with the receiver-local absolute time", () => {
    const result = formatRelativeAndAbsolute(
      "2026-09-26T11:55:00.000Z",
      "UTC",
      NOW_MS,
    );
    expect(result).toBe("5m ago (2026-09-26 11:55)");
  });
});

describe("receiver-uplink formatters render NOT_OBSERVED for null", () => {
  it("formatBytesRate", () => {
    expect(formatBytesRate(null)).toBe(NOT_OBSERVED);
    expect(formatBytesRate(512)).toBe("512 B/s");
    expect(formatBytesRate(2048)).toBe("2.0 KB/s");
  });

  it("formatCountOrNotObserved", () => {
    expect(formatCountOrNotObserved(null)).toBe(NOT_OBSERVED);
    expect(formatCountOrNotObserved(42)).toBe("42");
  });

  it("formatPerMinute", () => {
    expect(formatPerMinute(null)).toBe(NOT_OBSERVED);
    expect(formatPerMinute(12.6)).toBe("13/min");
  });

  it("formatRangeNm", () => {
    expect(formatRangeNm(null)).toBe(NOT_OBSERVED);
    expect(formatRangeNm(87.3)).toBe("87 nm");
  });
});

describe("formatMlatChip", () => {
  it("is null when the feeder has no MLAT signal", () => {
    expect(formatMlatChip(null)).toBeNull();
  });

  it("renders peers and sync percentage", () => {
    expect(
      formatMlatChip({
        peers: 6,
        good_sync_pct: 98.42,
        bad_sync_timeout_s: 0,
        last_bad_sync_at: null,
      }),
    ).toBe("6 peers · 98.4% sync");
  });

  it("renders unknown parts without crashing", () => {
    expect(
      formatMlatChip({
        peers: null,
        good_sync_pct: null,
        bad_sync_timeout_s: null,
        last_bad_sync_at: null,
      }),
    ).toBe("? peers · sync unknown");
  });
});

describe("formatAdsbOutChip", () => {
  it("is null when the feeder has no ADS-B-out signal", () => {
    expect(formatAdsbOutChip(null)).toBeNull();
  });

  it("names the connection state", () => {
    expect(formatAdsbOutChip({ connected: true, since: null })).toBe(
      "ADS-B out: connected",
    );
    expect(formatAdsbOutChip({ connected: false, since: null })).toBe(
      "ADS-B out: disconnected",
    );
  });
});
