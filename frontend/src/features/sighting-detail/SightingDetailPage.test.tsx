import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  aircraftDetail,
  installSightingsApiMock,
  sightingDetail,
} from "@/test/sightingsApiMock";
import { getLastMockMap, resetMapLibreMock } from "@/test/maplibreGlMock";
import { renderApp } from "@/test/test-utils";

beforeEach(() => {
  resetMapLibreMock();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SightingDetailPage", () => {
  it("shows a loading state before the sighting resolves", () => {
    let resolveDetail!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () => new Promise<Response>((resolve) => (resolveDetail = resolve)),
      ),
    );

    renderApp("/sightings/88213");

    expect(screen.getByText(/loading sighting/i)).toBeInTheDocument();
    resolveDetail(new Response("{}", { status: 200 }));
  });

  it("shows a not-found message for an id with no sighting", async () => {
    installSightingsApiMock({ detail: {} });

    renderApp("/sightings/999999");

    expect(await screen.findByText(/sighting not found/i)).toBeInTheDocument();
    expect(
      screen.getByText(/no sighting exists with id 999999/i),
    ).toBeInTheDocument();
  });

  it("rejects a malformed id without ever requesting its detail", () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.reject(new Error("unexpected fetch")),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderApp("/sightings/not-a-number");

    expect(screen.getByText(/sighting not found/i)).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).startsWith("/api/v1/sightings/"),
      ),
    ).toBe(false);
  });

  it("renders the summary header: identity, times, duration, closure", async () => {
    installSightingsApiMock({
      detail: { 88213: sightingDetail({ id: 88213 }) },
      aircraft: {
        ae1463: aircraftDetail({ icao: "ae1463", registration: "N302DN" }),
      },
    });

    renderApp("/sightings/88213");

    expect(await screen.findByText("N302DN")).toBeInTheDocument();
    expect(screen.getByText(/icao ae1463/i)).toBeInTheDocument();
    expect(screen.getByText(/callsign rch492/i)).toBeInTheDocument();
    // Duration: 2385s -> "39m 45s".
    expect(screen.getByText("39m 45s")).toBeInTheDocument();
    expect(screen.getByText("Timed out")).toBeInTheDocument();
  });

  it("links the header identity to the aircraft detail route", async () => {
    installSightingsApiMock({
      detail: { 88213: sightingDetail({ id: 88213 }) },
      aircraft: {
        ae1463: aircraftDetail({ icao: "ae1463", registration: "N302DN" }),
      },
    });

    renderApp("/sightings/88213");

    const link = await screen.findByRole("link", { name: "N302DN" });
    expect(link).toHaveAttribute("href", "/aircraft/ae1463");
  });

  it("shows 'Ongoing' instead of an end time and duration for an open sighting", async () => {
    installSightingsApiMock({
      detail: {
        88213: sightingDetail({
          id: 88213,
          ended_at: null,
          duration_s: null,
          closure_reason: null,
        }),
      },
    });

    renderApp("/sightings/88213");

    await screen.findByText(/icao ae1463/i);
    expect(screen.getAllByText("Ongoing")).not.toHaveLength(0);
  });

  it("renders the event timeline with plain-language labels", async () => {
    installSightingsApiMock({
      detail: {
        88213: sightingDetail({
          id: 88213,
          events: [
            {
              at: "2026-08-30T22:10:00.000Z",
              type: "squawk_change",
              detail: { from: "2000", to: "4521" },
            },
            {
              at: "2026-08-30T22:15:00.000Z",
              type: "emergency_start",
              detail: { squawk: "7700" },
            },
          ],
        }),
      },
    });

    renderApp("/sightings/88213");

    expect(await screen.findByText("Squawk changed")).toBeInTheDocument();
    expect(screen.getByText("2000 → 4521")).toBeInTheDocument();
    expect(screen.getByText("Emergency declared")).toBeInTheDocument();
    expect(screen.getByText("Squawk 7700")).toBeInTheDocument();
    expect(screen.queryByText("Callsign changed")).not.toBeInTheDocument();
  });

  it("shows a placeholder when a sighting has no events", async () => {
    installSightingsApiMock({
      detail: { 88213: sightingDetail({ id: 88213, events: [] }) },
    });

    renderApp("/sightings/88213");

    expect(
      await screen.findByText(/no notable events during this sighting/i),
    ).toBeInTheDocument();
  });

  it("renders reception stats and records", async () => {
    installSightingsApiMock({
      detail: { 88213: sightingDetail({ id: 88213 }) },
    });

    renderApp("/sightings/88213");

    await screen.findByText(/icao ae1463/i);
    expect(screen.getByText("48,210")).toBeInTheDocument(); // message_count
    expect(screen.getByText("92.4%")).toBeInTheDocument(); // pct_with_position
    expect(screen.getByText(/11\.2\s*nm/)).toBeInTheDocument(); // closest approach
  });

  it("renders the route block when a route is known", async () => {
    installSightingsApiMock({
      detail: {
        88213: sightingDetail({
          id: 88213,
          route: { origin: "KTCM", destination: "PHIK" },
        }),
      },
    });

    renderApp("/sightings/88213");

    expect(await screen.findByText("KTCM")).toBeInTheDocument();
    expect(screen.getByText("PHIK")).toBeInTheDocument();
  });

  it("omits the route section entirely when there is no route", async () => {
    installSightingsApiMock({
      detail: {
        88213: sightingDetail({
          id: 88213,
          route: { origin: null, destination: null },
        }),
      },
    });

    renderApp("/sightings/88213");

    await screen.findByText(/icao ae1463/i);
    expect(screen.queryByText("Route")).not.toBeInTheDocument();
  });

  it("renders the path on the map and fits the camera to it", async () => {
    installSightingsApiMock({
      detail: { 88213: sightingDetail({ id: 88213 }) },
    });

    renderApp("/sightings/88213");

    await screen.findByText(/icao ae1463/i);
    const map = getLastMockMap();
    await act(async () => {
      map.emit("load");
    });

    await waitFor(() => {
      expect(map.fitBounds).toHaveBeenCalledTimes(1);
    });
  });

  it("shows a no-path message instead of a map for a sighting with an empty path", async () => {
    installSightingsApiMock({
      detail: { 88213: sightingDetail({ id: 88213, path: [] }) },
    });

    renderApp("/sightings/88213");

    expect(
      await screen.findByText(/no path was recorded for this sighting/i),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("maplibre-container")).not.toBeInTheDocument();
  });
});
