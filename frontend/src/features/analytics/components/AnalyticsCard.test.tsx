import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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
    expect(screen.queryByText(/UTC/)).not.toBeInTheDocument();
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

  it("renders children and the echoed window once loaded", () => {
    render(
      <AnalyticsCard title="Top aircraft" isLoading={false} window={WINDOW}>
        <p>content</p>
      </AnalyticsCard>,
    );

    expect(screen.getByText("content")).toBeInTheDocument();
    expect(screen.getByText("Top aircraft")).toBeInTheDocument();
    expect(screen.getByText(/UTC/)).toBeInTheDocument();
  });
});
