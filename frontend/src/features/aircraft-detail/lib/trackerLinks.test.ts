import { describe, expect, it } from "vitest";

import { buildTrackerLinks } from "@/features/aircraft-detail/lib/trackerLinks";

describe("buildTrackerLinks", () => {
  it("prefers registration for FlightRadar24 and FlightAware", () => {
    const links = buildTrackerLinks({
      icao: "ae1463",
      callsign: "RCH471",
      registration: "N302DN",
    });
    expect(links.flightradar24).toBe(
      "https://www.flightradar24.com/data/aircraft/n302dn",
    );
    expect(links.flightaware).toBe(
      "https://www.flightaware.com/live/flight/N302DN",
    );
  });

  it("always builds the ADS-B Exchange link from ICAO hex, present or not", () => {
    const links = buildTrackerLinks({
      icao: "ae1463",
      callsign: null,
      registration: null,
    });
    expect(links.adsbExchange).toBe(
      "https://globe.adsbexchange.com/?icao=ae1463",
    );
  });

  it("falls back to callsign for FR24/FlightAware when no registration exists", () => {
    const links = buildTrackerLinks({
      icao: "ae1463",
      callsign: "RCH471",
      registration: null,
    });
    expect(links.flightradar24).toBe("https://www.flightradar24.com/RCH471");
    expect(links.flightaware).toBe(
      "https://www.flightaware.com/live/flight/RCH471",
    );
  });

  it("omits FR24/FlightAware links entirely when neither reg nor callsign exists", () => {
    const links = buildTrackerLinks({
      icao: "ae1463",
      callsign: null,
      registration: null,
    });
    expect(links.flightradar24).toBeNull();
    expect(links.flightaware).toBeNull();
  });

  it("treats blank strings the same as null", () => {
    const links = buildTrackerLinks({
      icao: "ae1463",
      callsign: "   ",
      registration: "",
    });
    expect(links.flightradar24).toBeNull();
    expect(links.flightaware).toBeNull();
  });
});
