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

import { formatReceiverLocalTime } from "@/features/aircraft-detail/lib/format";
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
            className="flex items-start gap-3 text-sm"
          >
            <Icon
              aria-hidden="true"
              className={`mt-0.5 size-4 shrink-0 ${tone}`}
            />
            <div className="min-w-0">
              <p className="font-medium">{info.label}</p>
              {info.detail !== null && (
                <p className="text-xs text-muted-foreground">{info.detail}</p>
              )}
            </div>
            <span className="ml-auto shrink-0 whitespace-nowrap text-xs text-muted-foreground">
              {formatReceiverLocalTime(event.at, timezone)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
