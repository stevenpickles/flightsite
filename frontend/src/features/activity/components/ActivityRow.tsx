/**
 * One row of the activity feed, shared by the Live Map panel and the
 * standalone page so the two can never drift into rendering an event
 * differently.
 *
 * Three parts, in the `SightingEventsTimeline` shape: a typed icon toned by
 * the event's §2.8 severity, the label and detail
 * `describeActivityEvent` derived, and the receiver-local time on the right.
 *
 * The link target is the most specific thing the event names. An aircraft
 * address wins over a sighting id — a feed row about an airframe is a row a
 * user follows to that airframe's page, and the sighting is one moment of it —
 * and a receiver-wide event (an outage, a metadata import) links nowhere,
 * because there is nowhere it would honestly go.
 */

import { Link } from "react-router-dom";

import { describeActivityEvent } from "@/features/activity/lib/describeActivityEvent";
import { ACTIVITY_ICONS, toneForSeverity } from "@/features/activity/lib/icons";
import { formatReceiverLocalTime } from "@/features/receiver/lib/format";
import type { ActivityEvent } from "@/lib/api/activity";
import { cn } from "@/lib/utils";

export interface ActivityRowProps {
  event: ActivityEvent;
  /** IANA zone from `GET /api/v1/receiver`; timestamps are receiver-local. */
  timezone: string;
  /** `true` on the Live Map panel, where the row has ~18rem to work with. */
  compact?: boolean;
}

/** The route this event points at, or `null` when it points at nothing. */
function linkTarget(event: ActivityEvent): string | null {
  if (event.icao !== null) {
    return `/aircraft/${event.icao}`;
  }
  if (event.sighting_id !== null) {
    return `/sightings/${event.sighting_id}`;
  }
  return null;
}

export function ActivityRow({ event, timezone, compact }: ActivityRowProps) {
  // An event type this build predates has no icon; the vocabulary's `Record`
  // is total, so this only fires against a backend ahead of this client, and
  // the generic milestone icon is a better answer than an empty cell.
  const Icon = ACTIVITY_ICONS[event.type] ?? ACTIVITY_ICONS.milestone;
  const { label, detail } = describeActivityEvent(event);
  const target = linkTarget(event);

  return (
    <li
      data-testid="activity-row"
      data-activity-type={event.type}
      className={cn(
        "flex items-start gap-2.5",
        compact ? "px-3 py-2 text-xs" : "px-4 py-2.5 text-sm",
      )}
    >
      <Icon
        aria-hidden="true"
        className={cn(
          "mt-0.5 shrink-0",
          compact ? "size-3.5" : "size-4",
          toneForSeverity(event.severity),
        )}
      />
      <div className="min-w-0 flex-1">
        <p className="font-medium">
          {target === null ? (
            label
          ) : (
            <Link to={target} className="text-accent hover:underline">
              {label}
            </Link>
          )}
        </p>
        {detail !== null && (
          <p
            className={cn(
              "text-muted-foreground",
              compact ? "text-[11px]" : "text-xs",
            )}
          >
            {detail}
          </p>
        )}
      </div>
      <span
        className={cn(
          "ml-auto shrink-0 whitespace-nowrap text-muted-foreground",
          compact ? "text-[11px]" : "text-xs",
        )}
      >
        {formatReceiverLocalTime(event.at, timezone)}
      </span>
    </li>
  );
}
