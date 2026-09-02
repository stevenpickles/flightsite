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
  it("keeps live events newest first across successive batches", () => {
    const store = useActivityFeedStore.getState;
    store().addEvents([activityEvent({ id: 1 })]);
    store().addEvents([activityEvent({ id: 2 })]);

    expect(store().events.map((event) => event.id)).toEqual([2, 1]);
  });

  it("reverses one batch, which arrives oldest first", () => {
    // `docs/API.md` §4.4: the frame carries a pass in the order it was
    // recorded (ascending event id). The store is newest first, so a batch
    // ingested in one update has to land reversed — the case a per-event loop
    // got right by accident and a batch update has to get right on purpose.
    const store = useActivityFeedStore.getState;
    store().addEvents([
      activityEvent({ id: 1 }),
      activityEvent({ id: 2 }),
      activityEvent({ id: 3 }),
    ]);

    expect(store().events.map((event) => event.id)).toEqual([3, 2, 1]);
  });

  it("puts a whole batch in front of what it already held", () => {
    const store = useActivityFeedStore.getState;
    store().addEvents([activityEvent({ id: 1 })]);
    store().addEvents([activityEvent({ id: 2 }), activityEvent({ id: 3 })]);

    expect(store().events.map((event) => event.id)).toEqual([3, 2, 1]);
  });

  it("ignores an event id it already holds", () => {
    const store = useActivityFeedStore.getState;
    store().addEvents([activityEvent({ id: 7 })]);
    store().addEvents([activityEvent({ id: 7 })]);

    expect(store().events).toHaveLength(1);
  });

  it("drops ids repeated within one batch", () => {
    const store = useActivityFeedStore.getState;
    store().addEvents([activityEvent({ id: 7 }), activityEvent({ id: 7 })]);

    expect(store().events).toHaveLength(1);
  });

  it("leaves the state object untouched when a batch is all duplicates", () => {
    // Identity matters: an unchanged reference is what stops zustand
    // re-rendering the panel for a batch that added nothing.
    const store = useActivityFeedStore.getState;
    store().addEvents([activityEvent({ id: 7 })]);
    const before = store().events;
    store().addEvents([activityEvent({ id: 7 })]);

    expect(store().events).toBe(before);
  });

  it("does nothing with an empty batch", () => {
    const store = useActivityFeedStore.getState;
    const before = store().events;
    store().addEvents([]);

    expect(store().events).toBe(before);
  });

  it("caps the stream so a long-lived tab cannot grow without bound", () => {
    const store = useActivityFeedStore.getState;
    for (let id = 1; id <= MAX_LIVE_EVENTS + 10; id += 1) {
      store().addEvents([activityEvent({ id })]);
    }

    expect(store().events).toHaveLength(MAX_LIVE_EVENTS);
    // The newest survive; the oldest fall off the end.
    expect(store().events[0]?.id).toBe(MAX_LIVE_EVENTS + 10);
  });

  it("caps a single batch larger than the whole store", () => {
    // A fresh install's first pass is hundreds of events at once — the case
    // that only exists now that a batch arrives as one update.
    const store = useActivityFeedStore.getState;
    const batch = Array.from({ length: MAX_LIVE_EVENTS + 50 }, (_, index) =>
      activityEvent({ id: index + 1 }),
    );
    store().addEvents(batch);

    expect(store().events).toHaveLength(MAX_LIVE_EVENTS);
    // Newest first means the highest id survives and the oldest are dropped.
    expect(store().events[0]?.id).toBe(MAX_LIVE_EVENTS + 50);
    expect(store().events.at(-1)?.id).toBe(51);
  });

  it("does not mutate the caller's array", () => {
    const store = useActivityFeedStore.getState;
    const batch = [activityEvent({ id: 1 }), activityEvent({ id: 2 })];
    store().addEvents(batch);

    expect(batch.map((event) => event.id)).toEqual([1, 2]);
  });

  it("empties on reset, so a remount shows no dead connection's stream", () => {
    const store = useActivityFeedStore.getState;
    store().addEvents([activityEvent({ id: 1 })]);
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
