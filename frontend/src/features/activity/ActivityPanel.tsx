/**
 * The activity feed's home on the Live Map (roadmap slice 035): a compact,
 * collapsible floating card answering *"what happened while I wasn't
 * watching?"* without leaving the radar picture.
 *
 * Two sources, one list. The REST first page (`GET /api/v1/activity`) supplies
 * the history that was already there when the tab opened, and the WebSocket's
 * `activity` frames (§4.4) append to it live through
 * `useActivityFeedStore` — merged and deduped by `id`, because a reconnect
 * plus a refetch can legitimately deliver the same row twice.
 *
 * The card follows the `NonPositionedPanel` idiom (collapsed by default,
 * header button carrying `aria-expanded`, count badge, scrolling body) and
 * takes the `bottom-3 right-3` corner — the last free floating slot, with
 * `ConnectionStatusChip` at `left-3 top-3`, the quick-filter chips below it,
 * the basemap/layers/filter controls down the right edge from `top-3`, and
 * the non-positioned list at `bottom-3 left-3`.
 *
 * "View all" hands off to `/activity`, which is the same feed unbounded and
 * filterable — the `RecentSightingsSection` affordance, and the reason this
 * slice adds no eighth primary nav section (SPEC §10 fixes them at seven).
 */

import { ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ActivityRow } from "@/features/activity/components/ActivityRow";
import {
  mergeActivityEvents,
  useActivityFeedStore,
} from "@/features/activity/store/useActivityFeedStore";
import { useActivityQuery } from "@/lib/api/activity";
import { useReceiverQuery } from "@/lib/api/receiver";

/** Events the panel shows. Enough to cover a glance back over the last
 * while; the standalone page is where a longer look belongs. */
const PANEL_LIMIT = 8;

export function ActivityPanel() {
  const [isExpanded, setIsExpanded] = useState(false);
  const receiverQuery = useReceiverQuery();
  // Fetched even while collapsed: the count badge is the whole reason the
  // collapsed card is worth having, and one page of eight rows every 30 s
  // (the app-wide `staleTime`) is not a cost worth a conditional for.
  const listQuery = useActivityQuery({ limit: PANEL_LIMIT, offset: 0 });
  const liveEvents = useActivityFeedStore((state) => state.events);

  const timezone = receiverQuery.data?.timezone ?? "UTC";
  const events = mergeActivityEvents(
    liveEvents,
    listQuery.data?.items ?? [],
  ).slice(0, PANEL_LIMIT);

  return (
    <div
      data-testid="activity-panel"
      className="absolute bottom-3 right-3 z-10 w-80 max-w-[80vw] overflow-hidden rounded-lg border border-border bg-card/95 shadow-md backdrop-blur-sm"
    >
      <button
        type="button"
        aria-expanded={isExpanded}
        onClick={() => setIsExpanded((expanded) => !expanded)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-xs font-medium"
      >
        <span className="flex items-center gap-1.5">
          Activity
          <span
            data-testid="activity-count"
            className="inline-flex min-w-4 items-center justify-center rounded-full bg-secondary px-1 text-[10px] font-semibold text-secondary-foreground"
          >
            {events.length}
          </span>
        </span>
        {isExpanded ? (
          <ChevronUp className="size-3.5" aria-hidden="true" />
        ) : (
          <ChevronDown className="size-3.5" aria-hidden="true" />
        )}
      </button>

      {isExpanded && (
        <div className="border-t border-border">
          {listQuery.isPending && events.length === 0 ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">Loading…</p>
          ) : listQuery.isError && events.length === 0 ? (
            // Only when there is nothing to show: a failed refetch behind rows
            // that are already on screen should not blank them out.
            <p className="px-3 py-2 text-xs text-destructive">
              Could not load activity: {listQuery.error.message}
            </p>
          ) : events.length === 0 ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">
              Nothing has happened yet.
            </p>
          ) : (
            <ul className="max-h-64 divide-y divide-border/60 overflow-y-auto">
              {events.map((event) => (
                <ActivityRow
                  key={event.id}
                  event={event}
                  timezone={timezone}
                  compact
                />
              ))}
            </ul>
          )}
          <div className="border-t border-border px-3 py-1.5">
            <Link
              to="/activity"
              className="text-[11px] text-accent hover:underline"
            >
              View all activity →
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
