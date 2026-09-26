import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FeedersSummaryCard } from "@/features/receiver/components/FeedersSummaryCard";
import {
  feeder,
  feedersResponse,
  installFeedersApiMock,
} from "@/test/feedersApiMock";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderCard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <FeedersSummaryCard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function card(): HTMLElement {
  return screen.getByRole("region", { name: "Feeders" });
}

describe("FeedersSummaryCard", () => {
  it("shows an 'N of M feeds up' count and a link to the full page", async () => {
    installFeedersApiMock({
      feeders: feedersResponse({
        feeders: [
          feeder({ name: "a", state: "up" }),
          feeder({ name: "b", state: "up" }),
          feeder({ name: "c", state: "down" }),
        ],
      }),
    });

    renderCard();

    expect(await screen.findByText("2 of 3 feeds up")).toBeInTheDocument();
    expect(
      within(card()).getByRole("link", { name: "View feeders" }),
    ).toHaveAttribute("href", "/receiver/feeders");
  });

  it("shows the worst state's pill, never color alone", async () => {
    installFeedersApiMock({
      feeders: feedersResponse({
        feeders: [
          feeder({ name: "a", state: "up" }),
          feeder({ name: "b", state: "down" }),
        ],
      }),
    });

    renderCard();

    expect(await screen.findByText("Down")).toBeInTheDocument();
  });

  it("is discoverable, not hidden, when no feeders are configured", async () => {
    installFeedersApiMock({ feeders: feedersResponse({ feeders: [] }) });

    renderCard();

    expect(
      await screen.findByText(/No feeders configured/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "add them in Settings" }),
    ).toHaveAttribute("href", "/settings#settings-feeders");
  });
});
