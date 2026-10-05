/**
 * The Sightings page's window and groupings (slice 098): the Analytics
 * presets with today as the default, a live summary line, and the same
 * window listed three ways — the log, the distinct aircraft, the distinct
 * types. `SightingsPage.test.tsx` covers the log itself.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  installSightingsApiMock,
  seenAircraftRow,
  seenTypeRow,
  sightingRow,
} from "@/test/sightingsApiMock";
import { renderApp } from "@/test/test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

type FetchMock = ReturnType<typeof installSightingsApiMock>["fetchMock"];

/** Every request the page made to `path`, as parsed URLs, oldest first. */
function requestsTo(fetchMock: FetchMock, path: string): URL[] {
  return (fetchMock.mock.calls as [RequestInfo | URL][])
    .map(([input]) => new URL(String(input), "http://localhost"))
    .filter((url) => url.pathname === path);
}

function lastRequestTo(fetchMock: FetchMock, path: string): URL {
  const last = requestsTo(fetchMock, path).at(-1);
  if (last === undefined) {
    throw new Error(`no request was made to ${path}`);
  }
  return last;
}

const COUNTS = {
  sightings: 142,
  unique_aircraft: 97,
  unique_types: 31,
  new_aircraft: 12,
};

describe("the Sightings page window", () => {
  it("opens on today's log, resolved by the server", async () => {
    const { fetchMock } = installSightingsApiMock({
      list: { items: [sightingRow()], total: null, limit: 50, offset: 0 },
    });

    const { router } = renderApp("/sightings");

    await screen.findAllByTestId("sighting-row");
    expect(screen.getByRole("radio", { name: "Today" })).toBeChecked();
    const request = lastRequestTo(fetchMock, "/api/v1/sightings");
    expect(request.searchParams.get("preset")).toBe("today");
    // The window is the server's to resolve in receiver-local time: the
    // browser sends no bounds of its own.
    expect(request.searchParams.has("from")).toBe(false);
    expect(request.searchParams.has("to")).toBe(false);
    expect(router.state.location.search).toBe("");
  });

  it("switches window with the Analytics presets and keeps it in the URL", async () => {
    const user = userEvent.setup();
    const { fetchMock } = installSightingsApiMock({
      list: { items: [sightingRow()], total: null, limit: 50, offset: 0 },
    });
    const { router } = renderApp("/sightings");
    await screen.findAllByTestId("sighting-row");

    await user.click(screen.getByRole("radio", { name: "Since T0" }));

    await waitFor(() => {
      expect(router.state.location.search).toBe("?preset=t0");
    });
    await waitFor(() => {
      expect(
        lastRequestTo(fetchMock, "/api/v1/sightings").searchParams.get(
          "preset",
        ),
      ).toBe("t0");
    });
    expect(
      lastRequestTo(fetchMock, "/api/v1/analytics/counts").searchParams.get(
        "preset",
      ),
    ).toBe("t0");
  });

  it("returns to page 1 when the window changes", async () => {
    const user = userEvent.setup();
    installSightingsApiMock({
      list: { items: [sightingRow()], total: null, limit: 50, offset: 0 },
    });
    const { router } = renderApp("/sightings?page=3");
    await screen.findAllByTestId("sighting-row");

    await user.click(screen.getByRole("radio", { name: "7 days" }));

    await waitFor(() => {
      expect(router.state.location.search).toBe("?preset=7d");
    });
  });

  it("shows all of an aircraft's sightings for an exact-aircraft link", async () => {
    // The aircraft detail page's "all sightings" link carries no preset.
    const { fetchMock } = installSightingsApiMock({
      list: { items: [sightingRow()], total: null, limit: 50, offset: 0 },
    });

    renderApp("/sightings?icao=ae1463");

    await screen.findAllByTestId("sighting-row");
    expect(screen.getByRole("radio", { name: "Since T0" })).toBeChecked();
    expect(
      lastRequestTo(fetchMock, "/api/v1/sightings").searchParams.get("preset"),
    ).toBe("t0");
  });

  it("no longer offers the raw date inputs", async () => {
    installSightingsApiMock();
    renderApp("/sightings");
    await screen.findByText(/no sightings match this window/i);

    expect(screen.queryByLabelText("From")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("To")).not.toBeInTheDocument();
  });
});

describe("the summary line", () => {
  it("states what the window held", async () => {
    installSightingsApiMock({ counts: COUNTS });
    renderApp("/sightings");

    const summary = await screen.findByRole("group", {
      name: "In this window",
    });
    await waitFor(() => {
      expect(summary).toHaveTextContent(
        /142 sightings\s*·\s*97 aircraft\s*·\s*31 types\s*·\s*12 never seen before/,
      );
    });
  });

  it("uses the singular for one of something", async () => {
    installSightingsApiMock({
      counts: {
        sightings: 1,
        unique_aircraft: 1,
        unique_types: 1,
        new_aircraft: 0,
      },
    });
    renderApp("/sightings");

    const summary = await screen.findByRole("group", {
      name: "In this window",
    });
    await waitFor(() => {
      expect(summary).toHaveTextContent(
        /1 sighting\s*·\s*1 aircraft\s*·\s*1 type\s*·\s*0 never seen before/,
      );
    });
  });

  it("leaves out never-seen-before over the whole history", async () => {
    installSightingsApiMock({ counts: COUNTS });
    renderApp("/sightings?preset=t0");

    const summary = await screen.findByRole("group", {
      name: "In this window",
    });
    await waitFor(() => {
      expect(summary).toHaveTextContent(/142 sightings\s*·\s*97 aircraft/);
    });
    expect(summary).not.toHaveTextContent("never seen before");
  });

  it("makes each figure a shortcut to the grouping that lists it", async () => {
    const user = userEvent.setup();
    installSightingsApiMock({
      counts: COUNTS,
      seenAircraft: [seenAircraftRow()],
      seenTypes: [seenTypeRow()],
    });
    const { router } = renderApp("/sightings");
    const summary = await screen.findByRole("group", {
      name: "In this window",
    });

    await user.click(
      await within(summary).findByRole("button", { name: /97 aircraft/ }),
    );
    await screen.findByTestId("seen-aircraft-row");
    expect(router.state.location.search).toBe("?group=aircraft");

    await user.click(within(summary).getByRole("button", { name: /31 types/ }));
    await screen.findByTestId("seen-type-row");
    expect(router.state.location.search).toBe("?group=types");

    await user.click(
      within(summary).getByRole("button", { name: /142 sightings/ }),
    );
    await waitFor(() => {
      expect(router.state.location.search).toBe("");
    });
  });

  it("says so, quietly, when the counts cannot be loaded", async () => {
    const base = installSightingsApiMock({
      list: { items: [sightingRow()], total: null, limit: 50, offset: 0 },
    });
    const original = base.fetchMock.getMockImplementation();
    base.fetchMock.mockImplementation(async (input, init) => {
      if (String(input).startsWith("/api/v1/analytics/counts")) {
        return new Response(
          JSON.stringify({
            error: { code: "internal_error", message: "boom", detail: null },
          }),
          { status: 500, headers: { "Content-Type": "application/json" } },
        );
      }
      return original!(input, init);
    });

    renderApp("/sightings");

    // The log is unaffected by a failed summary.
    await screen.findAllByTestId("sighting-row");
    expect(
      await screen.findByText("Counts unavailable.", undefined, {
        timeout: 4000,
      }),
    ).toBeInTheDocument();
  });
});

describe("grouped by aircraft", () => {
  it("lists each distinct aircraft of the window the way the site lists aircraft", async () => {
    const { fetchMock } = installSightingsApiMock({
      counts: COUNTS,
      seenAircraft: [
        seenAircraftRow(),
        seenAircraftRow({
          icao: "abcdef",
          registration: "N975QS",
          type: "C68A",
          model: "Cessna 680A Citation Latitude",
          operator: null,
          owner: "NetJets Sales Inc",
          operator_group: null,
          sightings: 1,
          new: true,
        }),
        seenAircraftRow({
          icao: "0f0f4f",
          registration: null,
          type: null,
          model: null,
          operator: null,
          owner: null,
          operator_group: null,
          sightings: 1,
        }),
      ],
    });

    renderApp("/sightings?group=aircraft&preset=7d");

    const rows = await screen.findAllByTestId("seen-aircraft-row");
    expect(rows).toHaveLength(3);
    expect(screen.getByRole("radio", { name: "Aircraft" })).toBeChecked();

    const first = within(rows[0] as HTMLElement);
    expect(first.getByRole("link", { name: "N228BZ" })).toHaveAttribute(
      "href",
      "/aircraft/a1b2c3",
    );
    expect(first.getByText("Airbus A220-300")).toBeInTheDocument();
    expect(first.getByRole("button", { name: "BCS3" })).toBeInTheDocument();
    expect(first.getByText("Breeze Airways")).toBeInTheDocument();
    expect(first.queryByTestId("new-badge")).not.toBeInTheDocument();

    const second = within(rows[1] as HTMLElement);
    expect(second.getByTestId("new-badge")).toHaveTextContent("New");
    expect(second.getByText("NetJets Sales Inc")).toBeInTheDocument();
    expect(second.getByText("registered owner")).toBeInTheDocument();

    // An aircraft no registry describes: its hex, and nothing invented.
    const third = within(rows[2] as HTMLElement);
    expect(third.getByRole("link", { name: "0F0F4F" })).toBeInTheDocument();

    const request = lastRequestTo(fetchMock, "/api/v1/analytics/aircraft");
    expect(request.searchParams.get("preset")).toBe("7d");
    expect(request.searchParams.get("limit")).toBe("50");
    expect(request.searchParams.get("offset")).toBe("0");
    // Only the grouping on screen asks for its page.
    expect(requestsTo(fetchMock, "/api/v1/sightings")).toHaveLength(0);
    expect(requestsTo(fetchMock, "/api/v1/analytics/types")).toHaveLength(0);
  });

  it("hides the log's filters, which do not apply to it", async () => {
    installSightingsApiMock({ seenAircraft: [seenAircraftRow()] });
    renderApp("/sightings?group=aircraft");
    await screen.findByTestId("seen-aircraft-row");

    expect(
      screen.queryByLabelText(/aircraft or callsign/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Open now" }),
    ).not.toBeInTheDocument();
  });

  it("narrows to one type from a row's designator, and clears again", async () => {
    const user = userEvent.setup();
    const { fetchMock } = installSightingsApiMock({
      seenAircraft: (url) =>
        url.searchParams.get("type") === "BCS3"
          ? [seenAircraftRow()]
          : [
              seenAircraftRow(),
              seenAircraftRow({
                icao: "bbbbbb",
                type: "B738",
                model: "Boeing 737-800",
                registration: "N802XT",
              }),
            ],
    });
    const { router } = renderApp("/sightings?group=aircraft");
    expect(await screen.findAllByTestId("seen-aircraft-row")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "BCS3" }));

    await waitFor(() => {
      expect(router.state.location.search).toBe("?group=aircraft&type=BCS3");
    });
    await waitFor(() => {
      expect(screen.getAllByTestId("seen-aircraft-row")).toHaveLength(1);
    });
    expect(screen.getByText("Showing only")).toBeInTheDocument();
    expect(
      lastRequestTo(fetchMock, "/api/v1/analytics/aircraft").searchParams.get(
        "type",
      ),
    ).toBe("BCS3");

    await user.click(screen.getByRole("button", { name: "Show all types" }));

    await waitFor(() => {
      expect(router.state.location.search).toBe("?group=aircraft");
    });
  });

  it("says when the window held no aircraft", async () => {
    installSightingsApiMock({ seenAircraft: [] });
    renderApp("/sightings?group=aircraft");

    expect(
      await screen.findByText("No aircraft were heard in this window."),
    ).toBeInTheDocument();
  });

  it("pages with an exact total", async () => {
    const user = userEvent.setup();
    const page = Array.from({ length: 50 }, (_, index) =>
      seenAircraftRow({
        icao: `a${String(index).padStart(5, "0")}`,
        registration: `N${index}`,
      }),
    );
    const base = installSightingsApiMock({ seenAircraft: page });
    const original = base.fetchMock.getMockImplementation();
    base.fetchMock.mockImplementation(async (input, init) => {
      const response = await original!(input, init);
      if (String(input).startsWith("/api/v1/analytics/aircraft")) {
        const body = (await response.json()) as Record<string, unknown>;
        return new Response(JSON.stringify({ ...body, total: 120 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return response;
    });
    const { router } = renderApp("/sightings?group=aircraft");
    await screen.findAllByTestId("seen-aircraft-row");

    expect(screen.getByText(/Page 1 of 3 · 120 aircraft/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /next/i }));

    await waitFor(() => {
      expect(router.state.location.search).toBe("?group=aircraft&page=2");
    });
    await waitFor(() => {
      expect(
        lastRequestTo(
          base.fetchMock,
          "/api/v1/analytics/aircraft",
        ).searchParams.get("offset"),
      ).toBe("50");
    });
  });
});

describe("grouped by type", () => {
  it("lists each distinct type, name over designator, with its counts", async () => {
    const { fetchMock } = installSightingsApiMock({
      seenTypes: [
        seenTypeRow(),
        seenTypeRow({
          type: "C68A",
          description: "Cessna 680A Citation Latitude",
          sightings: 1,
          unique_aircraft: 1,
          new: true,
        }),
        seenTypeRow({ type: "ZZZZ", description: null, sightings: 2 }),
      ],
    });

    renderApp("/sightings?group=types&preset=t0");

    const rows = await screen.findAllByTestId("seen-type-row");
    expect(rows).toHaveLength(3);
    expect(screen.getByRole("radio", { name: "Types" })).toBeChecked();

    const first = within(rows[0] as HTMLElement);
    expect(
      first.getByRole("button", { name: "Airbus A220-300" }),
    ).toBeInTheDocument();
    expect(first.getByText("BCS3")).toBeInTheDocument();
    expect(first.getAllByRole("cell").map((cell) => cell.textContent)).toEqual(
      expect.arrayContaining(["3", "11"]),
    );

    expect(
      within(rows[1] as HTMLElement).getByTestId("new-badge"),
    ).toBeInTheDocument();
    // No long form known: the designator stands alone, not twice.
    const third = within(rows[2] as HTMLElement);
    expect(third.getByRole("button", { name: "ZZZZ" })).toBeInTheDocument();
    expect(third.getAllByText("ZZZZ")).toHaveLength(1);

    expect(
      lastRequestTo(fetchMock, "/api/v1/analytics/types").searchParams.get(
        "preset",
      ),
    ).toBe("t0");
  });

  it("opens the aircraft of a type from its row", async () => {
    const user = userEvent.setup();
    installSightingsApiMock({
      seenTypes: [seenTypeRow()],
      seenAircraft: [seenAircraftRow()],
    });
    const { router } = renderApp("/sightings?group=types&preset=30d");
    await screen.findByTestId("seen-type-row");

    await user.click(screen.getByRole("button", { name: "Airbus A220-300" }));

    await screen.findByTestId("seen-aircraft-row");
    expect(router.state.location.search).toBe(
      "?preset=30d&group=aircraft&type=BCS3",
    );
  });

  it("says when the window held no typed aircraft", async () => {
    installSightingsApiMock({ seenTypes: [] });
    renderApp("/sightings?group=types");

    expect(
      await screen.findByText(
        "No aircraft with a known type were heard in this window.",
      ),
    ).toBeInTheDocument();
  });
});

describe("the grouping switch", () => {
  it("drops the type filter when leaving the aircraft grouping", async () => {
    const user = userEvent.setup();
    installSightingsApiMock({
      seenAircraft: [seenAircraftRow()],
      seenTypes: [seenTypeRow()],
    });
    const { router } = renderApp("/sightings?group=aircraft&type=BCS3");
    await screen.findByTestId("seen-aircraft-row");

    await user.click(screen.getByRole("radio", { name: "Types" }));

    await waitFor(() => {
      expect(router.state.location.search).toBe("?group=types");
    });
  });

  it("keeps the window when the grouping changes", async () => {
    const user = userEvent.setup();
    installSightingsApiMock({ seenTypes: [seenTypeRow()] });
    const { router } = renderApp("/sightings?preset=30d");
    await screen.findByText(/no sightings match this window/i);

    await user.click(screen.getByRole("radio", { name: "Types" }));

    await screen.findByTestId("seen-type-row");
    expect(router.state.location.search).toBe("?preset=30d&group=types");
    expect(screen.getByRole("radio", { name: "30 days" })).toBeChecked();
  });
});

describe("the log within a window", () => {
  it("leads a row's type with its name in words and marks a first sighting", async () => {
    installSightingsApiMock({
      list: {
        items: [
          sightingRow({ id: 1, first_sighting: true }),
          sightingRow({ id: 2, first_sighting: false }),
        ],
        total: null,
        limit: 50,
        offset: 0,
      },
    });

    renderApp("/sightings");

    const rows = await screen.findAllByTestId("sighting-row");
    expect(
      within(rows[0] as HTMLElement).getByTestId("new-badge"),
    ).toHaveTextContent("First sighting");
    expect(
      within(rows[1] as HTMLElement).queryByTestId("new-badge"),
    ).not.toBeInTheDocument();
  });
});
