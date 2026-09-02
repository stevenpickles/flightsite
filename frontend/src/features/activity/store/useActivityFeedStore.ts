/**
 * The activity events this session has received live, over the WebSocket.
 *
 * Deliberately *only* the live ones. The feed's history lives in
 * `activity_events` and is read over REST; this store holds the tail that has
 * arrived since the socket connected, and the panel merges the two
 * ({@link mergeActivityEvents}). Keeping them apart is what makes the split
 * honest — TanStack Query owns the fetched page and its cache, and this owns a
 * stream that has no cache and no replay.
 *
 * **Where the socket actually is.** Only `features/map/aircraft/AircraftLayer`
 * mounts `useLiveConnection`, so events flow into this store only while the
 * Live Map is mounted. That is intentional and not an oversight to be "fixed"
 * by hoisting socket ownership: the standalone `/activity` route reads the
 * same events from `GET /api/v1/activity`, where they are already durable, and
 * opening a second live socket for a page that renders history would cost a
 * connection to deliver rows the REST call already returned. `lib/api/receiver.ts`
 * documents the same division for `ReceiverInfo`.
 *
 * Written once per frame through `getState()`, like the live aircraft store,
 * so the socket never causes a render of its own for a component that is not
 * subscribed.
 */

import { create } from "zustand";

import type { ActivityEvent } from "@/lib/api/activity";

/**
 * How many live events are kept.
 *
 * The panel shows a handful and the standalone page pages through the REST
 * history, so this only has to be deep enough that a user who leaves the map
 * open for an afternoon can scroll the panel back over what they missed. A
 * hundred is a few hours of a busy receiver at the rate these events actually
 * fire (a few an hour once a receiver is past its first days), and it bounds
 * the memory a long-lived tab can accumulate.
 */
export const MAX_LIVE_EVENTS = 100;

export interface ActivityFeedState {
  /** Newest first, capped at {@link MAX_LIVE_EVENTS}. */
  events: ActivityEvent[];
  /**
   * Ingests one `activity_batch` frame — a whole detector pass — in a single
   * update (§4.4).
   *
   * A batch, not an event, because that is what the socket now delivers: the
   * server sends one frame per pass so a first-run backlog cannot evict the
   * client (slice 057). One `set` per pass rather than per event is the
   * incidental win — a 500-event first-run pass renders the panel once.
   *
   * The frame carries the pass oldest-first (the server sorts by event id, and
   * `docs/API.md` §3.9 numbers them in the order they were recorded), so it is
   * prepended reversed to keep this list newest-first.
   */
  addEvents: (events: readonly ActivityEvent[]) => void;
  /** Returns the store to its initial state — used when the socket is torn
   * down, so a remount never shows a stream from a dead connection. */
  reset: () => void;
}

function initialState(): Pick<ActivityFeedState, "events"> {
  return { events: [] };
}

export const useActivityFeedStore = create<ActivityFeedState>((set) => ({
  ...initialState(),

  addEvents: (incoming) => {
    if (incoming.length === 0) {
      return;
    }
    set((state) => {
      // The server never re-sends an event, but a reconnect can overlap with a
      // REST refetch and the panel merges both — so dropping a duplicate id
      // here as well keeps the store itself a set. The seen-set is built once
      // per pass rather than rescanning the array per event, which is what
      // keeps a 500-event first-run batch linear instead of quadratic.
      const seen = new Set(state.events.map((existing) => existing.id));
      const fresh: ActivityEvent[] = [];
      for (const event of incoming) {
        if (!seen.has(event.id)) {
          seen.add(event.id);
          fresh.push(event);
        }
      }
      if (fresh.length === 0) {
        return state;
      }
      // `reverse` is safe: `fresh` is this call's own array, never the
      // caller's. Newest event of the pass ends up at the head.
      fresh.reverse();
      return {
        events: [...fresh, ...state.events].slice(0, MAX_LIVE_EVENTS),
      };
    });
  },

  reset: () => {
    set(initialState());
  },
}));

/**
 * The REST page and the live stream as one newest-first list.
 *
 * Pure, and outside the store, because both callers (the panel and its tests)
 * want it without a React subscription. Dedupes by `id`: an event can
 * legitimately appear in both halves — it arrived over the socket and was then
 * included in a refetched page — and the two copies are the same row, built by
 * the same backend serializer.
 *
 * Sorted by `at` descending with `id` descending as the tie-break, matching
 * the server's own ordering (`docs/API.md` §3.9), so a burst written in one
 * instant reads the same way here as it does on the standalone page.
 */
export function mergeActivityEvents(
  live: readonly ActivityEvent[],
  fetched: readonly ActivityEvent[],
): ActivityEvent[] {
  const byId = new Map<number, ActivityEvent>();
  for (const event of [...fetched, ...live]) {
    byId.set(event.id, event);
  }
  return [...byId.values()].sort((a, b) =>
    a.at === b.at ? b.id - a.id : a.at < b.at ? 1 : -1,
  );
}
