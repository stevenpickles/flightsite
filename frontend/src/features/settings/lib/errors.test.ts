import { describe, expect, it } from "vitest";

import {
  fieldErrorsFrom,
  fieldMessage,
  generalErrorMessage,
} from "@/features/settings/lib/errors";
import { ApiError } from "@/lib/api/client";

describe("fieldErrorsFrom", () => {
  it("maps a validation-error array onto dotted field paths", () => {
    const error = new ApiError(422, [
      {
        loc: ["location", "latitude"],
        msg: "Input should be <= 90",
        type: "less_than_equal",
      },
      {
        loc: ["retention", "high_res_metric_days"],
        msg: "Input should be greater than or equal to 7",
        type: "greater_than_equal",
      },
    ]);
    expect(fieldErrorsFrom(error)).toEqual({
      "location.latitude": "Input should be <= 90",
      "retention.high_res_metric_days":
        "Input should be greater than or equal to 7",
    });
  });

  it("returns an empty map for a plain-string ConfigError detail", () => {
    const error = new ApiError(422, "unknown configuration key 'bogus'");
    expect(fieldErrorsFrom(error)).toEqual({});
  });

  it("returns an empty map for a non-ApiError", () => {
    expect(fieldErrorsFrom(new Error("network down"))).toEqual({});
  });

  it("ignores entries missing a usable loc or msg", () => {
    const error = new ApiError(422, [
      { loc: [], msg: "top-level error", type: "value_error" },
    ]);
    expect(fieldErrorsFrom(error)).toEqual({});
  });
});

describe("generalErrorMessage", () => {
  it("is null once there is nothing to report", () => {
    expect(generalErrorMessage(null, {})).toBeNull();
  });

  it("surfaces a plain-string ConfigError detail", () => {
    const error = new ApiError(422, "unknown configuration key 'bogus'");
    expect(generalErrorMessage(error, {})).toBe(
      "unknown configuration key 'bogus'",
    );
  });

  it("is null for a validation-error array once every entry mapped to a field", () => {
    const error = new ApiError(422, [
      { loc: ["location", "latitude"], msg: "bad value", type: "value_error" },
    ]);
    const fieldErrors = fieldErrorsFrom(error);
    expect(generalErrorMessage(error, fieldErrors)).toBeNull();
  });

  it("falls back to the ApiError message when no field could be mapped", () => {
    const error = new ApiError(422, [
      { loc: [], msg: "top-level error", type: "value_error" },
    ]);
    expect(generalErrorMessage(error, {})).toBe(error.message);
  });

  it("surfaces a plain network/Error message", () => {
    expect(generalErrorMessage(new Error("network down"), {})).toBe(
      "network down",
    );
  });

  it("falls back to a generic message for a non-Error value", () => {
    expect(generalErrorMessage("boom", {})).toBe("Could not save changes.");
  });
});

describe("fieldMessage", () => {
  it("is empty and non-blocking when there is nothing to report", () => {
    expect(fieldMessage(null, undefined)).toEqual({
      message: null,
      blocking: false,
    });
    expect(fieldMessage(null, null)).toEqual({
      message: null,
      blocking: false,
    });
  });

  it("blocks on a client-side error, ignoring any server message", () => {
    expect(
      fieldMessage("Enter a value greater than 0", "Rejected by the server"),
    ).toEqual({
      message: "Enter a value greater than 0",
      blocking: true,
    });
  });

  it("shows a server-side message without blocking (R4-02)", () => {
    // A rejected save must stay retryable: the message is shown, but Save
    // is never gated on it, or the section would be unsavable until an
    // unrelated edit or a page reload.
    expect(fieldMessage(null, "Input should be greater than 0")).toEqual({
      message: "Input should be greater than 0",
      blocking: false,
    });
  });

  it("treats an empty server string the same as no server error", () => {
    expect(fieldMessage(null, "")).toEqual({ message: null, blocking: false });
  });
});
