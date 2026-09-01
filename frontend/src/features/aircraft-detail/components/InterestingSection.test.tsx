import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InterestingSection } from "@/features/aircraft-detail/components/InterestingSection";

describe("InterestingSection", () => {
  it("renders nothing when no alert is matching", () => {
    // Not an "Alerts: none" row: that would be chrome on the overwhelming
    // majority of aircraft and would make the alerting one harder to spot.
    const { container } = render(<InterestingSection interesting={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names the severity in words, not by colour alone", () => {
    render(
      <InterestingSection
        interesting={{ severity: "critical", reasons: ["Emergency squawk"] }}
      />,
    );
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });

  it("lists every reason standing against the aircraft", () => {
    // The engine can stand more than one match against a sighting, and the
    // detail panel is where a user goes to find out which rule fired.
    render(
      <InterestingSection
        interesting={{
          severity: "high",
          reasons: ["Rule: Military aircraft", "Rule: Watchlist — Tankers"],
        }}
      />,
    );
    expect(screen.getByText("Rule: Military aircraft")).toBeInTheDocument();
    expect(screen.getByText("Rule: Watchlist — Tankers")).toBeInTheDocument();
    expect(screen.getByText("Reasons")).toBeInTheDocument();
  });

  it("uses the singular label for a single reason", () => {
    render(
      <InterestingSection
        interesting={{ severity: "info", reasons: ["Rule: First ever"] }}
      />,
    );
    expect(screen.getByText("Reason")).toBeInTheDocument();
  });

  it("still shows the severity when a match carries no reasons", () => {
    // An empty reason list is a backend that told us less than it should.
    // The severity is still true and still worth stating; the reason row
    // falls back to the panel-wide Unknown rather than rendering blank.
    render(
      <InterestingSection interesting={{ severity: "info", reasons: [] }} />,
    );
    expect(screen.getByText("Info")).toBeInTheDocument();
    expect(screen.queryByTestId("interesting-reasons")).not.toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });
});
