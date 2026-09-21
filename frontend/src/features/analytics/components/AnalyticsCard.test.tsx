import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";

const WINDOW = {
  preset: "today" as const,
  from: "2026-08-31T00:00:00.000Z",
  to: "2026-09-01T00:00:00.000Z",
  first_day: "2026-08-31",
  last_day: "2026-08-31",
  timezone: "UTC",
};

describe("AnalyticsCard", () => {
  it("shows a loading state and no window caption while pending", () => {
    render(
      <AnalyticsCard title="Top aircraft" isLoading>
        <p>content</p>
      </AnalyticsCard>,
    );

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByText(/Aug 31, 2026/)).not.toBeInTheDocument();
  });

  it("shows an error message in place of children", () => {
    render(
      <AnalyticsCard
        title="Top aircraft"
        isLoading={false}
        error="Could not load top aircraft."
      >
        <p>content</p>
      </AnalyticsCard>,
    );

    expect(
      screen.getByText("Could not load top aircraft."),
    ).toBeInTheDocument();
    expect(screen.queryByText("content")).not.toBeInTheDocument();
  });

  it("shows no Retry button in the error state when onRetry is omitted (R3-08's page-banner cards)", () => {
    render(
      <AnalyticsCard
        title="Top aircraft"
        isLoading={false}
        error="Could not load top aircraft."
      >
        <p>content</p>
      </AnalyticsCard>,
    );

    expect(
      screen.queryByRole("button", { name: "Retry" }),
    ).not.toBeInTheDocument();
  });

  it("shows a Retry button in the error state that calls onRetry (R3-05)", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <AnalyticsCard
        title="Top aircraft"
        isLoading={false}
        error="Could not load top aircraft."
        onRetry={onRetry}
      >
        <p>content</p>
      </AnalyticsCard>,
    );

    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders children and the echoed window once loaded, with no timezone of its own (R3-11)", () => {
    render(
      <AnalyticsCard title="Top aircraft" isLoading={false} window={WINDOW}>
        <p>content</p>
      </AnalyticsCard>,
    );

    expect(screen.getByText("content")).toBeInTheDocument();
    expect(screen.getByText("Top aircraft")).toBeInTheDocument();
    expect(screen.getByText("Aug 31, 2026")).toBeInTheDocument();
    // The timezone is stated once per page (AnalyticsPage's "Data as of"
    // line), not once per card.
    expect(screen.queryByText(/UTC/)).not.toBeInTheDocument();
  });
});
