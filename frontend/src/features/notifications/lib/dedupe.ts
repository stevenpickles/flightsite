/**
 * "One match, one notification", held for the life of the tab (SPEC §48).
 *
 * **The guarantee is the backend's; this is the client's half of keeping it.**
 * Slice 038's two partial unique indexes on `alert_matches` are what make a
 * rule fire once per sighting, and `alert_events()` emits exactly one activity
 * event per row it actually recorded — so a distinct event id *is* a distinct
 * match, and SPEC §48's allowed extra ("a newly matched higher-priority
 * condition may create another notification") arrives as its own id with no
 * special case here. Re-deriving the rule/sighting identity on the client
 * would be a second, drifting implementation of a guarantee that already
 * holds.
 *
 * What the client must still stop is the same *event* being handled twice:
 * a socket that reconnects while a frame is in flight, a React StrictMode
 * double effect, or a Live Map remount. Module scope rather than store state
 * is deliberate — `useActivityFeedStore` resets on socket teardown (so its own
 * id check cannot outlive a remount), while what a user has already been shown
 * must outlive one.
 *
 * Bounded, because a tab left open for weeks must not accumulate ids without
 * limit. The bound is far above any plausible burst, and eviction is oldest
 * first, so re-notifying could only happen for an event pushed out by
 * {@link DEDUPE_CAPACITY} more recent ones — by which point the notification
 * is long gone from the user's screen anyway.
 */

/** How many recently notified event ids are remembered. A busy receiver fires
 * a few alerts an hour, so this is weeks of history in a few kilobytes. */
export const DEDUPE_CAPACITY = 500;

/** Insertion-ordered, which is what makes "evict the oldest" a `keys().next()`
 * away without a second structure. */
const notified = new Set<number>();

/**
 * Marks an event id as notified, returning `false` when it already was.
 *
 * Call this at the moment of delivery, not on receipt: an alert the user has
 * muted or has no permission for should not consume its id, so that turning
 * notifications on does not silently swallow the next repeat of a frame.
 */
export function claimNotification(eventId: number): boolean {
  if (notified.has(eventId)) {
    return false;
  }
  notified.add(eventId);
  if (notified.size > DEDUPE_CAPACITY) {
    const oldest = notified.values().next();
    if (!oldest.done) {
      notified.delete(oldest.value);
    }
  }
  return true;
}

/** Whether this event has already produced a notification. */
export function hasNotified(eventId: number): boolean {
  return notified.has(eventId);
}

/** Forgets everything — for tests, which must not leak claimed ids into one
 * another. Production has no reason to call it: the set is scoped to the tab,
 * and so is what the user has been shown. */
export function resetNotificationDedupe(): void {
  notified.clear();
}
