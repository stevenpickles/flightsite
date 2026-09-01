import { beforeEach, describe, expect, it } from "vitest";

import {
  claimNotification,
  DEDUPE_CAPACITY,
  hasNotified,
  resetNotificationDedupe,
} from "@/features/notifications/lib/dedupe";

beforeEach(() => {
  resetNotificationDedupe();
});

describe("claimNotification", () => {
  it("claims an event once", () => {
    expect(claimNotification(11)).toBe(true);
    expect(hasNotified(11)).toBe(true);
  });

  it("refuses a second claim on the same event", () => {
    claimNotification(11);

    expect(claimNotification(11)).toBe(false);
  });

  it("treats a different event as different, which is how a severity upgrade notifies again", () => {
    // Slice 038 records an upgraded match as its own row with its own
    // activity event, which is SPEC §48's allowed extra notification.
    expect(claimNotification(11)).toBe(true);
    expect(claimNotification(12)).toBe(true);
  });

  it("bounds what it remembers, evicting the oldest first", () => {
    for (let id = 1; id <= DEDUPE_CAPACITY; id += 1) {
      claimNotification(id);
    }
    expect(hasNotified(1)).toBe(true);

    claimNotification(DEDUPE_CAPACITY + 1);

    expect(hasNotified(1)).toBe(false);
    expect(hasNotified(2)).toBe(true);
    expect(hasNotified(DEDUPE_CAPACITY + 1)).toBe(true);
  });

  it("forgets everything on reset", () => {
    claimNotification(11);
    resetNotificationDedupe();

    expect(hasNotified(11)).toBe(false);
  });
});
