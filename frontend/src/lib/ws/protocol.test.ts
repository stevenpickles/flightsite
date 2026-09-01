import { describe, expect, it } from "vitest";

import {
  asDeltaData,
  asSnapshotData,
  LIVE_WS_PATH,
  parseServerFrame,
  PONG_MESSAGE,
} from "@/lib/ws/protocol";
import { makeAircraft } from "@/test/liveAircraftFixtures";

describe("parseServerFrame", () => {
  it("parses a §4.1 envelope", () => {
    const frame = parseServerFrame(
      JSON.stringify({
        type: "delta",
        seq: 7,
        ts: "2026-08-31T14:03:22.418Z",
        data: { updated: [] },
      }),
    );
    expect(frame).toEqual({
      type: "delta",
      seq: 7,
      ts: "2026-08-31T14:03:22.418Z",
      data: { updated: [] },
    });
  });

  it("keeps unknown frame types rather than rejecting them", () => {
    // §6: a client must ignore types it does not know. Slice 035 adds
    // `activity` to this same socket, and it must not look like corruption.
    const frame = parseServerFrame(
      JSON.stringify({ type: "activity", seq: 3, ts: "t", data: {} }),
    );
    expect(frame?.type).toBe("activity");
    expect(frame?.seq).toBe(3);
  });

  it.each([
    ["non-string input", 42],
    ["malformed JSON", "{"],
    ["a JSON array", "[1,2,3]"],
    ["a missing seq", JSON.stringify({ type: "delta", ts: "t" })],
    ["a non-numeric seq", JSON.stringify({ type: "delta", seq: "7" })],
    ["a missing type", JSON.stringify({ seq: 7 })],
  ])("returns null for %s", (_label, raw) => {
    expect(parseServerFrame(raw)).toBeNull();
  });
});

describe("asSnapshotData", () => {
  it("extracts aircraft and receiver", () => {
    const aircraft = makeAircraft();
    const data = asSnapshotData({
      aircraft: [aircraft],
      receiver: { timezone: "UTC" },
    });
    expect(data?.aircraft).toEqual([aircraft]);
    expect(data?.receiver).toEqual({ timezone: "UTC" });
  });

  it("tolerates a missing receiver block", () => {
    expect(asSnapshotData({ aircraft: [] })).toEqual({
      aircraft: [],
      receiver: null,
    });
  });

  it("rejects a body with no aircraft list", () => {
    expect(asSnapshotData({ receiver: {} })).toBeNull();
    expect(asSnapshotData(null)).toBeNull();
  });
});

describe("asDeltaData", () => {
  it("extracts the three lists", () => {
    const aircraft = makeAircraft();
    expect(
      asDeltaData({
        updated: [aircraft],
        stale: ["a9c2f0"],
        removed: ["ff0011"],
      }),
    ).toEqual({
      updated: [aircraft],
      stale: ["a9c2f0"],
      removed: ["ff0011"],
    });
  });

  it("defaults absent lists to empty", () => {
    expect(asDeltaData({ updated: [makeAircraft()] })).toEqual({
      updated: [makeAircraft()],
      stale: [],
      removed: [],
    });
  });

  it("drops non-string icaos from the flag lists", () => {
    expect(asDeltaData({ stale: ["a9c2f0", 7, null] })?.stale).toEqual([
      "a9c2f0",
    ]);
  });

  it("rejects a non-object body", () => {
    expect(asDeltaData("delta")).toBeNull();
  });
});

describe("protocol constants", () => {
  it("targets the documented path", () => {
    expect(LIVE_WS_PATH).toBe("/api/v1/ws/live");
  });

  it("answers a ping with the documented pong object", () => {
    expect(JSON.parse(PONG_MESSAGE)).toEqual({ type: "pong" });
  });
});
