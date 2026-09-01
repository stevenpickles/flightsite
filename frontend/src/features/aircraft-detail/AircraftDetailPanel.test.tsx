import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AircraftDetailPanel } from "@/features/aircraft-detail/AircraftDetailPanel";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { makeAircraft } from "@/test/liveAircraftFixtures";

beforeEach(() => {
  useLiveAircraftStore.getState().reset();
});

afterEach(() => {
  useLiveAircraftStore.getState().reset();
});

function seedSnapshot(aircraftList: ReturnType<typeof makeAircraft>[]) {
  act(() => {
    useLiveAircraftStore.getState().applySnapshot({
      aircraft: aircraftList,
      receiver: null,
    });
  });
}

describe("AircraftDetailPanel", () => {
  it("renders nothing when no aircraft is selected", () => {
    render(<AircraftDetailPanel />);
    expect(
      screen.queryByTestId("aircraft-detail-panel"),
    ).not.toBeInTheDocument();
  });

  it("opens when the store's selection changes", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([makeAircraft({ icao: "aaaaaa", callsign: "RCH471" })]);

    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    expect(screen.getByTestId("aircraft-detail-panel")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "RCH471" })).toBeInTheDocument();
  });

  it("falls back to the ICAO hex as the heading when no callsign exists", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([makeAircraft({ icao: "aaaaaa", callsign: null })]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    expect(screen.getByRole("heading", { name: "AAAAAA" })).toBeInTheDocument();
  });

  it("closes and deselects when the close button is clicked", async () => {
    const user = userEvent.setup();
    render(<AircraftDetailPanel />);
    seedSnapshot([makeAircraft({ icao: "aaaaaa" })]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });
    expect(screen.getByTestId("aircraft-detail-panel")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /close aircraft detail/i }),
    );

    expect(
      screen.queryByTestId("aircraft-detail-panel"),
    ).not.toBeInTheDocument();
    expect(useLiveAircraftStore.getState().selectedIcao).toBeNull();
  });

  it("closes and deselects on Escape", async () => {
    const user = userEvent.setup();
    render(<AircraftDetailPanel />);
    seedSnapshot([makeAircraft({ icao: "aaaaaa" })]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });
    expect(screen.getByTestId("aircraft-detail-panel")).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(
      screen.queryByTestId("aircraft-detail-panel"),
    ).not.toBeInTheDocument();
    expect(useLiveAircraftStore.getState().selectedIcao).toBeNull();
  });

  it("renders Unknown for every currently-null metadata field", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        registration: null,
        aircraft_type: null,
        model: null,
        operator: null,
        operator_group: null,
        classification: null,
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const section = screen.getByText("Identity & metadata").closest("section");
    expect(section).not.toBeNull();
    const unknowns = within(section as HTMLElement).getAllByText("Unknown");
    // registration, type, model, operator, operator group, classification
    expect(unknowns.length).toBe(6);
  });

  it("shows the enriched route with its provenance", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        route: { origin: "KATL", destination: "KSLC" },
        provenance: { route: "aerodatabox" },
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const section = screen.getByText("Route").closest("section");
    expect(section).not.toBeNull();
    expect(
      within(section as HTMLElement).getByText("KATL"),
    ).toBeInTheDocument();
    expect(
      within(section as HTMLElement).getByText("KSLC"),
    ).toBeInTheDocument();
    expect(
      within(section as HTMLElement).getAllByRole("button", {
        name: /Source: AeroDataBox\. Looked up from the AeroDataBox/i,
      }).length,
    ).toBe(2);
  });

  it("renders Unknown for a route nobody has answered for", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        route: { origin: null, destination: null },
        provenance: {},
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const section = screen.getByText("Route").closest("section");
    expect(section).not.toBeNull();
    // Origin and destination: enrichment off, ineligible callsign, no answer
    // yet and no route filed all look the same, which is the point (§2.7).
    expect(within(section as HTMLElement).getAllByText("Unknown").length).toBe(
      2,
    );
  });

  it("renders half a route as half a route, not as nothing", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        route: { origin: "EHAM", destination: null },
        provenance: { route: "aerodatabox" },
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const section = screen.getByText("Route").closest("section");
    expect(
      within(section as HTMLElement).getByText("EHAM"),
    ).toBeInTheDocument();
    expect(within(section as HTMLElement).getAllByText("Unknown").length).toBe(
      1,
    );
  });

  it("shows an emergency squawk badge for 7700 even without the emergency field set", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([
      makeAircraft({ icao: "aaaaaa", squawk: "7700", emergency: null }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const badges = screen.getAllByText(/Emergency · 7700/);
    expect(badges.length).toBeGreaterThan(0);
  });

  it("shows no emergency badge for an ordinary squawk", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([makeAircraft({ icao: "aaaaaa", squawk: "1200" })]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    expect(screen.queryByText(/Emergency/)).not.toBeInTheDocument();
  });

  it("exposes provenance information via accessible labels on the indicator buttons", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        provenance: { distance_nm: "derived" },
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    expect(
      screen.getByRole("button", {
        name: /Source: Derived\. Calculated by FlightSite/i,
      }),
    ).toBeInTheDocument();
    // Every other live field has no provenance entry -> defaults to decoder,
    // so several indicators share this label.
    expect(
      screen.getAllByRole("button", {
        name: /Source: Decoder\. Decoded directly/i,
      }).length,
    ).toBeGreaterThan(0);
  });

  it("builds external tracker links using the best available identifier", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([
      makeAircraft({
        icao: "ae1463",
        callsign: "RCH471",
        registration: "05-8153",
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("ae1463");
    });

    const fr24 = screen.getByRole("link", { name: /FlightRadar24/i });
    expect(fr24).toHaveAttribute(
      "href",
      "https://www.flightradar24.com/data/aircraft/05-8153",
    );
    expect(fr24).toHaveAttribute("target", "_blank");
    expect(fr24).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(fr24).toHaveAttribute("rel", expect.stringContaining("noreferrer"));

    const adsbx = screen.getByRole("link", { name: /ADS-B Exchange/i });
    expect(adsbx).toHaveAttribute(
      "href",
      "https://globe.adsbexchange.com/?icao=ae1463",
    );
  });

  it("still shows the ADS-B Exchange link (icao-keyed) with no reg/callsign", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([
      makeAircraft({ icao: "ae1463", callsign: null, registration: null }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("ae1463");
    });

    expect(
      screen.getByRole("link", { name: /ADS-B Exchange/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /FlightRadar24/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /FlightAware/i }),
    ).not.toBeInTheDocument();
  });

  it("live-updates displayed values as the store changes without remounting", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([makeAircraft({ icao: "aaaaaa", altitude_ft: 10000 })]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });
    expect(screen.getByText("10,000 ft")).toBeInTheDocument();

    act(() => {
      useLiveAircraftStore.getState().applyDelta({
        updated: [makeAircraft({ icao: "aaaaaa", altitude_ft: 12000 })],
        stale: [],
        removed: [],
      });
    });

    expect(screen.getByText("12,000 ft")).toBeInTheDocument();
    expect(screen.queryByText("10,000 ft")).not.toBeInTheDocument();
  });

  it("shows current-track mini stats once positions have accumulated", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([
      makeAircraft({ icao: "aaaaaa", position: { lat: 47, lon: -122 } }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });
    act(() => {
      useLiveAircraftStore.getState().applyDelta(
        {
          updated: [
            makeAircraft({
              icao: "aaaaaa",
              position: { lat: 47.1, lon: -122 },
            }),
          ],
          stale: [],
          removed: [],
        },
        Date.now() + 5000,
      );
    });

    expect(screen.getByText(/2 points/)).toBeInTheDocument();
  });

  it("applies aviation vs. metric formatting from the store's receiver info", () => {
    render(<AircraftDetailPanel />);
    act(() => {
      useLiveAircraftStore.getState().applySnapshot({
        aircraft: [makeAircraft({ icao: "aaaaaa", altitude_ft: 10000 })],
        receiver: {
          site_name: "Test",
          latitude: 0,
          longitude: 0,
          antenna_height_ft: 0,
          timezone: "UTC",
          units: "metric",
          display_radius_nm: 250,
          alert_radius_nm: null,
          demo_mode: false,
          t0: null,
        },
      });
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    expect(screen.getByText("3,048 m")).toBeInTheDocument();
  });

  it("shows a no-live-data fallback when the selection names an unknown aircraft", () => {
    render(<AircraftDetailPanel />);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("ffffff");
    });

    expect(screen.getByTestId("aircraft-detail-panel")).toBeInTheDocument();
    expect(
      screen.getByText(/No live data for this aircraft/i),
    ).toBeInTheDocument();
  });

  it("summarizes a populated classification once phase 4 fills it in", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        classification: {
          military: true,
          government: false,
          law_enforcement: false,
          mission: "military",
          icon_category: "military_transport",
          confidence: "high",
        },
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    expect(screen.getByText("Military · military")).toBeInTheDocument();
  });

  it("shows a climb glyph for a positive vertical rate", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([makeAircraft({ icao: "aaaaaa", vertical_rate_fpm: 640 })]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });
    expect(screen.getByText("+640 fpm")).toBeInTheDocument();
  });

  it("shows a descend glyph for a negative vertical rate", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([makeAircraft({ icao: "aaaaaa", vertical_rate_fpm: -640 })]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });
    expect(screen.getByText("-640 fpm")).toBeInTheDocument();
  });

  it("renders on_ground as Yes/No", () => {
    render(<AircraftDetailPanel />);
    seedSnapshot([makeAircraft({ icao: "aaaaaa", on_ground: true })]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });
});
