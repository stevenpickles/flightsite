import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  NO_NOTIFICATIONS,
  useNotificationStore,
  wantsSeverity,
} from "@/features/notifications/store/useNotificationStore";
import type { AlertSeverity } from "@/lib/api/sightings";
import { installNotificationMock } from "@/test/notificationMock";

const ALL_ON = {
  enabled: true,
  info: true,
  interesting: true,
  high: true,
  critical: true,
};

beforeEach(() => {
  useNotificationStore.getState().reset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  useNotificationStore.getState().reset();
});

describe("useNotificationStore", () => {
  it("starts with nothing enabled, because the config has not loaded yet", () => {
    // SPEC §45: "do not silently enable every possible notification".
    expect(useNotificationStore.getState().preferences).toEqual(
      NO_NOTIFICATIONS,
    );
  });

  it("mirrors the server's preferences", () => {
    useNotificationStore.getState().setPreferences(ALL_ON);

    expect(useNotificationStore.getState().preferences).toEqual(ALL_ON);
  });

  it("re-reads the browser's permission without prompting", () => {
    const api = installNotificationMock({ permission: "denied" });

    expect(useNotificationStore.getState().refreshPermission()).toBe("denied");
    expect(useNotificationStore.getState().permission).toBe("denied");
    expect(api.requestPermission).not.toHaveBeenCalled();
  });

  it("counts what was delivered and what was not, for diagnostics", () => {
    const store = useNotificationStore.getState();
    store.recordDelivered();
    store.recordSuppressed();
    store.recordError("Notification is not a constructor");

    const state = useNotificationStore.getState();
    expect(state.delivered).toBe(1);
    // A failure is also an alert the user wanted and did not get.
    expect(state.suppressed).toBe(2);
    expect(state.lastError).toBe("Notification is not a constructor");
  });

  it("clears the counters on reset", () => {
    useNotificationStore.getState().recordSuppressed();
    useNotificationStore.getState().reset();

    expect(useNotificationStore.getState().suppressed).toBe(0);
    expect(useNotificationStore.getState().lastError).toBeNull();
  });
});

describe("wantsSeverity", () => {
  it("is false for every severity while the master switch is off", () => {
    const off = { ...ALL_ON, enabled: false };

    for (const severity of [
      "info",
      "interesting",
      "high",
      "critical",
    ] as const) {
      expect(wantsSeverity(off, severity)).toBe(false);
    }
  });

  it("keeps the per-severity choices independent", () => {
    const preferences = { ...ALL_ON, info: false };

    expect(wantsSeverity(preferences, "info")).toBe(false);
    expect(wantsSeverity(preferences, "critical")).toBe(true);
  });

  it("does not notify for a severity this build has never heard of", () => {
    expect(wantsSeverity(ALL_ON, "catastrophic" as AlertSeverity)).toBe(false);
  });
});
