import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { aircraftDetail, installAircraftApiMock } from "@/test/aircraftApiMock";
import { sightingRow } from "@/test/sightingsApiMock";
import { renderApp } from "@/test/test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RecentSightingsSection (via AircraftDetailPage)", () => {
  it("shows a 'no sightings yet' message when the aircraft has none", async () => {
    installAircraftApiMock({
      detail: { ae1463: aircraftDetail({ icao: "ae1463" }) },
    });

    renderApp("/aircraft/ae1463");

    expect(
      await screen.findByText(/no sightings recorded yet/i),
    ).toBeInTheDocument();
  });

  it("lists recent sightings and links each into its detail route", async () => {
    installAircraftApiMock({
      detail: { ae1463: aircraftDetail({ icao: "ae1463" }) },
      aircraftSightings: {
        ae1463: {
          items: [
            sightingRow({ id: 88213, started_at: "2026-08-30T22:02:10.000Z" }),
          ],
          total: null,
          limit: 5,
          offset: 0,
        },
      },
    });
    const user = userEvent.setup();
    const { router } = renderApp("/aircraft/ae1463");

    const link = await screen.findByRole("link", { name: /2026-08-30/ });
    await user.click(link);

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/sightings/88213");
    });
  });

  it("shows 'Ongoing' for an open sighting in the recent list", async () => {
    installAircraftApiMock({
      detail: { ae1463: aircraftDetail({ icao: "ae1463" }) },
      aircraftSightings: {
        ae1463: {
          items: [sightingRow({ id: 1, ended_at: null, duration_s: null })],
          total: null,
          limit: 5,
          offset: 0,
        },
      },
    });

    renderApp("/aircraft/ae1463");

    expect(await screen.findByText("Ongoing")).toBeInTheDocument();
  });

  it("links 'View all' to the Sightings page pre-filtered to this aircraft", async () => {
    installAircraftApiMock({
      detail: { ae1463: aircraftDetail({ icao: "ae1463" }) },
      aircraftSightings: {
        ae1463: {
          items: [sightingRow({ id: 1 })],
          total: null,
          limit: 5,
          offset: 0,
        },
      },
    });

    renderApp("/aircraft/ae1463");

    const viewAll = await screen.findByRole("link", {
      name: /view all sightings/i,
    });
    expect(viewAll).toHaveAttribute("href", "/sightings?icao=ae1463");
  });
});
