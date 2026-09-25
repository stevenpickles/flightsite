/**
 * External tracker links (scope item 6). Each link is present only when
 * {@link buildTrackerLinks} found a usable identifier for that service —
 * omitted, not rendered disabled, per the roadmap's "links omitted... when
 * no usable identifier exists." All open in a new tab with `rel`
 * security attributes (`noopener` so the opened page can't reach back via
 * `window.opener`, `noreferrer` so it doesn't see this origin).
 */

import { ExternalLink } from "lucide-react";

import {
  buildTrackerLinks,
  isFlightScoped,
} from "@/features/aircraft-detail/lib/trackerLinks";
import type { LiveAircraft } from "@/lib/api/live";

export interface ExternalTrackerLinksProps {
  aircraft: Pick<LiveAircraft, "icao" | "callsign" | "registration">;
}

const SERVICES: {
  key: keyof ReturnType<typeof buildTrackerLinks>;
  label: string;
  /** Whether this service's link can be keyed off a callsign, and so may be
   * flight-scoped rather than airframe-scoped. */
  callsignKeyed: boolean;
}[] = [
  { key: "flightradar24", label: "FlightRadar24", callsignKeyed: true },
  { key: "flightaware", label: "FlightAware", callsignKeyed: true },
  { key: "adsbExchange", label: "ADS-B Exchange", callsignKeyed: false },
];

export function ExternalTrackerLinks({ aircraft }: ExternalTrackerLinksProps) {
  const links = buildTrackerLinks(aircraft);
  const available = SERVICES.filter((service) => links[service.key] !== null);
  // Said once, in a title: a callsign link opens today's flight, not this
  // airframe (review R2-11).
  const flightScoped = isFlightScoped(aircraft);

  if (available.length === 0) {
    return (
      <p className="py-1 text-sm italic text-muted-foreground">
        No external identifier available yet.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-1.5 py-1">
      {available.map((service) => (
        <li key={service.key}>
          <a
            href={links[service.key] ?? undefined}
            target="_blank"
            rel="noopener noreferrer"
            title={
              flightScoped && service.callsignKeyed
                ? `Opens flight ${aircraft.callsign?.trim()} — the flight this callsign is flying now, not this airframe.`
                : undefined
            }
            className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline"
          >
            {service.label}
            <ExternalLink className="size-3.5" aria-hidden="true" />
          </a>
        </li>
      ))}
    </ul>
  );
}
