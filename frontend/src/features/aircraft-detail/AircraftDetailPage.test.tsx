import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { aircraftDetail, installAircraftApiMock } from "@/test/aircraftApiMock";
import { sightingRow } from "@/test/sightingsApiMock";
import { renderApp } from "@/test/test-utils";

beforeEach(() => {
  useLiveAircraftStore.getState().reset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  useLiveAircraftStore.getState().reset();
});

describe("AircraftDetailPage", () => {
  it("shows a loading state before the detail resolves", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );

    renderApp("/aircraft/ae1463");

    expect(screen.getByText(/loading aircraft/i)).toBeInTheDocument();
  });

  it("renders identity, metadata, classification and lifetime records for a non-live aircraft", async () => {
    installAircraftApiMock({
      detail: {
        ae1463: aircraftDetail({
          icao: "ae1463",
          registration: "N302DN",
          aircraft_type: "B738",
          operator: "Delta Air Lines",
          manufacture_year: 2018,
          owner: "Some Owner LLC",
          classification: {
            military: false,
            government: false,
            law_enforcement: false,
            mission: "commercial_passenger",
            icon_category: null,
            confidence: "high",
          },
          live: false,
          lifetime: {
            first_seen: "2026-04-02T18:11:09.000Z",
            last_seen: "2026-08-30T22:41:55.000Z",
            sighting_count: 41,
            cumulative_duration_s: 51_840,
            open_sighting_elapsed_s: null,
            closest_approach_nm: 2.1,
            max_range_nm: 141.8,
            lowest_altitude_ft: 1250,
            highest_altitude_ft: 41_000,
          },
        }),
      },
    });

    renderApp("/aircraft/ae1463");

    expect(
      await screen.findByRole("heading", { name: "N302DN" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/ICAO AE1463/)).toBeInTheDocument();
    expect(screen.getByText("B738")).toBeInTheDocument();
    // Both "Operator" and "Operator group" show the same string here.
    expect(screen.getAllByText("Delta Air Lines")).toHaveLength(2);
    expect(screen.getByText("2018")).toBeInTheDocument();
    // SPEC §23's second item, derived from the first (review R2-10).
    expect(screen.getByText(/^\d+ years \(built 2018\)$/)).toBeInTheDocument();
    expect(screen.getByText("Some Owner LLC")).toBeInTheDocument();
    // Mission renders through MISSION_LABELS, never the raw slug.
    expect(
      screen.getByText("Civilian · Commercial passenger"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/commercial_passenger/)).not.toBeInTheDocument();
    // Lifetime records, unit-aware (aviation default: nm/ft).
    expect(screen.getByText("41")).toBeInTheDocument();
    expect(screen.getByText("2.1 nm")).toBeInTheDocument();
    expect(screen.getByText("141.8 nm")).toBeInTheDocument();
    expect(screen.getByText("1,250 ft")).toBeInTheDocument();
    // No live section for a non-live aircraft.
    expect(
      screen.queryByRole("button", { name: /live now/i }),
    ).not.toBeInTheDocument();
  });

  it("builds tracker links from the airframe's last callsign when it has no registration (R2-11)", async () => {
    installAircraftApiMock({
      detail: {
        b034be: aircraftDetail({ icao: "b034be", registration: null }),
      },
      aircraftSightings: {
        b034be: {
          items: [
            sightingRow({ id: 2, icao: "b034be", callsign: "AFR1641" }),
            sightingRow({ id: 1, icao: "b034be", callsign: "AFR990" }),
          ],
          total: null,
          limit: 5,
          offset: 0,
        },
      },
    });

    renderApp("/aircraft/b034be");

    // All three of SPEC §24's services, not the one ADS-B Exchange link a
    // hard-coded `callsign: null` left behind.
    const fr24 = await screen.findByRole("link", { name: /flightradar24/i });
    expect(fr24).toHaveAttribute(
      "href",
      "https://www.flightradar24.com/AFR1641",
    );
    expect(
      screen.getByRole("link", { name: /flightaware/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /ads-b exchange/i }),
    ).toBeInTheDocument();
    // And it says what a callsign link actually opens.
    expect(fr24.getAttribute("title")).toMatch(/not this airframe/i);
  });

  it("counts a sighting still in progress in the cumulative time, and says so (R2-02)", async () => {
    installAircraftApiMock({
      detail: {
        ae1463: aircraftDetail({
          icao: "ae1463",
          lifetime: {
            first_seen: "2026-09-21T01:33:24.000Z",
            last_seen: "2026-09-21T01:49:30.000Z",
            sighting_count: 1,
            // The review's case: overhead since T0 and reported as `0s`,
            // because the total summed closed sightings only.
            cumulative_duration_s: 964,
            open_sighting_elapsed_s: 964,
            closest_approach_nm: null,
            max_range_nm: null,
            lowest_altitude_ft: null,
            highest_altitude_ft: null,
          },
        }),
      },
    });

    renderApp("/aircraft/ae1463");

    await screen.findByText(/ICAO AE1463/);
    const row = screen.getByText("Cumulative observed time").closest("div");
    expect(row).toHaveTextContent("16m 4s");
    expect(row).toHaveTextContent("still running");
  });

  it("puts its sections at H2, under the page's H1 (R2-17)", async () => {
    installAircraftApiMock({
      detail: { ae1463: aircraftDetail({ icao: "ae1463" }) },
    });

    renderApp("/aircraft/ae1463");

    await screen.findByText(/ICAO AE1463/);
    // The review audited this route as H1 → H3 with no H2 anywhere.
    const headings = screen
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent);
    expect(headings).toContain("Identity & metadata");
    expect(headings).toContain("Manufacture & ownership");
  });

  it("shows a not-found message for a valid-format icao this receiver never sighted", async () => {
    installAircraftApiMock({ detail: {} });

    renderApp("/aircraft/ffffff");

    expect(
      await screen.findByRole("heading", { name: /aircraft not found/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/never sighted FFFFFF/i)).toBeInTheDocument();
  });

  it("shows a generic error message for a non-404 failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith("/api/v1/receiver")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({ units: "aviation", timezone: "UTC" }),
              {
                status: 200,
              },
            ),
          );
        }
        return Promise.resolve(new Response("", { status: 500 }));
      }),
    );

    renderApp("/aircraft/ae1463");

    expect(
      await screen.findByRole("heading", {
        name: /could not load this aircraft/i,
      }),
    ).toBeInTheDocument();
  });

  it("shows Unknown for an aircraft with no registration", async () => {
    installAircraftApiMock({
      detail: {
        ae1463: aircraftDetail({ icao: "ae1463", registration: null }),
      },
    });

    renderApp("/aircraft/ae1463");

    expect(
      await screen.findByRole("heading", { name: "AE1463" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Unknown").length).toBeGreaterThan(0);
  });

  it("rejects a malformed icao without making a detail request", async () => {
    const { fetchMock } = installAircraftApiMock({ detail: {} });

    renderApp("/aircraft/not-an-icao");

    expect(
      await screen.findByRole("heading", { name: /aircraft not found/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/is not a valid ICAO 24-bit address/i),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes("/api/v1/aircraft/not-an-icao"),
      ),
    ).toBe(false);
  });

  it("offers a jump to the Live Map for a currently-live aircraft, and selects it there", async () => {
    installAircraftApiMock({
      detail: { ae1463: aircraftDetail({ icao: "ae1463", live: true }) },
    });
    const user = userEvent.setup();
    const { router } = renderApp("/aircraft/ae1463");

    const jumpButton = await screen.findByRole("button", {
      name: /live now/i,
    });
    await user.click(jumpButton);

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    expect(useLiveAircraftStore.getState().selectedIcao).toBe("ae1463");
  });
});
