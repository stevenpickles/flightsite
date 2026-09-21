/**
 * The sighting detail view's event timeline (SPEC §52): typed icons and
 * plain-language labels for callsign/squawk changes, emergencies, and the
 * enrichment/classification/alert events later slices populate.
 */

import {
  AlertTriangle,
  Bell,
  BellRing,
  CheckCircle2,
  type LucideIcon,
  Radio,
  Route,
  ShieldCheck,
  Tag,
} from "lucide-react";

import {
  formatReceiverLocalTime,
  formatReceiverLocalTitle,
} from "@/features/aircraft-detail/lib/format";
import { describeSightingEvent } from "@/features/sighting-detail/lib/eventDescriptions";
import type { SightingEvent, SightingEventType } from "@/lib/api/sightings";

const ICONS: Record<SightingEventType, LucideIcon> = {
  callsign_change: Tag,
  squawk_change: Radio,
  emergency_start: AlertTriangle,
  emergency_end: CheckCircle2,
  route_enriched: Route,
  classification_available: ShieldCheck,
  alert_matched: Bell,
  alert_severity_upgraded: BellRing,
};

const EMERGENCY_TONE: Partial<Record<SightingEventType, string>> = {
  emergency_start: "text-destructive",
  alert_matched: "text-warning",
  alert_severity_upgraded: "text-destructive",
};

export interface SightingEventsTimelineProps {
  events: SightingEvent[];
  timezone: string;
}

export function SightingEventsTimeline({
  events,
  timezone,
}: SightingEventsTimelineProps) {
  if (events.length === 0) {
    return (
      <p className="px-4 py-3 text-sm text-muted-foreground">
        No notable events during this sighting.
      </p>
    );
  }

  return (
    <ol className="flex flex-col gap-3 px-4 py-3">
      {events.map((event, index) => {
        const Icon = ICONS[event.type];
        const info = describeSightingEvent(event);
        const tone = EMERGENCY_TONE[event.type] ?? "text-muted-foreground";
        return (
          <li
            key={`${event.at}-${index}`}
            // Wrapping, so a long label and the timestamp share the row when
            // there is width for it and stack when there is not. At 390px
            // the fixed row printed "Alert matched" on top of its own
            // 21:34:36 (review R2-08).
            className="flex flex-wrap items-start gap-x-3 gap-y-0.5 text-sm"
          >
            <Icon
              aria-hidden="true"
              className={`mt-0.5 size-4 shrink-0 ${tone}`}
            />
            <div className="min-w-0 flex-1">
              <p className="font-medium">{info.label}</p>
              {info.detail !== null && (
                <p className="text-xs text-muted-foreground">{info.detail}</p>
              )}
            </div>
            {/* A sighting can straddle midnight, so the time of day alone is
             * not an instant; the `title` carries the receiver-local
             * datetime and the UTC instant behind it (review R2-06). */}
            <time
              dateTime={event.at}
              title={formatReceiverLocalTitle(event.at, timezone)}
              className="ml-auto shrink-0 whitespace-nowrap text-xs text-muted-foreground"
            >
              {formatReceiverLocalTime(event.at, timezone)}
            </time>
          </li>
        );
      })}
    </ol>
  );
}
