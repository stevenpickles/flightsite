import { afterEach, describe, expect, it, vi } from "vitest";

import {
  canNotify,
  canRequest,
  readPermissionState,
  requestNotificationPermission,
} from "@/features/notifications/lib/permission";
import { installNotificationMock } from "@/test/notificationMock";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("readPermissionState", () => {
  it("reports the browser's standing answer without prompting", () => {
    const api = installNotificationMock({ permission: "granted" });

    expect(readPermissionState()).toBe("granted");
    expect(api.requestPermission).not.toHaveBeenCalled();
  });

  it("reports a denial", () => {
    installNotificationMock({ permission: "denied" });

    expect(readPermissionState()).toBe("denied");
  });

  it("treats an unrecognised value as not-yet-asked", () => {
    const api = installNotificationMock();
    api.permission = "nonsense" as NotificationPermission;

    expect(readPermissionState()).toBe("default");
  });

  it("distinguishes an insecure origin from an unsupported browser", () => {
    // The API is withheld on a plain-HTTP LAN address, which is how
    // FlightSite is normally reached (`docs/SECURITY.md` §1) — the user needs
    // to be told *that*, not a generic "unsupported".
    vi.stubGlobal("Notification", undefined);
    vi.stubGlobal("isSecureContext", false);

    expect(readPermissionState()).toBe("insecure-context");
  });

  it("reports an unsupported browser when the context is secure", () => {
    vi.stubGlobal("Notification", undefined);
    vi.stubGlobal("isSecureContext", true);

    expect(readPermissionState()).toBe("unsupported");
  });

  it("does not guess 'insecure' where the environment says nothing", () => {
    vi.stubGlobal("Notification", undefined);
    vi.stubGlobal("isSecureContext", undefined);

    expect(readPermissionState()).toBe("unsupported");
  });
});

describe("canNotify / canRequest", () => {
  it("only a granted permission delivers", () => {
    expect(canNotify("granted")).toBe(true);
    for (const state of [
      "default",
      "denied",
      "unsupported",
      "insecure-context",
    ] as const) {
      expect(canNotify(state)).toBe(false);
    }
  });

  it("only an unasked permission can still be prompted for", () => {
    expect(canRequest("default")).toBe(true);
    for (const state of [
      "granted",
      "denied",
      "unsupported",
      "insecure-context",
    ] as const) {
      expect(canRequest(state)).toBe(false);
    }
  });
});

describe("requestNotificationPermission", () => {
  it("resolves with the answer from the promise-returning API", async () => {
    const api = installNotificationMock({
      permission: "default",
      requestResult: "granted",
    });

    await expect(requestNotificationPermission()).resolves.toBe("granted");
    expect(api.requestPermission).toHaveBeenCalledTimes(1);
  });

  it("resolves with a denial the user just gave", async () => {
    installNotificationMock({
      permission: "default",
      requestResult: "denied",
    });

    await expect(requestNotificationPermission()).resolves.toBe("denied");
  });

  it("supports the legacy callback form that returns nothing", async () => {
    // Older Safari's `requestPermission(callback)` returns `undefined`;
    // awaiting that would resolve instantly with the wrong answer.
    const api = installNotificationMock({ permission: "default" });
    api.requestPermission = vi.fn(
      (callback?: (permission: NotificationPermission) => void) => {
        callback?.("granted");
        return undefined;
      },
    ) as unknown as typeof api.requestPermission;

    await expect(requestNotificationPermission()).resolves.toBe("granted");
  });

  it("falls back to the standing state when the browser refuses the request", async () => {
    const api = installNotificationMock({ permission: "default" });
    api.requestPermission = vi.fn(() => {
      throw new DOMException("insecure", "SecurityError");
    }) as unknown as typeof api.requestPermission;

    await expect(requestNotificationPermission()).resolves.toBe("default");
  });

  it("is a no-op read where the API does not exist", async () => {
    vi.stubGlobal("Notification", undefined);
    vi.stubGlobal("isSecureContext", false);

    await expect(requestNotificationPermission()).resolves.toBe(
      "insecure-context",
    );
  });
});
