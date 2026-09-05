import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AircraftDetailPanel } from "@/features/aircraft-detail/AircraftDetailPanel";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { makeAircraft, makeNearestAirport } from "@/test/liveAircraftFixtures";

beforeEach(() => {
  useLiveAircraftStore.getState().reset();
});

afterEach(() => {
  useLiveAircraftStore.getState().reset();
});

/** The panel's History section links to `/aircraft/:icao` (roadmap slice
 * 029), so every render needs a router context the same way the app always
 * provides one. */
function renderPanel() {
  return render(
    <MemoryRouter>
      <AircraftDetailPanel />
    </MemoryRouter>,
  );
}

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
    renderPanel();
    expect(
      screen.queryByTestId("aircraft-detail-panel"),
    ).not.toBeInTheDocument();
  });

  it("opens when the store's selection changes", () => {
    renderPanel();
    seedSnapshot([makeAircraft({ icao: "aaaaaa", callsign: "RCH471" })]);

    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    expect(screen.getByTestId("aircraft-detail-panel")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "RCH471" })).toBeInTheDocument();
  });

  it("links the History section to the full aircraft detail route", () => {
    renderPanel();
    seedSnapshot([makeAircraft({ icao: "aaaaaa" })]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const link = screen.getByRole("link", {
      name: /view lifetime records/i,
    });
    expect(link).toHaveAttribute("href", "/aircraft/aaaaaa");
  });

  it("falls back to the ICAO hex as the heading when no callsign exists", () => {
    renderPanel();
    seedSnapshot([makeAircraft({ icao: "aaaaaa", callsign: null })]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    expect(screen.getByRole("heading", { name: "AAAAAA" })).toBeInTheDocument();
  });

  it("closes and deselects when the close button is clicked", async () => {
    const user = userEvent.setup();
    renderPanel();
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
    renderPanel();
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
    renderPanel();
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
    renderPanel();
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
    renderPanel();
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

  it("names each end of the route beside its ident", () => {
    // Slice 070: an ident is only meaningful to someone who already knows
    // the airport. The name carries the meaning, the ident stays the value.
    renderPanel();
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        route: {
          origin: "KATL",
          destination: "KSLC",
          origin_name: "Hartsfield–Jackson Atlanta International",
          destination_name: "Salt Lake City International",
        },
        provenance: { route: "aerodatabox" },
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const section = screen.getByText("Route").closest("section") as HTMLElement;
    expect(within(section).getByText("KATL")).toBeInTheDocument();
    const originName = within(section).getByText(
      "Hartsfield–Jackson Atlanta International",
    );
    // The full name is the accessible text and the tooltip; only the pixels
    // are clipped, so a screen reader never reads a half-name.
    expect(originName).toHaveAttribute(
      "title",
      "Hartsfield–Jackson Atlanta International",
    );
    expect(originName).toHaveClass("truncate");
    expect(
      within(section).getByText("Salt Lake City International"),
    ).toBeInTheDocument();
  });

  it("shows the ident alone when the airport name is unknown", () => {
    renderPanel();
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        route: {
          origin: "ZZZZ",
          destination: "KSLC",
          origin_name: null,
          destination_name: "Salt Lake City International",
        },
        provenance: { route: "aerodatabox" },
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const section = screen.getByText("Route").closest("section") as HTMLElement;
    // An unresolvable ident is still the truth the provider filed — it is
    // shown, not replaced by `Unknown`.
    expect(within(section).getByText("ZZZZ")).toBeInTheDocument();
    expect(within(section).queryAllByText("Unknown")).toHaveLength(0);
  });

  it("renders a name-less payload from an older backend unchanged", () => {
    // The name keys are absent, not null: a frontend ahead of its backend
    // must degrade to exactly the pre-070 row rather than render "undefined".
    renderPanel();
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        route: { origin: "EGLL", destination: "KJFK" },
        provenance: { route: "aerodatabox" },
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const section = screen.getByText("Route").closest("section") as HTMLElement;
    expect(within(section).getByText("EGLL")).toBeInTheDocument();
    expect(within(section).getByText("KJFK")).toBeInTheDocument();
    expect(section.textContent).not.toContain("undefined");
  });

  it("keeps Unknown for a null ident even when a name would fit beside it", () => {
    renderPanel();
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        route: {
          origin: null,
          destination: "KSLC",
          origin_name: null,
          destination_name: "Salt Lake City International",
        },
        provenance: { route: "aerodatabox" },
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const section = screen.getByText("Route").closest("section") as HTMLElement;
    expect(within(section).getAllByText("Unknown")).toHaveLength(1);
    expect(
      within(section).getByText("Salt Lake City International"),
    ).toBeInTheDocument();
  });

  it("renders half a route as half a route, not as nothing", () => {
    renderPanel();
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

  it("stands a departure field in for an unreported origin", () => {
    // SPEC §28 as amended for slice 071: where no source knows the callsign,
    // the airport context may say where the aircraft left from — provided it
    // says so as an inference and not as a filed route.
    renderPanel();
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        route: { origin: null, destination: null },
        nearest_airport: makeNearestAirport({
          ident: "KPAE",
          name: "Paine Field",
          phase: "departing",
        }),
        provenance: { nearest_airport: "heuristic" },
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const section = screen.getByText("Route").closest("section") as HTMLElement;
    expect(within(section).getByText("KPAE")).toBeInTheDocument();
    expect(within(section).getByText("Paine Field")).toBeInTheDocument();
    expect(within(section).getByText("inferred")).toBeInTheDocument();
    // Destination is untouched: a departure says nothing about where the
    // aircraft is going, so that end stays honestly Unknown.
    expect(within(section).getAllByText("Unknown")).toHaveLength(1);
    // Attributed to the heuristic that produced it, never to a route source.
    expect(
      within(section).getByRole("button", {
        name: /Source: Heuristic\./i,
      }),
    ).toBeInTheDocument();
  });

  it("stands an arrival field in for an unreported destination", () => {
    renderPanel();
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        route: { origin: null, destination: null },
        nearest_airport: makeNearestAirport({ phase: "arriving" }),
        provenance: { nearest_airport: "heuristic" },
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const section = screen.getByText("Route").closest("section") as HTMLElement;
    expect(within(section).getByText("KBFI")).toBeInTheDocument();
    expect(within(section).getByText("inferred")).toBeInTheDocument();
    expect(within(section).getAllByText("Unknown")).toHaveLength(1);
  });

  it("labels the inferred end in text, not by styling alone", () => {
    // SPEC §80 forbids colour-only signalling, and a muted ident on its own
    // is exactly that. The tag is real text inside the row, and the sentence
    // explaining it is on the element rather than only in a hover popup.
    renderPanel();
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        route: { origin: null, destination: null },
        nearest_airport: makeNearestAirport({ phase: "departing" }),
        provenance: { nearest_airport: "heuristic" },
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const section = screen.getByText("Route").closest("section") as HTMLElement;
    const originRow = within(section).getByText("Origin")
      .parentElement as HTMLElement;
    expect(originRow.textContent).toContain("inferred");

    const tag = within(section).getByText("inferred");
    expect(tag).toHaveAttribute(
      "title",
      "Inferred from the aircraft's departure at this field; not a reported route.",
    );
  });

  it("lets a reported ident win over an inference for the same end", () => {
    // Inference fills a hole; it never overwrites an answer. A directory or
    // provider route is what somebody filed, and that outranks a guess even
    // when the guess is about the very same end.
    renderPanel();
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        route: { origin: "KATL", destination: null },
        nearest_airport: makeNearestAirport({
          ident: "KPAE",
          name: "Paine Field",
          phase: "departing",
        }),
        provenance: { route: "vrs", nearest_airport: "heuristic" },
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const section = screen.getByText("Route").closest("section") as HTMLElement;
    expect(within(section).getByText("KATL")).toBeInTheDocument();
    expect(within(section).queryByText("KPAE")).not.toBeInTheDocument();
    expect(within(section).queryByText("inferred")).not.toBeInTheDocument();
    expect(
      within(section).getByRole("button", {
        name: /Source: VRS standing data\./i,
      }),
    ).toBeInTheDocument();
  });

  it("infers nothing from an airport the aircraft is merely near", () => {
    // `phase: null` is the common case — cruise, or on the ground — and it
    // is not evidence of anything. The rows stay exactly as they were.
    renderPanel();
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        route: { origin: null, destination: null },
        nearest_airport: makeNearestAirport({ phase: null }),
        provenance: { nearest_airport: "heuristic" },
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const section = screen.getByText("Route").closest("section") as HTMLElement;
    expect(within(section).getAllByText("Unknown")).toHaveLength(2);
    expect(within(section).queryByText("KBFI")).not.toBeInTheDocument();
  });

  it("infers nothing when the payload carries no airport context at all", () => {
    renderPanel();
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        route: { origin: null, destination: null },
        nearest_airport: null,
        provenance: {},
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const section = screen.getByText("Route").closest("section") as HTMLElement;
    expect(within(section).getAllByText("Unknown")).toHaveLength(2);
    expect(within(section).queryByText("inferred")).not.toBeInTheDocument();
  });

  it("labels a route the offline directory answered for", () => {
    // Slice 071: `provenance.route` is now `vrs` or `aerodatabox`, and the
    // panel must name which — the offline directory and the online provider
    // are different claims about the same field.
    renderPanel();
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        route: { origin: "EGLL", destination: "KJFK" },
        provenance: { route: "vrs" },
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const section = screen.getByText("Route").closest("section") as HTMLElement;
    expect(
      within(section).getAllByRole("button", {
        name: /Source: VRS standing data\. Matched against the Virtual Radar Server/i,
      }),
    ).toHaveLength(2);
  });

  it("keeps the inferred airport in its own section, apart from the route", () => {
    // The slice's acceptance criterion: inference and external route data are
    // visually and semantically distinct (SPEC §41). Two sections, and neither
    // one's values appear in the other.
    renderPanel();
    seedSnapshot([
      makeAircraft({
        icao: "aaaaaa",
        route: { origin: "KATL", destination: "KSLC" },
        nearest_airport: {
          ident: "KBFI",
          name: "Boeing Field",
          distance_nm: 3.4,
          phase: "arriving",
        },
        provenance: { route: "aerodatabox", nearest_airport: "heuristic" },
      }),
    ]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const route = screen.getByText("Route").closest("section") as HTMLElement;
    const airport = screen
      .getByText("Nearest airport")
      .closest("section") as HTMLElement;
    expect(route).not.toBe(airport);

    expect(within(route).getByText("KATL")).toBeInTheDocument();
    expect(within(route).queryByText(/KBFI/)).not.toBeInTheDocument();
    expect(within(route).queryByText(/inferred/i)).not.toBeInTheDocument();

    expect(
      within(airport).getByText("KBFI — Boeing Field"),
    ).toBeInTheDocument();
    expect(
      within(airport).getByText("Likely arriving · inferred"),
    ).toBeInTheDocument();
    expect(within(airport).queryByText("KATL")).not.toBeInTheDocument();
  });

  it("renders the nearest-airport section as Unknown when nothing is known", () => {
    renderPanel();
    seedSnapshot([makeAircraft({ icao: "aaaaaa", nearest_airport: null })]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const airport = screen
      .getByText("Nearest airport")
      .closest("section") as HTMLElement;
    expect(within(airport).getAllByText("Unknown").length).toBe(3);
  });

  it("shows an emergency squawk badge for 7700 even without the emergency field set", () => {
    renderPanel();
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
    renderPanel();
    seedSnapshot([makeAircraft({ icao: "aaaaaa", squawk: "1200" })]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    expect(screen.queryByText(/Emergency/)).not.toBeInTheDocument();
  });

  it("exposes provenance information via accessible labels on the indicator buttons", () => {
    renderPanel();
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
    renderPanel();
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
    renderPanel();
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
    renderPanel();
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
    renderPanel();
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
    renderPanel();
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
    renderPanel();
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("ffffff");
    });

    expect(screen.getByTestId("aircraft-detail-panel")).toBeInTheDocument();
    expect(
      screen.getByText(/No live data for this aircraft/i),
    ).toBeInTheDocument();
  });

  it("summarizes a populated classification once phase 4 fills it in", () => {
    renderPanel();
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

    expect(screen.getByText("Military · Military")).toBeInTheDocument();
  });

  it("shows a climb glyph for a positive vertical rate", () => {
    renderPanel();
    seedSnapshot([makeAircraft({ icao: "aaaaaa", vertical_rate_fpm: 640 })]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });
    expect(screen.getByText("+640 fpm")).toBeInTheDocument();
  });

  it("shows a descend glyph for a negative vertical rate", () => {
    renderPanel();
    seedSnapshot([makeAircraft({ icao: "aaaaaa", vertical_rate_fpm: -640 })]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });
    expect(screen.getByText("-640 fpm")).toBeInTheDocument();
  });

  it("renders on_ground as Yes/No", () => {
    renderPanel();
    seedSnapshot([makeAircraft({ icao: "aaaaaa", on_ground: true })]);
    act(() => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });
});
