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
