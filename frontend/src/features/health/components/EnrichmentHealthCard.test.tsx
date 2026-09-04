import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EnrichmentHealthCard } from "@/features/health/components/EnrichmentHealthCard";
import { enrichment } from "@/test/diagnosticsApiMock";
import type { DiagnosticsEnrichment } from "@/lib/api/diagnostics";

function renderCard(overrides: Partial<DiagnosticsEnrichment> = {}) {
  return render(
    <EnrichmentHealthCard
      enrichment={enrichment(overrides)}
      timezone="America/Los_Angeles"
    />,
  );
}

function card(): HTMLElement {
  return screen.getByRole("region", { name: "Route enrichment" });
}

describe("EnrichmentHealthCard", () => {
  it("keeps the slice 042 counters", () => {
    renderCard({ enabled: true, lookups: 1240, failures: 3 });

    const section = card();
    expect(within(section).getByText("1,240")).toBeInTheDocument();
    expect(within(section).getByText("3")).toBeInTheDocument();
    expect(within(section).getByText("Closed")).toBeInTheDocument();
  });

  it("shows a capped budget as used, limit, remaining and reset time", () => {
    renderCard({
      budget: {
        limit: 100,
        used_today: 12,
        remaining: 88,
        resets_at: "2026-09-01T00:00:00.000Z",
      },
    });

    const section = card();
    expect(within(section).getByText("12 / 100 used")).toBeInTheDocument();
    expect(within(section).getByText("88")).toBeInTheDocument();
    // Rendered in the receiver's timezone: midnight UTC is the previous
    // afternoon in Los Angeles, and that is the answer an operator needs.
    expect(within(section).getByText("2026-08-31 17:00")).toBeInTheDocument();
    expect(within(section).getByText("88 left today")).toHaveAttribute(
      "data-tone",
      "ok",
    );
  });

  it("calls an uncapped budget uncapped rather than inventing a limit", () => {
    renderCard({
      budget: {
        limit: null,
        used_today: 412,
        remaining: null,
        resets_at: "2026-09-01T00:00:00.000Z",
      },
    });

    const section = card();
    expect(
      within(section).getByText("412 used · uncapped"),
    ).toBeInTheDocument();
    expect(within(section).queryByText("Remaining today")).toBeNull();
    expect(within(section).getByText("Uncapped")).toHaveAttribute(
      "data-tone",
      "idle",
    );
  });

  it("warns, rather than errors, when the budget is spent", () => {
    // Reaching a cap the operator set is the economy working, not a fault:
    // cached and locally-learned routes keep being served and the counter
    // rolls over at midnight UTC.
    renderCard({
      budget: {
        limit: 50,
        used_today: 50,
        remaining: 0,
        resets_at: "2026-09-01T00:00:00.000Z",
      },
    });

    const pill = within(card()).getByText("Budget spent");
    expect(pill).toHaveAttribute("data-tone", "warn");
    expect(pill).not.toHaveAttribute("data-tone", "bad");
  });

  it("reports the cache counters", () => {
    renderCard({ cache: { hits: 340, misses: 42, learned: 17 } });

    const section = card();
    expect(within(section).getByText("Cache hits")).toBeInTheDocument();
    expect(within(section).getByText("340")).toBeInTheDocument();
    expect(within(section).getByText("42")).toBeInTheDocument();
    expect(within(section).getByText("Routes learned")).toBeInTheDocument();
    expect(within(section).getByText("17")).toBeInTheDocument();
  });

  it("degrades to the pre-070 card when the backend sends neither block", () => {
    // A frontend ahead of its backend must not render zeroes: "the cache
    // never hits" and "this backend does not say" are different claims.
    renderCard({ budget: undefined, cache: undefined });

    const section = card();
    expect(within(section).getByText("Lookups")).toBeInTheDocument();
    expect(within(section).queryByText("Daily budget")).toBeNull();
    expect(within(section).queryByText("Budget resets")).toBeNull();
    expect(within(section).queryByText("Cache hits")).toBeNull();
    expect(within(section).queryByText("Routes learned")).toBeNull();
    expect(section.querySelector("[data-tone]")).toBeNull();
  });
});
