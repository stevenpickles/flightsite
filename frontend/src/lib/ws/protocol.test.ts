import { describe, expect, it } from "vitest";

import {
  asActivityEvent,
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

describe("asActivityEvent", () => {
  it("narrows a well-formed §3.9 event", () => {
    const event = asActivityEvent({
      id: 4021,
      type: "range_record",
      severity: "interesting",
      at: "2026-08-31T14:03:22.418Z",
      icao: "ae1463",
      sighting_id: 88213,
      payload: { range_nm: 412.75 },
    });
    expect(event).toEqual({
      id: 4021,
      type: "range_record",
      severity: "interesting",
      at: "2026-08-31T14:03:22.418Z",
      icao: "ae1463",
      sighting_id: 88213,
      payload: { range_nm: 412.75 },
    });
  });

  it("keeps a type this build predates rather than dropping the event", () => {
    // §6 from the other side: the vocabulary may grow, and the feed renders
    // an unknown type from its own slug.
    expect(asActivityEvent({ id: 1, type: "maintenance_issue" })?.type).toBe(
      "maintenance_issue",
    );
  });

  it("defaults the optional members a receiver-wide event has none of", () => {
    const event = asActivityEvent({ id: 7, type: "receiver_offline" });
    expect(event).toEqual({
      id: 7,
      type: "receiver_offline",
      severity: "info",
      at: "",
      icao: null,
      sighting_id: null,
      payload: {},
    });
  });

  it("falls back to info for a severity outside the §2.8 ladder", () => {
    expect(
      asActivityEvent({ id: 7, type: "milestone", severity: "urgent" })
        ?.severity,
    ).toBe("info");
  });

  it.each([
    ["a non-object body", "activity"],
    ["a missing id", { type: "milestone" }],
    ["a non-numeric id", { id: "7", type: "milestone" }],
    ["a missing type", { id: 7 }],
  ])("returns null for %s", (_label, data) => {
    // Stricter than the snapshot/delta narrowings on purpose: `id` is what the
    // feed dedupes on and `type` is what decides the rendering, so an event
    // missing either could only ever be a blank row.
    expect(asActivityEvent(data)).toBeNull();
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
