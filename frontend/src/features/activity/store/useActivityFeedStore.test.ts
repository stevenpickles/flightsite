import { beforeEach, describe, expect, it } from "vitest";

import {
  MAX_LIVE_EVENTS,
  mergeActivityEvents,
  useActivityFeedStore,
} from "@/features/activity/store/useActivityFeedStore";
import { activityEvent } from "@/test/activityApiMock";

beforeEach(() => {
  useActivityFeedStore.getState().reset();
});

describe("useActivityFeedStore", () => {
  it("keeps live events newest first", () => {
    const store = useActivityFeedStore.getState;
    store().addEvent(activityEvent({ id: 1 }));
    store().addEvent(activityEvent({ id: 2 }));

    expect(store().events.map((event) => event.id)).toEqual([2, 1]);
  });

  it("ignores an event id it already holds", () => {
    const store = useActivityFeedStore.getState;
    store().addEvent(activityEvent({ id: 7 }));
    store().addEvent(activityEvent({ id: 7 }));

    expect(store().events).toHaveLength(1);
  });

  it("caps the stream so a long-lived tab cannot grow without bound", () => {
    const store = useActivityFeedStore.getState;
    for (let id = 1; id <= MAX_LIVE_EVENTS + 10; id += 1) {
      store().addEvent(activityEvent({ id }));
    }

    expect(store().events).toHaveLength(MAX_LIVE_EVENTS);
    // The newest survive; the oldest fall off the end.
    expect(store().events[0]?.id).toBe(MAX_LIVE_EVENTS + 10);
  });

  it("empties on reset, so a remount shows no dead connection's stream", () => {
    const store = useActivityFeedStore.getState;
    store().addEvent(activityEvent({ id: 1 }));
    store().reset();

    expect(store().events).toEqual([]);
  });
});

describe("mergeActivityEvents", () => {
  it("orders both sources newest first by `at`", () => {
    const merged = mergeActivityEvents(
      [activityEvent({ id: 3, at: "2026-08-31T15:00:00.000Z" })],
      [
        activityEvent({ id: 1, at: "2026-08-31T13:00:00.000Z" }),
        activityEvent({ id: 2, at: "2026-08-31T14:00:00.000Z" }),
      ],
    );
    expect(merged.map((event) => event.id)).toEqual([3, 2, 1]);
  });

  it("breaks a shared instant by id, descending", () => {
    // A pass writes several events with one timestamp; the server orders them
    // by id descending, and so must the client, or a page boundary through
    // the burst would repeat or skip a row.
    const at = "2026-08-31T14:00:00.000Z";
    const merged = mergeActivityEvents(
      [],
      [activityEvent({ id: 5, at }), activityEvent({ id: 9, at })],
    );
    expect(merged.map((event) => event.id)).toEqual([9, 5]);
  });

  it("keeps one copy of an event present in both halves", () => {
    const merged = mergeActivityEvents(
      [activityEvent({ id: 42 })],
      [activityEvent({ id: 42 })],
    );
    expect(merged).toHaveLength(1);
  });

  it("prefers the live copy of a duplicated event", () => {
    // Both are built by the same serializer, so they agree — but the live one
    // is the later observation, and taking it means the merge has one rule
    // rather than a tie it resolves by accident of iteration order.
    const merged = mergeActivityEvents(
      [activityEvent({ id: 42, severity: "high" })],
      [activityEvent({ id: 42, severity: "info" })],
    );
    expect(merged[0]?.severity).toBe("high");
  });
});
