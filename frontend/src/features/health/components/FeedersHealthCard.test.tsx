import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { FeedersHealthCard } from "@/features/health/components/FeedersHealthCard";
import type { DiagnosticsFeeders } from "@/lib/api/diagnostics";

function feeders(
  overrides: Partial<DiagnosticsFeeders> = {},
): DiagnosticsFeeders {
  return {
    configured: 6,
    up: 6,
    degraded: 0,
    down: 0,
    unknown: 0,
    docker_socket: "available",
    ...overrides,
  };
}

function renderCard(overrides: Partial<DiagnosticsFeeders> = {}) {
  return render(
    <MemoryRouter>
      <FeedersHealthCard feeders={feeders(overrides)} />
    </MemoryRouter>,
  );
}

function card(): HTMLElement {
  return screen.getByRole("region", { name: "Feeders" });
}

describe("FeedersHealthCard", () => {
  it("renders a healthy pill when every feeder is up", () => {
    renderCard();
    expect(within(card()).getByText("Healthy")).toBeInTheDocument();
  });

  it("renders a degraded pill when a feeder is degraded or unknown", () => {
    renderCard({ up: 5, degraded: 1 });
    // Scoped to the pill itself (`data-tone`): the card's own "Degraded"
    // `DetailRow` label reads the same text, so an unscoped query is
    // ambiguous between the two.
    expect(
      within(card()).getByText("Degraded", { selector: "[data-tone]" }),
    ).toBeInTheDocument();
  });

  it("renders a problem pill when a feeder is down", () => {
    renderCard({ up: 5, down: 1 });
    expect(within(card()).getByText("Problem")).toBeInTheDocument();
  });

  it("shows the counts and the Docker socket state", () => {
    renderCard({ docker_socket: "unset" });
    const section = card();
    expect(within(section).getByText("Configured")).toBeInTheDocument();
    expect(within(section).getByText("Not configured")).toBeInTheDocument();
  });

  it("links to the full Feeders page", () => {
    renderCard();
    expect(
      screen.getByRole("link", { name: "Open the Feeders page" }),
    ).toHaveAttribute("href", "/receiver/feeders");
  });
});
