import { afterEach, describe, expect, it, vi } from "vitest";

import { testDecoderConnection } from "@/lib/api/decoder";
import {
  installConfigApiMock,
  successConnectionTestResult,
} from "@/test/configApiMock";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("testDecoderConnection", () => {
  it("POSTs the candidate receiver as the JSON body", async () => {
    const { fetchMock } = installConfigApiMock({
      decoderTestResult: successConnectionTestResult(),
    });
    const receiver = {
      host: "192.168.1.10",
      port: 8080,
      path: "/data/aircraft.json",
      poll_interval_s: 1,
    };

    const result = await testDecoderConnection(receiver);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/internal/decoder/test");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(JSON.parse(String(init.body))).toEqual(receiver);
    expect(result.ok).toBe(true);
  });

  it("sends no body when testing the currently configured receiver", async () => {
    const { fetchMock } = installConfigApiMock({
      decoderTestResult: successConnectionTestResult(),
    });

    await testDecoderConnection();

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
  });

  it("returns a failed result's error kind and detail unchanged", async () => {
    installConfigApiMock({
      decoderTestResult: {
        ok: false,
        url: "http://10.0.0.5:8080/data/aircraft.json",
        elapsed_ms: 8000,
        error: "http_error",
        detail: "404 Not Found",
        aircraft_count: null,
        positioned_count: null,
        flavor: null,
        decoder_time: null,
      },
    });

    const result = await testDecoderConnection({
      host: "10.0.0.5",
      port: 8080,
      path: "/wrong/path.json",
      poll_interval_s: 1,
    });

    expect(result.ok).toBe(false);
    expect(result.error).toBe("http_error");
    expect(result.detail).toBe("404 Not Found");
  });
});
