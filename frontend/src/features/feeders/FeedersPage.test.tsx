import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FeedersPage } from "@/features/feeders/FeedersPage";
import { feedersQueryKey } from "@/lib/api/feeders";
import {
  feeder,
  feederHistory,
  feedersResponse,
  installFeedersApiMock,
} from "@/test/feedersApiMock";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <FeedersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...utils, queryClient };
}

describe("FeedersPage", () => {
  it("shows a loading state before the first response resolves", () => {
    installFeedersApiMock();
    renderPage();

    expect(
      screen.getByRole("heading", { level: 1, name: "Feeders" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading feeders…");
  });

  it("shows the empty state and a link to Settings when no feeders are configured", async () => {
    installFeedersApiMock({ feeders: feedersResponse({ feeders: [] }) });
    renderPage();

    expect(
      await screen.findByText("No feeders are configured yet."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Add feeders in Settings" }),
    ).toHaveAttribute("href", "/settings#settings-feeders");
  });

  it("renders the receiver uplink tiles, feeder cards and local pages on a populated install", async () => {
    installFeedersApiMock();
    renderPage();

    const cards = await screen.findByTestId("feeders-feed-cards");
    expect(within(cards).getByText("FlightAware")).toBeInTheDocument();
    expect(within(cards).getByText("ADS-B Exchange")).toBeInTheDocument();
    expect(within(cards).getByText("FlightRadar24")).toBeInTheDocument();

    // The per-feeder `data-testid`/`data-feeder` hooks
    // `e2e/tests/12-feeders.spec.ts` drives (work package coordination
    // note, 2026-09-26).
    const feederCards = within(cards).getAllByTestId("feeder-card");
    expect(feederCards).toHaveLength(3);
    expect(feederCards.map((card) => card.getAttribute("data-feeder"))).toEqual(
      ["flightaware", "adsbx", "fr24"],
    );

    // Receiver uplink tiles (design record: rendered from `receiver`).
    const uplink = screen.getByRole("group", { name: "Receiver uplink" });
    expect(within(uplink).getByText("Bytes out")).toBeInTheDocument();
    expect(within(uplink).getByText("Max range")).toBeInTheDocument();

    // Local pages.
    const localPages = screen.getByTestId("local-pages-card");
    expect(
      within(localPages).getByRole("link", { name: "tar1090" }),
    ).toHaveAttribute("href", "http://fermi.local:8080/");

    // The "as of ... refreshes every 10 s" caption.
    expect(screen.getByText(/refreshes every 10 s/)).toBeInTheDocument();
  });

  it("gives each feeder's gap timeline a stable data-testid/data-feeder hook", async () => {
    installFeedersApiMock();
    renderPage();

    const history = await screen.findByTestId("feeders-history");
    const timelines = within(history).getAllByTestId("gap-timeline");
    expect(timelines).toHaveLength(3);
    expect(timelines.map((row) => row.getAttribute("data-feeder"))).toEqual([
      "flightaware",
      "adsbx",
      "fr24",
    ]);
  });

  it("renders 'Not observed' for a null receiver-uplink field", async () => {
    installFeedersApiMock({
      feeders: feedersResponse({
        receiver: {
          bytes_out_rate_per_s: null,
          messages_per_min: null,
          aircraft: null,
          mlat_inbound: null,
          samples_dropped: null,
          max_range_nm: null,
        },
      }),
    });
    renderPage();

    await screen.findByTestId("feeders-feed-cards");
    const uplink = screen.getByRole("group", { name: "Receiver uplink" });
    expect(within(uplink).getAllByText("Not observed").length).toBe(6);
  });

  it("renders a StatusPill per feeder state (up, degraded, down, unknown)", async () => {
    installFeedersApiMock({
      feeders: feedersResponse({
        feeders: [
          feeder({ name: "a", label: "Alpha", state: "up" }),
          feeder({ name: "b", label: "Bravo", state: "degraded" }),
          feeder({ name: "c", label: "Charlie", state: "down" }),
          feeder({ name: "d", label: "Delta", state: "unknown" }),
        ],
      }),
    });
    renderPage();

    const cardsContainer = await screen.findByTestId("feeders-feed-cards");
    const cards = within(cardsContainer).getAllByRole("region");
    const byName = (name: string) =>
      cards.find((el) => within(el).queryByText(name) !== null);

    expect(
      within(byName("Alpha") as HTMLElement).getByText("Up"),
    ).toBeInTheDocument();
    expect(
      within(byName("Bravo") as HTMLElement).getByText("Degraded"),
    ).toBeInTheDocument();
    expect(
      within(byName("Charlie") as HTMLElement).getByText("Down"),
    ).toBeInTheDocument();
    expect(
      within(byName("Delta") as HTMLElement).getByText("Unknown"),
    ).toBeInTheDocument();
  });

  it("shows the socket-off observability note for a feeder with observability 'none'", async () => {
    installFeedersApiMock({
      feeders: feedersResponse({
        feeders: [
          feeder({
            name: "opensky",
            label: "OpenSky Network",
            kind: "opensky_logs",
            state: "unknown",
            observability: "none",
          }),
        ],
      }),
    });
    renderPage();

    expect(
      await screen.findByText("Needs the Docker socket — see Settings"),
    ).toBeInTheDocument();
  });

  it("renders the stats link as a plain, never-fetched internal redirect anchor", async () => {
    const { fetchMock } = installFeedersApiMock({
      feeders: feedersResponse({
        feeders: [
          feeder({
            name: "flightaware",
            label: "FlightAware",
            stats_link: true,
          }),
        ],
      }),
    });
    renderPage();

    const link = await screen.findByRole("link", {
      name: "View stats on FlightAware",
    });
    expect(link).toHaveAttribute(
      "href",
      "/api/internal/feeders/flightaware/stats-link",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    // Never fetched from the frontend — only navigated to.
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("stats-link"),
      ),
    ).toBe(false);
  });

  it("omits the stats link when the feeder has none configured", async () => {
    installFeedersApiMock({
      feeders: feedersResponse({
        feeders: [
          feeder({ name: "fr24", label: "FlightRadar24", stats_link: false }),
        ],
      }),
    });
    renderPage();

    await screen.findByTestId("feeders-feed-cards");
    expect(
      screen.queryByRole("link", { name: "View stats on FlightRadar24" }),
    ).not.toBeInTheDocument();
  });

  it("keeps rendering cached feeder cards with a retry banner when a refresh fails (R4-04 pattern)", async () => {
    const { fetchMock: baseline } = installFeedersApiMock();
    const { queryClient } = renderPage();

    const cards = await screen.findByTestId("feeders-feed-cards");
    expect(within(cards).getByText("FlightAware")).toBeInTheDocument();

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), "http://localhost");
        if (url.pathname === "/api/v1/feeders") {
          return Promise.resolve(new Response("", { status: 500 }));
        }
        return baseline(input, init);
      }),
    );

    await act(async () => {
      await queryClient.refetchQueries({ queryKey: feedersQueryKey });
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Refreshing failed/,
    );
    // The cached card is still on screen, not replaced by the error.
    expect(within(cards).getByText("FlightAware")).toBeInTheDocument();

    const user = userEvent.setup();
    vi.stubGlobal("fetch", baseline);
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await within(cards).findByText("FlightAware");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a full-page error only when nothing has ever loaded", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("", { status: 500 }))),
    );
    renderPage();

    expect(
      await screen.findByText(/Could not load feeders/),
    ).toBeInTheDocument();
  });

  it("stacks feeder cards and offers a horizontal-scroll affordance for the timeline at phone width", async () => {
    installFeedersApiMock({
      history: {
        "flightaware:24h": feederHistory(),
      },
    });
    renderPage();

    const cardsContainer = await screen.findByTestId("feeders-feed-cards");

    // The card grid stacks to a single column below `sm` — structural
    // classes rather than a computed layout, since jsdom does not evaluate
    // media queries.
    expect(cardsContainer.className).toMatch(/grid/);
    expect(cardsContainer.className).toMatch(/sm:grid-cols-2/);

    // The gap timeline's horizontal-scroll hint is always in the DOM (CSS
    // hides it at wider viewports via `sm:hidden`), so a phone-width reader
    // — real or assistive tech ignoring the media query — always has it.
    expect(
      await screen.findByText("Scroll to see the full range →"),
    ).toBeInTheDocument();
  });
});
