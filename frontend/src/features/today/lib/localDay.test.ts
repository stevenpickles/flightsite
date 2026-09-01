import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  receiverLocalDate,
  useReceiverLocalDate,
} from "@/features/today/lib/localDay";

describe("receiverLocalDate", () => {
  it("resolves against the receiver's zone, not UTC", () => {
    // 2026-09-01T02:00:00Z is already the 1st in UTC, but still the 31st in
    // Los Angeles (UTC-7 in August/September DST) — the exact case §3.7's
    // "today" must get right for a receiver west of the browser.
    const at = new Date("2026-09-01T02:00:00Z");

    expect(receiverLocalDate("America/Los_Angeles", at)).toBe("2026-08-31");
    expect(receiverLocalDate("UTC", at)).toBe("2026-09-01");
  });

  it("resolves against a zone ahead of UTC the same way", () => {
    // 2026-08-31T20:00:00Z is still the 31st in UTC but already the 1st in
    // Kolkata (UTC+5:30).
    const at = new Date("2026-08-31T20:00:00Z");

    expect(receiverLocalDate("Asia/Kolkata", at)).toBe("2026-09-01");
  });

  it("falls back to UTC's date rather than throwing on an unrecognized zone", () => {
    const at = new Date("2026-09-01T00:00:00Z");

    expect(receiverLocalDate("Not/AZone", at)).toBe("2026-09-01");
  });
});

describe("useReceiverLocalDate", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns the receiver-local date for the current instant", () => {
    vi.setSystemTime(new Date("2026-08-31T12:00:00Z"));

    const { result } = renderHook(() =>
      useReceiverLocalDate("America/Los_Angeles"),
    );

    expect(result.current).toBe("2026-08-31");
  });

  it("rolls over once receiver-local midnight passes, on its own", () => {
    // 2026-08-31T06:59:00Z is 2026-08-30T23:59 in Los Angeles; a minute
    // later crosses receiver-local midnight into the 31st.
    vi.setSystemTime(new Date("2026-08-31T06:59:00Z"));
    const { result } = renderHook(() =>
      useReceiverLocalDate("America/Los_Angeles"),
    );
    expect(result.current).toBe("2026-08-30");

    act(() => {
      vi.setSystemTime(new Date("2026-08-31T07:01:00Z"));
      vi.advanceTimersByTime(30_000);
    });

    expect(result.current).toBe("2026-08-31");
  });

  it("recomputes immediately when the timezone itself changes", () => {
    vi.setSystemTime(new Date("2026-09-01T02:00:00Z"));
    const { result, rerender } = renderHook(
      ({ timezone }: { timezone: string }) => useReceiverLocalDate(timezone),
      { initialProps: { timezone: "UTC" } },
    );
    expect(result.current).toBe("2026-09-01");

    rerender({ timezone: "America/Los_Angeles" });

    expect(result.current).toBe("2026-08-31");
  });
});
