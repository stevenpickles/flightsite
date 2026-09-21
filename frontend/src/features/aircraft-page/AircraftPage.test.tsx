import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PAGE_SIZE } from "@/features/aircraft-page/lib/urlState";
import {
  aircraftDetail,
  aircraftListRow,
  defaultReceiverInfo,
  installAircraftApiMock,
} from "@/test/aircraftApiMock";
import { renderApp } from "@/test/test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function lastFetchedUrl(fetchMock: ReturnType<typeof vi.fn>): URL {
  const calls = fetchMock.mock.calls;
  const last = calls[calls.length - 1] as [string];
  return new URL(last[0], "http://localhost");
}

describe("AircraftPage", () => {
  it("shows a loading state before the list resolves", () => {
    let resolveList!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((resolve) => (resolveList = resolve))),
    );

    renderApp("/aircraft");

    expect(screen.getByText(/loading aircraft/i)).toBeInTheDocument();
    // Avoid leaking the unsettled fetch into the next test.
    resolveList(new Response("{}", { status: 200 }));
  });

  it("shows an empty state when the receiver has never sighted anything", async () => {
    installAircraftApiMock({
      list: { items: [], total: 0, limit: PAGE_SIZE, offset: 0 },
    });

    renderApp("/aircraft");

    expect(
      await screen.findByText(/hasn.t sighted any aircraft yet/i),
    ).toBeInTheDocument();
  });

  it("renders the documented columns for each row, mission spelled as a label", async () => {
    installAircraftApiMock({
      list: {
        items: [
          aircraftListRow({
            icao: "ae1463",
            registration: "N302DN",
            classification: {
              military: false,
              government: false,
              law_enforcement: false,
              mission: "commercial_passenger",
              icon_category: null,
              confidence: "high",
            },
          }),
        ],
        total: 1,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });

    renderApp("/aircraft");

    expect(await screen.findByText("N302DN")).toBeInTheDocument();
    expect(screen.getByText("AE1463")).toBeInTheDocument();
    expect(screen.getByText("Delta Air Lines")).toBeInTheDocument();
    // The raw enum value never reaches the screen.
    expect(screen.queryByText(/commercial_passenger/)).not.toBeInTheDocument();
    expect(
      screen.getByText("Civilian · Commercial passenger"),
    ).toBeInTheDocument();
  });

  it("sorts by a clicked column, descending first, and toggles on a second click", async () => {
    const { fetchMock } = installAircraftApiMock({
      list: {
        items: [aircraftListRow()],
        total: 1,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });
    const user = userEvent.setup();
    const { router } = renderApp("/aircraft");
    await screen.findByText("N302DN");

    await user.click(screen.getByRole("button", { name: "ICAO" }));

    await waitFor(() => {
      expect(lastFetchedUrl(fetchMock).searchParams.get("sort")).toBe("icao");
    });
    expect(lastFetchedUrl(fetchMock).searchParams.get("order")).toBe("desc");
    expect(router.state.location.search).toContain("sort=icao");

    await user.click(screen.getByRole("button", { name: /icao/i }));

    await waitFor(() => {
      expect(lastFetchedUrl(fetchMock).searchParams.get("order")).toBe("asc");
    });
  });

  it("persists the current page in the URL and pages through the result", async () => {
    const total = PAGE_SIZE + 5;
    const { fetchMock } = installAircraftApiMock({
      list: (url) => {
        const offset = Number(url.searchParams.get("offset") ?? "0");
        return {
          items: [
            aircraftListRow({
              icao: offset === 0 ? "aaaaaa" : "bbbbbb",
              registration: offset === 0 ? "PAGE-ONE" : "PAGE-TWO",
            }),
          ],
          total,
          limit: PAGE_SIZE,
          offset,
        };
      },
    });
    const user = userEvent.setup();
    const { router } = renderApp("/aircraft");
    await screen.findByText("PAGE-ONE");

    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /next/i }));

    expect(await screen.findByText("PAGE-TWO")).toBeInTheDocument();
    expect(router.state.location.search).toContain("page=2");
    expect(lastFetchedUrl(fetchMock).searchParams.get("offset")).toBe(
      String(PAGE_SIZE),
    );

    await user.click(screen.getByRole("button", { name: /previous/i }));

    expect(await screen.findByText("PAGE-ONE")).toBeInTheDocument();
    expect(router.state.location.search).not.toContain("page=");
  });

  it("says so and offers a way back when the URL names a page past the end (R2-09)", async () => {
    installAircraftApiMock({
      list: (url) => ({
        items: [],
        total: 68,
        limit: PAGE_SIZE,
        offset: Number(url.searchParams.get("offset") ?? "0"),
      }),
    });
    const user = userEvent.setup();
    const { router } = renderApp("/aircraft?page=999");

    // Before: a header row, no body rows, "Page 999 of 2", and no
    // explanation — reachable from a bookmark after history is pruned.
    const state = await screen.findByTestId("past-the-end");
    expect(state).toHaveAttribute("role", "status");
    expect(state).toHaveTextContent("There is nothing on page 999");

    await user.click(screen.getByRole("button", { name: /back to page 1/i }));

    await waitFor(() => {
      expect(router.state.location.search).not.toContain("page=");
    });
  });

  it("names the receiver's timezone and stamps every cell with its instant (R2-14)", async () => {
    installAircraftApiMock({
      list: {
        items: [aircraftListRow()],
        total: 1,
        limit: PAGE_SIZE,
        offset: 0,
      },
      receiver: defaultReceiverInfo({ timezone: "America/New_York" }),
    });

    renderApp("/aircraft");
    await screen.findByText("N302DN");

    // Said once per page, not once per row — the review found the zone
    // named nowhere on any of the five routes.
    await waitFor(() =>
      expect(screen.getByTestId("timezone-note")).toHaveTextContent(
        "All times America/New_York",
      ),
    );

    // And every timestamp carries the instant behind it, which is what a
    // reader correlating FlightSite with another log actually needs.
    const lastSeen = screen.getByText("2026-08-30 18:41");
    expect(lastSeen.tagName).toBe("TIME");
    expect(lastSeen).toHaveAttribute("datetime", "2026-08-30T22:41:55.000Z");
    expect(lastSeen.getAttribute("title")).toContain("2026-08-30T22:41:55");
  });

  it("says how old the table is and fetches again on demand (R2-03)", async () => {
    const { fetchMock } = installAircraftApiMock({
      list: {
        items: [aircraftListRow()],
        total: 1,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });
    const user = userEvent.setup();
    renderApp("/aircraft");
    await screen.findByText("N302DN");

    // The page commits to an age rather than leaving "is this current?"
    // unanswerable, which is the whole of the finding.
    expect(
      within(screen.getByTestId("refresh-status")).getByText(/^Updated /),
    ).toBeInTheDocument();

    const before = fetchMock.mock.calls.filter(([url]) =>
      String(url).startsWith("/api/v1/aircraft?"),
    ).length;
    await user.click(screen.getByRole("button", { name: /refresh/i }));

    await waitFor(() => {
      const after = fetchMock.mock.calls.filter(([url]) =>
        String(url).startsWith("/api/v1/aircraft?"),
      ).length;
      expect(after).toBeGreaterThan(before);
    });
  });

  it("offers a retry when the first load fails, and recovers without a reload (R2-04)", async () => {
    let failing = true;
    installAircraftApiMock({
      listStatus: () => (failing ? 500 : null),
      list: {
        items: [aircraftListRow()],
        total: 1,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });
    const user = userEvent.setup();
    renderApp("/aircraft");

    const failure = await screen.findByTestId("query-error-state");
    expect(failure).toHaveAttribute("role", "alert");

    failing = false;
    await user.click(screen.getByRole("button", { name: /try again/i }));

    // Recovered in place: no browser reload was needed, which is the whole
    // of the finding.
    expect(await screen.findByText("N302DN")).toBeInTheDocument();
    expect(screen.queryByTestId("query-error-state")).not.toBeInTheDocument();
  });

  it("keeps the table, its sort headers and its pagination when a refresh fails (R2-04)", async () => {
    let failing = false;
    installAircraftApiMock({
      listStatus: () => (failing ? 500 : null),
      list: {
        items: [aircraftListRow()],
        total: 1,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });
    const user = userEvent.setup();
    renderApp("/aircraft");
    await screen.findByText("N302DN");

    failing = true;
    await user.click(screen.getByRole("button", { name: /^refresh$/i }));

    expect(await screen.findByTestId("query-error-banner")).toBeInTheDocument();
    // The previous answer is still the best one anybody has, so it stays —
    // along with every control capable of asking again.
    expect(screen.getByText("N302DN")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ICAO" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeInTheDocument();
  });

  it("opens the aircraft detail route when a row is clicked", async () => {
    installAircraftApiMock({
      list: {
        items: [aircraftListRow({ icao: "ae1463" })],
        total: 1,
        limit: PAGE_SIZE,
        offset: 0,
      },
      detail: { ae1463: aircraftDetail({ icao: "ae1463" }) },
    });
    const user = userEvent.setup();
    const { router } = renderApp("/aircraft");
    const row = (await screen.findByText("N302DN")).closest("tr");
    expect(row).not.toBeNull();

    await user.click(within(row as HTMLElement).getByText("N302DN"));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/aircraft/ae1463");
    });
  });

  it("also opens the detail route when a non-link cell in the row is clicked", async () => {
    installAircraftApiMock({
      list: {
        items: [aircraftListRow({ icao: "ae1463" })],
        total: 1,
        limit: PAGE_SIZE,
        offset: 0,
      },
      detail: { ae1463: aircraftDetail({ icao: "ae1463" }) },
    });
    const user = userEvent.setup();
    const { router } = renderApp("/aircraft");
    await screen.findByText("N302DN");

    // The ICAO cell has no link of its own — the row's own click handler
    // is what has to carry this one.
    await user.click(screen.getByText("AE1463"));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/aircraft/ae1463");
    });
  });
});
