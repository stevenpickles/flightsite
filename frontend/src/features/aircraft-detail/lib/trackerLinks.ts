/**
 * External tracker link construction (SPEC §24/§50, roadmap slice 016
 * scope item 6).
 *
 * Each service supports a different identifier, so "best identifier
 * available" is resolved per link rather than once globally:
 *
 * - **FlightRadar24** keys its aircraft data page off registration
 *   (`flightradar24.com/data/aircraft/{reg}`); lacking a registration, its
 *   live-flight shortcut (`flightradar24.com/{callsign}`) still works from
 *   a callsign. It has no public ICAO-hex page, so a hex-only aircraft gets
 *   no FR24 link.
 * - **FlightAware**'s `/live/flight/{ident}` accepts either a registration
 *   (N-numbers resolve directly) or a callsign/flight ident; it has no
 *   ICAO-hex lookup either.
 * - **ADS-B Exchange**'s live globe is keyed by ICAO hex
 *   (`globe.adsbexchange.com/?icao={hex}`), which every aircraft object
 *   carries (§3.3 `icao` is never null) — so this link is effectively
 *   always available.
 *
 * A link is omitted (not rendered disabled) when nothing usable exists for
 * that service, per the roadmap's "links omitted... when no usable
 * identifier exists."
 */

import type { LiveAircraft } from "@/lib/api/live";

export interface TrackerLinks {
  flightradar24: string | null;
  flightaware: string | null;
  adsbExchange: string | null;
}

function cleaned(value: string | null): string | null {
  const trimmed = value?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : null;
}

export function buildTrackerLinks(
  aircraft: Pick<LiveAircraft, "icao" | "callsign" | "registration">,
): TrackerLinks {
  const registration = cleaned(aircraft.registration);
  const callsign = cleaned(aircraft.callsign);
  const icao = cleaned(aircraft.icao);

  const flightradar24 = registration
    ? `https://www.flightradar24.com/data/aircraft/${encodeURIComponent(registration.toLowerCase())}`
    : callsign
      ? `https://www.flightradar24.com/${encodeURIComponent(callsign)}`
      : null;

  const flightaware = registration
    ? `https://www.flightaware.com/live/flight/${encodeURIComponent(registration)}`
    : callsign
      ? `https://www.flightaware.com/live/flight/${encodeURIComponent(callsign)}`
      : null;

  const adsbExchange = icao
    ? `https://globe.adsbexchange.com/?icao=${encodeURIComponent(icao.toLowerCase())}`
    : null;

  return { flightradar24, flightaware, adsbExchange };
}

/**
 * True when the FlightRadar24 / FlightAware links were built from a callsign
 * rather than from a registration.
 *
 * The distinction matters to the reader, not to the URL: a registration link
 * opens *this airframe*, while a callsign link opens *a flight* — today's
 * AFR1641, which tomorrow is a different aircraft. The UI says so in a
 * `title` rather than withholding the link, because a flight-scoped link is
 * still the best answer available for an airframe with no registration
 * (SPEC §24: "the best available identifier").
 */
export function isFlightScoped(
  aircraft: Pick<LiveAircraft, "callsign" | "registration">,
): boolean {
  return (
    cleaned(aircraft.registration) === null &&
    cleaned(aircraft.callsign) !== null
  );
}
