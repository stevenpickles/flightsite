/**
 * External tracker links (scope item 6). Each link is present only when
 * {@link buildTrackerLinks} found a usable identifier for that service —
 * omitted, not rendered disabled, per the roadmap's "links omitted... when
 * no usable identifier exists." All open in a new tab with `rel`
 * security attributes (`noopener` so the opened page can't reach back via
 * `window.opener`, `noreferrer` so it doesn't see this origin).
 */

import { ExternalLink } from "lucide-react";

import { buildTrackerLinks } from "@/features/aircraft-detail/lib/trackerLinks";
import type { LiveAircraft } from "@/lib/api/live";

export interface ExternalTrackerLinksProps {
  aircraft: Pick<LiveAircraft, "icao" | "callsign" | "registration">;
}

const SERVICES: {
  key: keyof ReturnType<typeof buildTrackerLinks>;
  label: string;
}[] = [
  { key: "flightradar24", label: "FlightRadar24" },
  { key: "flightaware", label: "FlightAware" },
  { key: "adsbExchange", label: "ADS-B Exchange" },
];

export function ExternalTrackerLinks({ aircraft }: ExternalTrackerLinksProps) {
  const links = buildTrackerLinks(aircraft);
  const available = SERVICES.filter((service) => links[service.key] !== null);

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
