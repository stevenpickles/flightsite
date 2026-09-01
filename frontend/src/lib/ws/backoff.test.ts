import { describe, expect, it } from "vitest";

import { backoffDelayMs, DEFAULT_BACKOFF } from "@/lib/ws/backoff";

const NO_JITTER = () => 0;
const MAX_JITTER = () => 0.999999;

describe("backoffDelayMs", () => {
  it("doubles the base delay with each attempt", () => {
    const delays = [1, 2, 3, 4].map((attempt) =>
      backoffDelayMs(attempt, DEFAULT_BACKOFF, NO_JITTER),
    );
    // Half of 500, 1000, 2000, 4000 — the fixed half of the equal-jitter curve.
    expect(delays).toEqual([250, 500, 1000, 2000]);
  });

  it("clamps to the ceiling however many attempts have failed", () => {
    expect(backoffDelayMs(50, DEFAULT_BACKOFF, MAX_JITTER)).toBeLessThanOrEqual(
      DEFAULT_BACKOFF.maxDelayMs,
    );
    expect(backoffDelayMs(50, DEFAULT_BACKOFF, NO_JITTER)).toBe(
      DEFAULT_BACKOFF.maxDelayMs / 2,
    );
  });

  it("never returns less than half the exponential delay", () => {
    // The point of equal rather than full jitter: an unlucky draw must not
    // produce a near-immediate retry against a backend that just shed us.
    for (let attempt = 1; attempt <= 6; attempt += 1) {
      const floor = backoffDelayMs(attempt, DEFAULT_BACKOFF, NO_JITTER);
      const drawn = backoffDelayMs(attempt, DEFAULT_BACKOFF, () => 0.0001);
      expect(drawn).toBeGreaterThanOrEqual(floor);
    }
  });

  it("spreads retries across the jitter window", () => {
    const low = backoffDelayMs(3, DEFAULT_BACKOFF, NO_JITTER);
    const high = backoffDelayMs(3, DEFAULT_BACKOFF, MAX_JITTER);
    expect(high).toBeGreaterThan(low);
    expect(high).toBeLessThanOrEqual(2 * low);
  });

  it("treats a zero or negative attempt as the first retry", () => {
    expect(backoffDelayMs(0, DEFAULT_BACKOFF, NO_JITTER)).toBe(250);
    expect(backoffDelayMs(-3, DEFAULT_BACKOFF, NO_JITTER)).toBe(250);
  });
});
