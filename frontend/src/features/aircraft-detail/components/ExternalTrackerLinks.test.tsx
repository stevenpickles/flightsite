import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ExternalTrackerLinks } from "@/features/aircraft-detail/components/ExternalTrackerLinks";

describe("ExternalTrackerLinks", () => {
  it("shows a fallback message when no identifier is usable for any service", () => {
    render(
      <ExternalTrackerLinks
        aircraft={{ icao: "", callsign: null, registration: null }}
      />,
    );
    expect(
      screen.getByText(/No external identifier available yet/i),
    ).toBeInTheDocument();
  });

  it("renders every link with new-tab and security attributes", () => {
    render(
      <ExternalTrackerLinks
        aircraft={{ icao: "ae1463", callsign: "RCH471", registration: "N1" }}
      />,
    );
    for (const link of screen.getAllByRole("link")) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link.getAttribute("rel")).toContain("noopener");
      expect(link.getAttribute("rel")).toContain("noreferrer");
    }
  });
});
