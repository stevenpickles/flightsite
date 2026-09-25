/**
 * Splits a page of the activity feed into receiver-local days (review
 * R2-06).
 *
 * The feed answers "what happened while I wasn't watching?", a question
 * whose premise is a gap of hours or days — but every row rendered a bare
 * `21:43`, with no date, no separator and no `title`, so after one night the
 * top of the feed and page three of it were indistinguishable. A day header
 * answers it once per day instead of once per row.
 *
 * Consecutive runs, not a bucket map: `/api/v1/activity` returns rows in
 * descending `at` order, so a run *is* a day, and grouping this way keeps
 * the rows in exactly the order the endpoint chose rather than quietly
 * re-sorting them. A feed that ever arrived unordered would show a day twice
 * — visibly wrong, which is what you want from a violated assumption.
 *
 * "Receiver-local" is the whole point of the day key: a sighting at 21:43 in
 * New York belongs to that day, not to the 01:43 UTC day the instant is
 * stored under (SPEC §15), and not to the browser's day either.
 */

import { receiverLocalDayKey } from "@/features/aircraft-detail/lib/format";
import type { ActivityEvent } from "@/lib/api/activity";

export interface ActivityDayGroup {
  /** The receiver-local day, `"YYYY-MM-DD"` — also the React key. */
  key: string;
  /** What the header says: `"Today"`, `"Yesterday"`, or the day itself. */
  label: string;
  events: ActivityEvent[];
}

const MS_PER_DAY = 86_400_000;

export function groupActivityByDay(
  events: readonly ActivityEvent[],
  timezone: string,
  now: Date = new Date(),
): ActivityDayGroup[] {
  const today = receiverLocalDayKey(now.toISOString(), timezone);
  const yesterday = receiverLocalDayKey(
    new Date(now.getTime() - MS_PER_DAY).toISOString(),
    timezone,
  );

  const groups: ActivityDayGroup[] = [];
  for (const event of events) {
    const key = receiverLocalDayKey(event.at, timezone);
    const current = groups[groups.length - 1];
    if (current !== undefined && current.key === key) {
      current.events.push(event);
      continue;
    }
    groups.push({
      key,
      label: key === today ? "Today" : key === yesterday ? "Yesterday" : key,
      events: [event],
    });
  }
  return groups;
}
