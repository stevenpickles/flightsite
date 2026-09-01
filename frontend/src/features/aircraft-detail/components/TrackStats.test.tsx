import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TrackStats } from "@/features/aircraft-detail/components/TrackStats";

describe("TrackStats", () => {
  it("shows a quiet message when nothing has accumulated yet", () => {
    render(<TrackStats track={null} />);
    expect(screen.getByText(/No track accumulated yet/i)).toBeInTheDocument();
  });

  it("shows a quiet message for a track with zero points", () => {
    render(<TrackStats track={{ icao: "aaaaaa", points: [] }} />);
    expect(screen.getByText(/No track accumulated yet/i)).toBeInTheDocument();
  });

  it("shows point count and duration for an accumulated track", () => {
    render(
      <TrackStats
        track={{
          icao: "aaaaaa",
          points: [
            { lat: 47, lon: -122, at: 0 },
            { lat: 47.1, lon: -122, at: 3000 },
            { lat: 47.2, lon: -122, at: 12000 },
          ],
        }}
      />,
    );
    expect(screen.getByText(/3 points/)).toBeInTheDocument();
    expect(screen.getByText(/12s since selection/)).toBeInTheDocument();
  });

  it("uses singular wording for exactly one point", () => {
    render(
      <TrackStats
        track={{ icao: "aaaaaa", points: [{ lat: 47, lon: -122, at: 0 }] }}
      />,
    );
    expect(screen.getByText(/1 point\b/)).toBeInTheDocument();
  });
});
