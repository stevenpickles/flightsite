import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useRelativeAge } from "@/features/aircraft-detail/lib/useRelativeAge";

describe("useRelativeAge", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-31T00:00:10Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns null when there is no last-seen instant", () => {
    const { result } = renderHook(() => useRelativeAge(null));
    expect(result.current).toBeNull();
  });

  it("computes the initial age from the last-seen instant", () => {
    const { result } = renderHook(() => useRelativeAge("2026-08-31T00:00:00Z"));
    expect(result.current).toBe("10s ago");
  });

  it("ticks forward on its own every second, independent of new frames", () => {
    const { result } = renderHook(() => useRelativeAge("2026-08-31T00:00:00Z"));
    expect(result.current).toBe("10s ago");

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(result.current).toBe("15s ago");
  });

  it("recomputes immediately when the selected instant changes, without waiting for the next tick", () => {
    const { result, rerender } = renderHook(
      ({ lastSeen }: { lastSeen: string | null }) => useRelativeAge(lastSeen),
      { initialProps: { lastSeen: "2026-08-31T00:00:00Z" } },
    );
    expect(result.current).toBe("10s ago");

    rerender({ lastSeen: "2026-08-31T00:00:08Z" });

    expect(result.current).toBe("2s ago");
  });
});
