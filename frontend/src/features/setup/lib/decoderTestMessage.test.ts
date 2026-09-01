import { describe, expect, it } from "vitest";

import {
  describeConnectionFailure,
  describeConnectionSuccess,
} from "@/features/setup/lib/decoderTestMessage";
import {
  failureConnectionTestResult,
  successConnectionTestResult,
} from "@/test/configApiMock";

describe("describeConnectionSuccess", () => {
  it("names the decoder flavor and aircraft counts", () => {
    const message = describeConnectionSuccess(
      successConnectionTestResult({
        flavor: "readsb",
        aircraft_count: 37,
        positioned_count: 24,
      }),
    );
    expect(message).toBe(
      "Connected — found readsb, 37 aircraft (24 with positions).",
    );
  });

  it("uses a generic label when the flavor is unknown", () => {
    const message = describeConnectionSuccess(
      successConnectionTestResult({
        flavor: "unknown",
        aircraft_count: 5,
        positioned_count: 5,
      }),
    );
    expect(message).toContain("found a decoder");
  });
});

describe("describeConnectionFailure", () => {
  it("maps a known error kind to its label and includes the detail", () => {
    const message = describeConnectionFailure(
      failureConnectionTestResult({
        error: "unreachable",
        detail: "Connection refused",
      }),
    );
    expect(message).toBe("Unreachable: Connection refused");
  });

  it("maps http_error and invalid_document to their labels", () => {
    expect(
      describeConnectionFailure(
        failureConnectionTestResult({ error: "http_error", detail: "404" }),
      ),
    ).toBe("Endpoint returned an error: 404");
    expect(
      describeConnectionFailure(
        failureConnectionTestResult({
          error: "invalid_document",
          detail: "not JSON",
        }),
      ),
    ).toBe("Response was not a decoder aircraft document: not JSON");
  });

  it("falls back to a generic message when there is no error kind or detail", () => {
    expect(
      describeConnectionFailure(
        failureConnectionTestResult({ error: null, detail: null }),
      ),
    ).toBe("Connection failed");
  });
});
