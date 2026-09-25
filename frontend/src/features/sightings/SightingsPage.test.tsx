import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PAGE_SIZE } from "@/features/sightings/lib/urlState";
import { installSightingsApiMock, sightingRow } from "@/test/sightingsApiMock";
import { renderApp } from "@/test/test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function lastFetchedSightingsUrl(fetchMock: ReturnType<typeof vi.fn>): URL {
  const calls = fetchMock.mock.calls as [string][];
  const match = [...calls]
    .reverse()
    .find(([url]) => url.toString().startsWith("/api/v1/sightings?"));
  if (!match) {
    throw new Error("no /api/v1/sightings request was made");
  }
  return new URL(match[0], "http://localhost");
}

describe("SightingsPage", () => {
  it("shows a loading state before the log resolves", () => {
    let resolveList!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((resolve) => (resolveList = resolve))),
    );

    renderApp("/sightings");

    expect(screen.getByText(/loading sightings/i)).toBeInTheDocument();
    resolveList(new Response("{}", { status: 200 }));
  });

  it("shows an empty state when nothing matches", async () => {
    installSightingsApiMock({
      list: { items: [], total: null, limit: PAGE_SIZE, offset: 0 },
    });

    renderApp("/sightings");

    expect(
      await screen.findByText(/no sightings match these filters/i),
    ).toBeInTheDocument();
  });

  it("renders the documented row fields", async () => {
    installSightingsApiMock({
      list: {
        items: [
          sightingRow({
            id: 1,
            icao: "ae1463",
            registration: "N302DN",
            closure_reason: "gap_timeout",
          }),
        ],
        total: null,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });

    renderApp("/sightings");

    expect(await screen.findByText("N302DN")).toBeInTheDocument();
    expect(screen.getByText("Delta Air Lines")).toBeInTheDocument();
    expect(screen.getByText("Timed out")).toBeInTheDocument();
  });

  it("renders 'Ongoing' for an open sighting instead of an end time", async () => {
    installSightingsApiMock({
      list: {
        items: [sightingRow({ id: 1, ended_at: null, duration_s: null })],
        total: null,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });

    renderApp("/sightings");

    expect(await screen.findAllByText("Ongoing")).not.toHaveLength(0);
  });

  it("says how long an open sighting has been running, not Unknown (R2-02)", async () => {
    installSightingsApiMock({
      list: {
        items: [
          sightingRow({
            id: 1,
            ended_at: null,
            duration_s: null,
            elapsed_s: 964,
          }),
        ],
        total: null,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });

    renderApp("/sightings");

    // `Unknown` means "the decoder never reported this". A sighting the same
    // row calls "Ongoing" two columns to the left is a different fact.
    const duration = await screen.findByText(
      "Still open · running for 16m 04s",
    );
    expect(duration.closest("td")).not.toHaveTextContent("Unknown");
  });

  it("sorts by a clicked sortable column, descending first, and toggles on a second click", async () => {
    const { fetchMock } = installSightingsApiMock({
      list: {
        items: [sightingRow()],
        total: null,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });
    const user = userEvent.setup();
    const { router } = renderApp("/sightings");
    await screen.findByText("N302DN");

    await user.click(screen.getByRole("button", { name: "Duration" }));

    await waitFor(() => {
      expect(lastFetchedSightingsUrl(fetchMock).searchParams.get("sort")).toBe(
        "duration_s",
      );
    });
    expect(lastFetchedSightingsUrl(fetchMock).searchParams.get("order")).toBe(
      "desc",
    );
    expect(router.state.location.search).toContain("sort=duration_s");

    await user.click(screen.getByRole("button", { name: "Duration" }));

    await waitFor(() => {
      expect(lastFetchedSightingsUrl(fetchMock).searchParams.get("order")).toBe(
        "asc",
      );
    });
  });

  it("filters by icao and persists it in the URL", async () => {
    const { fetchMock } = installSightingsApiMock({
      list: {
        items: [sightingRow()],
        total: null,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });
    const user = userEvent.setup();
    const { router } = renderApp("/sightings");
    await screen.findByText("N302DN");

    await user.type(screen.getByLabelText(/aircraft \(icao\)/i), "ae1463");
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(lastFetchedSightingsUrl(fetchMock).searchParams.get("icao")).toBe(
        "ae1463",
      );
    });
    expect(router.state.location.search).toContain("icao=ae1463");
  });

  it("rejects a malformed icao filter without changing the URL", async () => {
    installSightingsApiMock({
      list: {
        items: [sightingRow()],
        total: null,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });
    const user = userEvent.setup();
    const { router } = renderApp("/sightings");
    await screen.findByText("N302DN");

    await user.type(screen.getByLabelText(/aircraft \(icao\)/i), "not-hex");
    await user.keyboard("{Enter}");

    expect(
      await screen.findByText(/enter a 6-character hex icao address/i),
    ).toBeInTheDocument();
    expect(router.state.location.search).not.toContain("icao=");
  });

  it("toggles the open-now filter and persists it in the URL", async () => {
    const { fetchMock } = installSightingsApiMock({
      list: {
        items: [sightingRow()],
        total: null,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });
    const user = userEvent.setup();
    const { router } = renderApp("/sightings");
    await screen.findByText("N302DN");

    await user.click(screen.getByRole("button", { name: /open now/i }));

    await waitFor(() => {
      expect(lastFetchedSightingsUrl(fetchMock).searchParams.get("open")).toBe(
        "true",
      );
    });
    expect(router.state.location.search).toContain("open=true");
  });

  it("pages through the result using 'a full page came back' since total is omitted", async () => {
    const { fetchMock } = installSightingsApiMock({
      list: (url) => {
        const offset = Number(url.searchParams.get("offset") ?? "0");
        return {
          items: Array.from(
            { length: offset === 0 ? PAGE_SIZE : 3 },
            (_, index) =>
              sightingRow({
                id: offset + index + 1,
                registration: offset === 0 ? "PAGE-ONE" : "PAGE-TWO",
              }),
          ),
          total: null,
          limit: PAGE_SIZE,
          offset,
        };
      },
    });
    const user = userEvent.setup();
    const { router } = renderApp("/sightings");
    await screen.findAllByText("PAGE-ONE");

    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /next/i })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: /next/i }));

    await screen.findAllByText("PAGE-TWO");
    expect(router.state.location.search).toContain("page=2");
    expect(lastFetchedSightingsUrl(fetchMock).searchParams.get("offset")).toBe(
      String(PAGE_SIZE),
    );
    // A short (< limit) page means there is no next page.
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
  });

  it("keeps the log on screen and offers a retry when a refresh fails (R2-04)", async () => {
    let failing = false;
    installSightingsApiMock({
      listStatus: () => (failing ? 500 : null),
      list: {
        items: [sightingRow()],
        total: null,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });
    const user = userEvent.setup();
    renderApp("/sightings");
    await screen.findByText("N302DN");

    failing = true;
    await user.click(screen.getByRole("button", { name: /^refresh$/i }));

    const banner = await screen.findByTestId("query-error-banner");
    expect(banner).toHaveAttribute("role", "alert");
    expect(screen.getByText("N302DN")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Duration" }),
    ).toBeInTheDocument();

    failing = false;
    await user.click(
      within(banner).getByRole("button", { name: /try again/i }),
    );

    await waitFor(() =>
      expect(
        screen.queryByTestId("query-error-banner"),
      ).not.toBeInTheDocument(),
    );
  });

  it("keeps Status on screen and defers the columns that crowded it out (R2-08, R2-13)", async () => {
    installSightingsApiMock({
      list: {
        items: [sightingRow({ id: 1 })],
        total: null,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });

    renderApp("/sightings");
    await screen.findByText("N302DN");

    const header = (label: string) =>
      screen.getByRole("columnheader", { name: label });

    // §57's alert/interesting column is essential — it is the one a
    // 1440x900 desktop could not see at all.
    expect(header("Status").className).not.toContain("hidden");
    expect(header("Start").className).not.toContain("hidden");
    // The four that were costing it that width wait for a wide window, and
    // their header and body cell agree about it.
    for (const label of ["Classification", "Lowest alt.", "Positions"]) {
      expect(header(label).className).toContain("2xl:table-cell");
    }
    const row = screen.getByTestId("sighting-row");
    expect(within(row).getByText("2210").className).toContain("2xl:table-cell");
  });

  it("gives every row a keyboard route into its sighting (R2-07)", async () => {
    installSightingsApiMock({
      list: {
        items: [sightingRow({ id: 42 }), sightingRow({ id: 43 })],
        total: null,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });

    renderApp("/sightings");
    await screen.findAllByText("N302DN");

    // The review audited fifty rendered rows and found zero anchors, zero
    // buttons and zero `[tabindex]` — no keyboard or screen-reader user
    // could open any sighting from the log at all.
    const rows = screen.getAllByTestId("sighting-row");
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      const link = within(row).getByRole("link");
      expect(link).toHaveAttribute(
        "href",
        `/sightings/${row.getAttribute("data-sighting-id")}`,
      );
    }
  });

  it("opens the sighting detail route when a row is clicked", async () => {
    installSightingsApiMock({
      list: {
        items: [sightingRow({ id: 42 })],
        total: null,
        limit: PAGE_SIZE,
        offset: 0,
      },
    });
    const user = userEvent.setup();
    const { router } = renderApp("/sightings");
    const row = (await screen.findByText("N302DN")).closest("tr");
    expect(row).not.toBeNull();

    await user.click(within(row as HTMLElement).getByText("N302DN"));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/sightings/42");
    });
  });
});
