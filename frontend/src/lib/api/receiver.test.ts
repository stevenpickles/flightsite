import { afterEach, describe, expect, it, vi } from "vitest";

import { getReceiver } from "@/lib/api/receiver";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getReceiver", () => {
  it("resolves the parsed receiver info on a 2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              site_name: "Test",
              latitude: 47.6,
              longitude: -122.3,
              antenna_height_ft: 10,
              timezone: "UTC",
              units: "aviation",
              display_radius_nm: 250,
              alert_radius_nm: null,
              demo_mode: false,
              t0: null,
            }),
            { status: 200 },
          ),
        ),
      ),
    );

    const receiver = await getReceiver();

    expect(receiver.site_name).toBe("Test");
    expect(receiver.units).toBe("aviation");
  });

  it("rejects with a readable error on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("", { status: 503 }))),
    );

    await expect(getReceiver()).rejects.toThrow("status 503");
  });
});
